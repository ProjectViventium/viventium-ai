"""Public Responses transport for the selected Light-owned ChatGPT grant."""
import asyncio
import time
from contextlib import asynccontextmanager, suppress

import httpx2 as httpx
import openai
from livekit.agents import APIConnectionError, APIStatusError

from core import accounts, chatgpt_authorization as auth, chatgpt_sign_in as sign_in

_catalogs: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {}
NAMESPACE = "viventium"
PRIVATE_REQUEST_FIELDS = frozenset((
    "background", "conversation", "max_output_tokens", "max_tool_calls", "max_tokens", "metadata", "moderation",
    "multi_agent", "previous_response_id", "prompt", "prompt_cache_retention", "safety_identifier", "service_tier",
    "temperature", "top_logprobs", "top_p", "truncation", "user",
))
STREAM_STATUS = {
    "subscription_sharing_usage_limit_exceeded": 429,
    "subscription_sharing_usage_unavailable": 503,
    "subscription_sharing_user_unavailable": 503,
    "subscription_sharing_user_not_eligible": 403,
    "subscription_sharing_invalid_user": 401,
    "subscription_sharing_unsupported_capability": 400,
    "subscription_sharing_route_not_supported": 403,
    "chatpass_v2_scope_not_authorized": 403,
    "chatpass_v2_invalid_authorization_context": 403,
}


def _request(values):
    """Adapt LiveKit's serialization to the documented direct-plan request shape."""
    request = {key: value for key, value in values.items() if key not in PRIVATE_REQUEST_FIELDS}
    messages = request["input"]
    if not isinstance(messages, list):
        raise ValueError("ChatGPT plan requests need explicit history")
    request["input"] = [
        ({**item, "role": "developer"} if item.get("role") == "system"
         else {**item, "namespace": NAMESPACE} if item.get("type") in ("function_call", "function_call_output")
         else item)
        for item in messages
    ]
    tools = [tool for tool in request.get("tools", ()) if tool["type"] == "function"]
    request["tools"] = [{"type": "namespace", "name": NAMESPACE, "description": "Viventium AI functions",
                         "tools": tools}] if tools else []
    if isinstance(request.get("tool_choice"), dict):
        request["tool_choice"] = {**request["tool_choice"], "namespace": NAMESPACE}
    return {**request, "store": False, "stream": True}


def _bearer(grant):
    return {"Authorization": f"Bearer {grant.token}"}


def _health(status):
    with suppress(OSError):
        if status is None:
            if accounts.states().get(accounts.route(sign_in.NEEDS), {}).get("state"):
                accounts.up(sign_in.NEEDS, seen=time.time())
        else:
            accounts.down(sign_in.NEEDS, accounts.failure_of(status), seen=time.time())


def _auth_error(error):
    state = sign_in.stop_state(error)
    status = 429 if state == "limited" else 404 if state == "model_unavailable" else (
        401 if isinstance(error, sign_in.NotSignedIn) else 503)
    if state in ("signed_out", "revoked", "scope_missing", "refresh_unavailable"):
        _health(status)
    return _plan_error(state, status)


def _plan_error(state, status, **details):
    error = APIStatusError(sign_in.STOP_WORDS[state], status_code=status, retryable=False, **details)
    error.plan_state = state
    return error


async def _models(http, grant, timeout):
    key = (grant.account, grant.session)
    until, models = _catalogs.get(key, (0, ()))
    if until > time.monotonic():
        return models
    reply = await http.get(sign_in.API + "/models", headers=_bearer(grant), timeout=timeout)
    if not reply.is_success:
        raise openai.APIStatusError("ChatGPT model catalog request failed", response=reply, body=sign_in._body(reply))
    models = sign_in.model_slugs(sign_in._body(reply))
    await asyncio.to_thread(sign_in.connection.save_catalog, grant, models)
    _catalogs.clear()
    _catalogs[key] = (time.monotonic() + 300, models)
    return models


async def _still(grant, admission=None):
    try:
        if admission is not None:
            await asyncio.to_thread(auth.require, admission, (admission.purpose,))
        await asyncio.to_thread(sign_in.connection.ensure_current, grant)
    except sign_in.SignInError as error:
        raise _auth_error(error) from None


@asynccontextmanager
async def _watch(grant, close=None, *, admission=None):
    """Race stream I/O with authorization checks, including while no bytes arrive."""
    async def watch():
        try:
            while True:
                await _still(grant, admission)
                await asyncio.sleep(0.2)
        except APIStatusError:
            if close is not None:
                with suppress(httpx.HTTPError, RuntimeError):
                    await close()
            raise

    watcher = asyncio.create_task(watch())
    try:
        yield watcher
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


async def _checked(operation, watcher):
    pending = asyncio.ensure_future(operation)
    try:
        await asyncio.wait((pending, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher.done():
            if pending.done() and not pending.cancelled():
                pending.exception()  # retrieve the losing operation's exception
            watcher.result()
        return pending.result()
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


def _error(status, code="", identifier=None, body=None):
    # Retain documented codes and the live HTTP status. Provider text may echo inputs or credentials.
    structured = {"error": {"code": code}} if code in STREAM_STATUS else {"detail": "ChatGPT plan request failed"}
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        structured = {"error": structured.get("error", {})}
    identifier = identifier if identifier and identifier.isascii() and len(identifier) <= 128 else None
    state = {401: "unauthorized", 403: "refused", 429: "limited"}.get(status, "unavailable")
    return _plan_error(state, status, request_id=identifier, body=structured)


async def _pause(grant, headers=None):
    retry_after = (headers or {}).get("retry-after", "")
    # (the provider's own retry time; without one, the connection's own rest, longer while the limit lasts)
    seconds = int(retry_after) if retry_after.isascii() and retry_after.isdecimal() and len(retry_after) < 9 else None
    with suppress(sign_in.NotSignedIn):
        await asyncio.to_thread(sign_in.connection.pause, grant, seconds)


class _Stream:
    def __init__(self, stream, grant, names, admission=None, *, helper=False):
        self.stream = stream
        self.grant = grant
        self.names = names
        self.admission = admission
        self.helper = helper

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self.stream.__aexit__(*exc)

    async def __aiter__(self):
        async with _watch(self.grant, getattr(self.stream, "close", None), admission=self.admission) as watcher:
            events = self.events()
            try:
                while True:
                    yield await _checked(anext(events), watcher)
            except StopAsyncIteration:
                return
            finally:
                if close := getattr(events, "aclose", None):
                    await close()

    async def _failed(self, code):
        """The plan's own failure, by its documented code: paused while limited, its health said, and the person told."""
        status = STREAM_STATUS.get(code, -1)
        if status == 429:
            await _pause(self.grant)
        await asyncio.to_thread(_health, status)
        if status == 401:
            # Prepare the next request. The current turn may have shown text.
            with suppress(sign_in.SignInError):
                await asyncio.to_thread(sign_in.connection.mark_refused, self.grant)
        from brain.queen import _scrubbed
        raise _scrubbed(_error(status, code, self.stream.response.headers.get("x-request-id")),
                        self.grant.token) from None

    async def events(self):
        calls = []
        stream = aiter(self.stream)
        while True:
            try:
                event = await anext(stream)
            except StopAsyncIteration:
                break
            except openai.APIError as error:
                # (an event whose data carries "error" is raised by the SDK's own stream parser before it reaches us:
                # a bare APIError with that error as its body. Its documented code goes the way the event's would.)
                if isinstance(error, (openai.APIStatusError, openai.APIConnectionError)):
                    raise
                await self._failed(error.code)
            if event.type in ("response.failed", "error", "response.incomplete"):
                info = getattr(getattr(event, "response", None), "error", None)
                await self._failed(getattr(info or event, "code", None))
            if event.type == "response.output_item.done" and event.item.type == "function_call":
                item = event.item
                if item.name not in self.names or getattr(item, "namespace", NAMESPACE) not in (None, NAMESPACE):
                    raise APIConnectionError("ChatGPT returned a function that Light did not offer", retryable=False)
                calls.append(event)
                continue
            if event.type == "response.completed":
                await _still(self.grant, self.admission)
                for call in calls:
                    yield call
                yield event
                await asyncio.to_thread(_health, None)
                with suppress(sign_in.SignInError):  # (it answered: its next limit rests from the first pause again)
                    await asyncio.to_thread(sign_in.connection.answered, self.grant)
                return
            if event.type == "response.refusal.delta":
                if self.helper:
                    raise APIStatusError("ChatGPT declined the helper request", status_code=422, retryable=False)
                # The standard LiveKit Responses engine renders only output-text deltas.
                event = openai.types.responses.ResponseTextDeltaEvent(
                    type="response.output_text.delta", delta=event.delta, item_id=event.item_id,
                    output_index=event.output_index, content_index=event.content_index,
                    sequence_number=event.sequence_number, logprobs=[])
            yield event
        raise _plan_error("stream_ended", 503)


def client(*, purpose=None):
    """Reuse LiveKit's Responses streaming and tool engine with a per-request plan credential."""
    from brain.queen import _off_now, _scrubbed

    http = httpx.AsyncClient(follow_redirects=False, trust_env=False)
    sdk = openai.AsyncOpenAI(api_key="light-auth-supplied-per-request", base_url=sign_in.API,
                            max_retries=0, http_client=http)
    create = sdk.responses.create

    async def plan_request(**values):
        # An attended helper borrows the existing turn instead of making a new admission.
        roles = auth.ATTENDED if purpose is None else (auth.Purpose.TURN if purpose == auth.Purpose.HELPERS else purpose,)
        try:
            admission = await asyncio.to_thread(auth.require, auth.current.get(), roles)
        except sign_in.SignInError as error:
            raise _auth_error(error) from None
        request = _request(values)
        grant = None
        for attempt in range(2):
            if await _off_now(sign_in.NEEDS):
                raise _plan_error("off", 401)
            try:
                grant = await asyncio.to_thread(sign_in.connection.authorization, grant,
                                                admitted=admission)
                names = await _models(http, grant, request.get("timeout"))
                if request["model"] not in names:
                    raise sign_in.NotEntitled
                await _still(grant, admission)
                if await _off_now(sign_in.NEEDS):
                    raise _plan_error("off", 401)
                async with _watch(grant, admission=admission) as watcher:
                    result = await _checked(create(**request, extra_headers=_bearer(grant)), watcher)
            except sign_in.SignInError as error:
                raise _auth_error(error) from None
            except openai.APIStatusError as error:
                if error.status_code == 401 and attempt == 0:
                    continue
                if error.status_code == 429:
                    await _pause(grant, error.response.headers)
                await asyncio.to_thread(_health, error.status_code)
                shaped = _error(error.status_code, error.code, error.request_id, error.body)
                raise _scrubbed(shaped, grant.token) from None
            except (httpx.TimeoutException, openai.APITimeoutError):
                raise _plan_error("timeout", 504) from None
            except (httpx.HTTPError, openai.APIConnectionError):
                raise _plan_error("unavailable", 503) from None
            else:
                functions = {tool["name"] for space in request["tools"] for tool in space["tools"]}
                return _Stream(result, grant, functions, admission, helper=purpose == auth.Purpose.HELPERS)

    sdk.responses.create = plan_request
    return sdk
