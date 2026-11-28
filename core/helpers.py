"""Her quick helpers: the small questions asked beside the conversation (a one-word check, Deep Memory's judgement,
Feelings' appraisal, a summary of your Life). Not the one you talk to: these never speak.

Where they are asked is the profile's HELPERS, first to last, for every question, a quick check during a call too; the
first that answers is used, and a helper that fails is passed over for a while (a missing deployment or key for ten
minutes, a timeout for one). The requirement for Hybrid, which had kept them on this Mac: every model that is not the
one you talk to runs online, Claude first with OpenAI as its fallback (without that, Hybrid could not go live):

    HELPERS=claude:claude-opus-5-5,openai:gpt-6.1-sol,mac       Hybrid and Cloud: Claude, then OpenAI, then this Mac
    (unset)                                                      Local: this Mac (MEMORY_URL, MEMORY_MODEL)

A question's time (`wait`) is shared in that order: each helper gets what is left, less a moment kept for this Mac when
it is the backup still to come, so a slow online helper never leaves the last backup no time at all. Nothing is moved
ahead of his order to be faster: a quick check put this Mac before OpenAI (HELPERS_FAST);
that setting is no longer read. Each answer says which one gave it (`Answer.route`), what failed before it and why
(`tried`), how long each one took (`took`) and the time it had (`budget`).

claude: your Anthropic key, signed-in Claude Code, or the model on your Microsoft Foundry resource.
openai: the OpenAI mind's Responses endpoint and key, or your explicit helper endpoint.
chatgpt_plan: Light's selected ChatGPT grant, inside an attended turn.
mac: this Mac's helper server.
"""
import asyncio
import subprocess
import json
import logging
import os
import re
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("helpers")

SLOW, DOWN = 60.0, 600.0  # seconds a helper is passed over: after a timeout or outage; after a missing key or model
# What is kept for this Mac when it is the backup still to come: warm, it answers a quick check in 0.05 to 0.2 s.
MAC_RESERVE = 0.5
_down: dict[str, float] = {}
UNSET = ("no_key", "not_here")  # nothing to ask there yet: never passed over, only skipped
# This request's own setting or content refused (a 400, or the model's refusal): about the request, never the helper's health
REQUEST_REFUSED = ("status_400", "status_422", "refused")
_said_fast = False  # (HELPERS_FAST set somewhere: said once in the log that it is not read)
# A helper is passed over only for a real failure: unreachable, a 5xx, a limit, a sign-in or deployment missing, or a
# timeout at its own full time (FULL). A timeout inside any shorter time a caller gave is that caller's, never the helper's.
FULL = 20.0
CLAUDE_OPUS = "claude-opus-5-5"
OPENAI_SOL = "gpt-6.1-sol"
# Thinking effort, low to high, and the levels each helper takes (a card may ask for one its model has not: it gets the
# nearest, as a Worker does, brain/rounds._effort_on)
LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
EFFORTS = {"claude": ("low", "medium", "high", "xhigh", "max"), "openai": ("none", "low", "medium", "high", "xhigh"),
           "mac": ("none", "low", "medium", "high")}


def nearest(kind: str, effort: str, *, model: str = "") -> str:
    """The level of `effort` this helper takes, or the nearest it has (the lower one on a tie)."""
    have = ("low", "medium", "high") if kind in ("openai", "chatgpt_plan") and model == OPENAI_SOL else EFFORTS.get(kind) or LEVELS
    if effort in have or effort not in LEVELS:
        return effort
    at = LEVELS.index(effort)
    return min(have, key=lambda level: (abs(LEVELS.index(level) - at), LEVELS.index(level)))


@dataclass
class Answer:
    text: str = ""
    route: str = ""  # claude | openai | mac, "" when none answered
    model: str = ""
    tried: list[tuple[str, str]] = field(default_factory=list)  # (route, why it was passed over), in order
    took: list[tuple[str, float]] = field(default_factory=list)  # (route, seconds), each one asked, in order
    budget: float = 0.0  # the time the question had, in seconds


def routes(fast: bool = False) -> list[tuple[str, str]]:
    """The helpers to ask, in his order (HELPERS): [(kind, model)]. The same for a quick check (fast)."""
    global _said_fast
    if os.environ.get("HELPERS_FAST") and os.environ.get("HELPERS_FAST") != os.environ.get("HELPERS") and not _said_fast:
        _said_fast = True
        log.info("HELPERS_FAST is not read: a quick check follows HELPERS, his order")
    from core import chatgpt_authorization as auth

    approval = auth.current.get()
    attended = approval is not None and approval.purpose == auth.Purpose.TURN and not approval.denied
    spec = os.environ.get("HELPERS") or "mac"
    out = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        kind, _, model = part.partition(":")
        kind = kind.strip()
        if kind == "chatgpt_plan" and not attended:
            continue
        default = os.environ.get("MEMORY_MODEL", "qwen3.6:latest") if kind == "mac" else OPENAI_SOL if kind == "chatgpt_plan" else ""
        out.append((kind, model.strip() or default))
    if attended and os.environ.get("QUEEN") == "chatgpt_plan" and all(kind != "chatgpt_plan" for kind, _ in out):
        out.insert(0, ("chatgpt_plan", OPENAI_SOL))
    return out


def available() -> bool:
    """Whether any helper can be asked here (an online one, or this Mac's helper server)."""
    return any(kind != "mac" or os.environ.get("MEMORY_URL") for kind, _ in routes())


def online() -> bool:
    """Whether the first helper is online (the settings page and the docs say where they run)."""
    first = routes()[0][0] if routes() else "mac"
    return first != "mac"


QUICK = ("", "none", "minimal")  # efforts at which a helper answers without thinking first


def _online_wait(kind: str, left: float, later: list[tuple[str, str]]) -> float:
    if kind in ("claude", "xai_plan", "chatgpt_plan") and _openai_access()[1] and any(
            name == "openai" and _down.get(f"{name}:{model}", 0) <= time.monotonic() for name, model in later):
        return left / 2
    return left


def ask(messages: list[dict], *, max_tokens: int, wait: float, json_out: bool = False, fast: bool = False,
        think: bool = False, effort: str = "", only: list[tuple[str, str]] | None = None) -> Answer:
    """One answer from the first helper that gives one, asked in his order. messages: OpenAI-style [{role, content}],
    system first. think: it thinks before it answers (a summary of your Life must be true; a one-word check must be
    quick). fast: a quick check during a call (this Mac's helper is then kept loaded for the next one).
    effort: the exact thinking effort a card chose (low … max, or none), given to every helper as its own setting
    (Claude's effort, OpenAI's reasoning effort, this Mac's reasoning effort); unset, each helper's usual level.
    only: these of his helpers, in his order (unset: all of them). The Subconscious asks the online ones here and this
    Mac's itself, where its part waits for her and stops when she speaks (brain/rounds.py)."""
    if effort:
        think = effort not in QUICK
    answer = Answer(budget=wait)
    deadline = time.monotonic() + wait
    order = routes(fast) if only is None else [route for route in routes(fast) if route in only]
    for at, (kind, model) in enumerate(order):
        name = f"{kind}:{model}"
        left = deadline - time.monotonic()
        if left <= 0.05:
            answer.tried.append((kind, "out_of_time"))
            break
        if _down.get(name, 0) > time.monotonic():
            answer.tried.append((kind, "passed_over"))
            continue
        # (this Mac still to come as the backup: a moment is kept for it, so a slow helper never takes it all)
        keep = MAC_RESERVE if kind != "mac" and os.environ.get("MEMORY_URL") and any(
            later == "mac" and _down.get(f"{later}:{m}", 0) <= time.monotonic() for later, m in order[at + 1:]) else 0.0
        given = _online_wait(kind, max(left - keep, min(left, 0.2)), order[at + 1:])
        began = time.monotonic()
        try:
            ask_one = {"claude": _claude, "openai": _openai, "mac": _mac, "xai_plan": _grok_sync,
                       "chatgpt_plan": _chatgpt_sync}[kind]
            text = ask_one(model, messages, max_tokens, given, json_out, think, fast,
                           **({"effort": nearest(kind, effort)} if effort else {}))
        except KeyError:
            answer.tried.append((kind, "unknown_helper"))
            continue
        except Unavailable as e:
            # Passed over for a while only for what is the helper's: never a setting not there yet (a key added is
            # used at once), a caller's time too short to answer in, or a refusal of the request's own setting (400).
            short = e.why == "timeout" and given < FULL
            if kind != "chatgpt_plan" and e.why not in UNSET and not short and e.why not in REQUEST_REFUSED:
                _down[name] = time.monotonic() + (DOWN if e.lasting else SLOW)
            if e.why not in UNSET:
                answer.took.append((kind, round(time.monotonic() - began, 3)))
            if short:
                e.why = "timeout_short_budget"
            answer.tried.append((kind, e.why))
            log.debug("helper %s passed over: %s", name, e.why)
            continue
        answer.took.append((kind, round(time.monotonic() - began, 3)))
        if text.strip():
            answer.text, answer.route, answer.model = text.strip(), kind, model
            return answer
        answer.tried.append((kind, "empty"))
    return answer


def json_object(text: str):
    """The first JSON object in a helper's answer (a model may wrap it in a code fence), or None."""
    found = re.search(r"\{.*\}", text or "", re.S)
    if not found:
        return None
    try:
        return json.loads(found.group(0))
    except ValueError:
        return None


async def ask_async(messages: list[dict], *, max_tokens: int, wait: float, json_out: bool = False,
                    think: bool = False, effort: str = "", only: list[tuple[str, str]] | None = None) -> Answer:
    """Cancellable online helpers for background parts. The same order, health and receipts as ask()."""
    answer = Answer(budget=wait)
    deadline = time.monotonic() + wait
    if effort:
        think = effort not in QUICK
    order = [r for r in routes() if r[0] != "mac" and (only is None or r in only)]
    for at, (kind, model) in enumerate(order):
        name = f"{kind}:{model}"
        left = deadline - time.monotonic()
        if left <= 0.05:
            answer.tried.append((kind, "out_of_time"))
            break
        if _down.get(name, 0) > time.monotonic():
            answer.tried.append((kind, "passed_over"))
            continue
        began = time.monotonic()
        given = _online_wait(kind, left, order[at + 1:])
        try:
            found_effort = nearest(kind, effort) if effort else ""
            if kind == "chatgpt_plan":
                text = await _chatgpt(model, messages, max_tokens, given, json_out, think, found_effort)
            else:
                text = await _online_async(kind, model, messages, max_tokens, given, json_out, think, found_effort)
        except Unavailable as e:
            short = e.why == "timeout" and given < FULL
            if kind != "chatgpt_plan" and e.why not in UNSET and not short and e.why not in REQUEST_REFUSED:
                _down[name] = time.monotonic() + (DOWN if e.lasting else SLOW)
            if e.why not in UNSET:
                answer.took.append((kind, round(time.monotonic() - began, 3)))
            answer.tried.append((kind, "timeout_short_budget" if short else e.why))
            continue
        answer.took.append((kind, round(time.monotonic() - began, 3)))
        if text.strip():
            answer.text, answer.route, answer.model = text.strip(), kind, model
            return answer
        answer.tried.append((kind, "empty"))
    return answer


async def _online_async(kind, model, messages, max_tokens, wait, json_out, think, effort):
    """Native SDK async clients: cancellation closes the in-flight request and its client."""
    if kind == "xai_plan":
        return await _grok(model, messages, max_tokens, wait, json_out, think, effort)
    if kind == "claude":
        import anthropic
        if os.environ.get("ANTHROPIC_API_KEY"):
            client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=0, timeout=wait)
        else:
            try:
                return await _claude_plan(model, messages, max_tokens, wait, json_out, think, effort)
            except Unavailable as error:
                if error.why != "no_key" or not (resource := _foundry_resource()) or not os.environ.get("OPENAI_API_KEY"):
                    raise
            client = anthropic.AsyncAnthropicFoundry(resource=resource, api_key=os.environ["OPENAI_API_KEY"],
                                                     max_retries=0, timeout=wait)
        try:
            async with client:
                reply = await client.messages.create(**_claude_request(model, messages, max_tokens, json_out, think, effort))
        except anthropic.APIError as e:
            raise _unavailable(e) from None
        if reply.stop_reason == "refusal":
            raise Unavailable("refused")
        return "".join(block.text for block in reply.content if block.type == "text")
    if kind != "openai":
        raise Unavailable("unknown_helper")
    import openai
    url, key = _openai_access()
    if not key:
        raise Unavailable("no_key", lasting=True)
    if os.environ.get("SMALL_MAC_TIER"):
        from brain.queen import _off_now
        if await _off_now("OPENAI_API_KEY"):
            raise Unavailable("no_key")
    try:
        async with openai.AsyncOpenAI(base_url=url, api_key=key, max_retries=0, timeout=wait) as client:
            reply = await client.responses.create(**_openai_request(model, messages, max_tokens, json_out, think, effort))
    except openai.APIError as e:
        raise _unavailable(e) from None
    return reply.output_text


def _chatgpt_sync(model, messages, max_tokens, wait, json_out, think, _fast, effort=""):
    return asyncio.run(_chatgpt(model, messages, max_tokens, wait, json_out, think, effort))


async def _chatgpt(model, messages, max_tokens, wait, json_out, think, effort):
    from core import chatgpt_authorization as auth, chatgpt_responses
    from livekit.agents import APIError

    values = _openai_request(model, messages, max_tokens, json_out, think, effort)
    try:
        async with asyncio.timeout(wait), chatgpt_responses.client(purpose=auth.Purpose.HELPERS) as client:
            stream = await client.responses.create(**values, timeout=wait)
            async with stream:
                parts = [event.delta async for event in stream if event.type == "response.output_text.delta"]
        text = "".join(parts)
        if json_out:
            try:
                valid = isinstance(json.loads(text), dict)
            except ValueError:
                valid = False
            if not valid:
                raise Unavailable("invalid_json")
        return text
    except (APIError, TimeoutError) as error:
        if state := getattr(error, "plan_state", None):
            raise Unavailable("rate_limited" if state == "limited" else state) from None
        raise _unavailable(error) from None


def _grok_sync(model, messages, max_tokens, wait, json_out, think, _fast, effort="") -> str:
    return asyncio.run(_grok(model, messages, max_tokens, wait, json_out, think, effort))


async def _grok(model, messages, max_tokens, wait, json_out, think, effort="") -> str:
    from brain.queen import _mind
    from livekit.agents import APIConnectOptions, APIError
    from livekit.agents.llm import ChatContext

    chat = ChatContext()
    for message in messages:
        chat.add_message(role=message["role"], content=message["content"])
    if json_out:
        chat.add_message(role="system", content="Reply with one JSON object and nothing else.")
    mind = _mind("xai_plan", model, "low" if effort in QUICK else effort or "low", None)
    try:
        async with asyncio.timeout(wait):
            async with mind.chat(chat_ctx=chat, conn_options=APIConnectOptions(max_retry=0, timeout=wait),
                                 extra_kwargs={"max_output_tokens": max_tokens + (8000 if think else 1000)}) as stream:
                return "".join([chunk.delta.content async for chunk in stream if chunk.delta and chunk.delta.content])
    except (APIError, TimeoutError) as error:
        raise _unavailable(error) from None
    finally:
        await mind.aclose()


def _unavailable(error=None, *, status_code=None) -> "Unavailable":
    status, name = status_code or getattr(error, "status_code", None), type(error).__name__
    why = ("not_deployed" if status == 404 else "auth" if status in (401, 403) else "rate_limited" if status == 429 else
           "timeout" if "Timeout" in name else "unreachable" if "Connection" in name else f"status_{status}")
    return Unavailable(why, lasting=status in (400, 401, 403, 404))


class Unavailable(Exception):
    def __init__(self, why: str, lasting: bool = False):
        super().__init__(why)
        self.why, self.lasting = why, lasting


def _split(messages: list[dict], json_out: bool) -> tuple[str, list[dict]]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    if json_out:
        system += "\n\nReply with one JSON object and nothing else."
    rest = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
    if not rest or rest[0]["role"] != "user":
        rest.insert(0, {"role": "user", "content": "(begin)"})
    return system, rest


def claude_effort(think: bool, effort: str) -> str:
    return (effort or "medium") if think else "low"


def _claude_budget(model, max_tokens, think) -> int:
    return max(8, max_tokens) + (16000 if think else 400 if model == CLAUDE_OPUS else 0)


def _claude_request(model, messages, max_tokens, json_out, think, effort) -> dict:
    system, rest = _split(messages, json_out)
    request = {"model": model, "max_tokens": _claude_budget(model, max_tokens, think), "system": system, "messages": rest}
    if model == CLAUDE_OPUS:  # Opus 5.5 always reasons. Use low effort and leave room for its reply.
        request["output_config"] = {"effort": claude_effort(think, effort)}
    elif not think:
        request["thinking"] = {"type": "disabled"}
    elif effort not in QUICK:
        request["output_config"] = {"effort": effort}
    return request


async def _claude_process(args: list[str], env: dict, folder: str, prompt: str = "") -> tuple[int, dict]:
    """The Claude CLI started and read in a thread: asyncio's own subprocess transport starts a process on the event
    loop, and on a busy Mac one start of this CLI held a call's loop for 166 ms. Cancelled (its wait ran out), it is
    killed and reaped, as before."""
    proc = await asyncio.to_thread(subprocess.Popen, args, env=env, cwd=folder, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        raw, _ = await asyncio.to_thread(proc.communicate, prompt.encode())
    finally:
        if proc.poll() is None:
            with suppress(ProcessLookupError):
                proc.kill()
            await asyncio.to_thread(proc.wait)
    try:
        result = json.loads(raw)
    except ValueError:
        result = None
    return proc.returncode, result if isinstance(result, dict) else {}


async def _claude_plan(model, messages, max_tokens, wait, json_out, think, effort) -> str:
    """Use the owner's Claude Code sign-in through its own CLI, with no tools or saved session."""
    from settings.install import tool_path
    from settings.store import clean_env

    if not (tool := tool_path("claude")):
        raise Unavailable("no_key")
    env = clean_env()
    env.update(DISABLE_NONESSENTIAL_MODEL_CALLS="1", CLAUDE_CODE_DISABLE_TERMINAL_TITLE="1",
               CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(_claude_budget(model, max_tokens, think)))
    if not think and model != CLAUDE_OPUS:
        env["MAX_THINKING_TOKENS"] = "0"
    system, rest = _split(messages, json_out)
    prompt = rest[0]["content"] if len(rest) == 1 else json.dumps(rest, ensure_ascii=False)
    try:
        async with asyncio.timeout(wait):
            with tempfile.TemporaryDirectory(prefix="vx-claude-") as folder:
                _, auth = await _claude_process([tool, "auth", "status", "--json"], env, folder)
                if not auth.get("loggedIn") or auth.get("authMethod") != "claude.ai":
                    raise Unavailable("no_key")
                args = [tool, "--print", "--model", model, "--effort", claude_effort(think, effort),
                        "--output-format", "json", "--max-turns", "1", "--no-session-persistence", "--safe-mode",
                        "--tools", "", "--strict-mcp-config", "--no-chrome", "--permission-mode", "dontAsk"]
                if system:
                    path = Path(folder) / "system.txt"
                    path.write_text(system)
                    args.extend(["--system-prompt-file", str(path)])
                code, result = await _claude_process(args, env, folder, prompt)
    except TimeoutError:
        raise Unavailable("timeout") from None
    except OSError:
        raise Unavailable("unreachable") from None
    if code or result.get("is_error"):
        status = result.get("api_error_status")
        if status is not None:
            raise _unavailable(status_code=status)
        raise Unavailable("unreachable")
    if result.get("stop_reason") == "refusal":
        raise Unavailable("refused")
    if set(result.get("modelUsage") or {}) != {model}:
        raise Unavailable("not_deployed", lasting=True)
    text = result.get("result")
    return text if isinstance(text, str) else ""


def _claude(model: str, messages: list[dict], max_tokens: int, wait: float, json_out: bool, think: bool,
            fast: bool = False, effort: str = "") -> str:
    """Claude through your own key, your Claude Code sign-in, or your Microsoft Foundry resource."""
    import anthropic
    if os.environ.get("ANTHROPIC_API_KEY"):
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=0, timeout=wait)
    else:
        try:
            return asyncio.run(_claude_plan(model, messages, max_tokens, wait, json_out, think, effort))
        except Unavailable as error:
            if error.why != "no_key" or not (resource := _foundry_resource()) or not os.environ.get("OPENAI_API_KEY"):
                raise
        client = anthropic.AnthropicFoundry(resource=resource, api_key=os.environ["OPENAI_API_KEY"], max_retries=0,
                                            timeout=wait)
    try:
        reply = client.messages.create(**_claude_request(model, messages, max_tokens, json_out, think, effort))
    except anthropic.NotFoundError:
        raise Unavailable("not_deployed", lasting=True) from None
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        raise Unavailable("auth", lasting=True) from None
    except anthropic.RateLimitError:
        raise Unavailable("rate_limited") from None
    except anthropic.APITimeoutError:
        raise Unavailable("timeout") from None
    except anthropic.APIConnectionError:
        raise Unavailable("unreachable") from None
    except anthropic.APIStatusError as e:
        raise Unavailable(f"status_{e.status_code}", lasting=e.status_code == 400) from None
    if reply.stop_reason == "refusal":
        raise Unavailable("refused")
    return "".join(block.text for block in reply.content if block.type == "text")


def _foundry_resource() -> str:
    """The Microsoft Foundry resource her online mind uses (QUEEN_URL on an Azure host), "" when there is none."""
    host = urlsplit(os.environ.get("QUEEN_URL", "")).hostname or ""
    if os.environ.get("QUEEN") == "openai" and host.endswith((".azure.com", ".azure.us")):
        return host.split(".")[0]
    return ""


def _openai_access() -> tuple[str | None, str]:
    url = os.environ.get("HELPERS_OPENAI_URL")
    if not url and os.environ.get("QUEEN") == "openai":
        url = os.environ.get("QUEEN_URL")
    elif not url and os.environ.get("QUEEN_FALLBACK") == "openai":
        url = os.environ.get("QUEEN_FALLBACK_URL")
    key_name = "HELPERS_OPENAI_API_KEY" if os.environ.get("HELPERS_OPENAI_API_KEY_ITEM") else "OPENAI_API_KEY"
    return url or None, os.environ.get(key_name, "")


def openai_effort(model: str, think: bool, effort: str) -> str:
    requested = effort or ("medium" if think else os.environ.get("HELPERS_OPENAI_EFFORT", "low"))
    return nearest("openai", requested, model=model)


def _openai_request(model, messages, max_tokens, json_out, think, effort) -> dict:
    return {"model": model, "input": messages, "store": False,
            "max_output_tokens": max_tokens + (8000 if think else 400),
            "reasoning": {"effort": openai_effort(model, think, effort)},
            **({"text": {"format": {"type": "json_object"}}} if json_out else {})}


def _openai(model: str, messages: list[dict], max_tokens: int, wait: float, json_out: bool, think: bool,
            fast: bool = False, effort: str = "") -> str:
    """The OpenAI mind's Responses route, with the card's reasoning effort."""
    import openai
    url, key = _openai_access()
    if not key:
        raise Unavailable("no_key", lasting=True)
    if os.environ.get("SMALL_MAC_TIER"):
        from brain.queen import _turned_off
        if _turned_off("OPENAI_API_KEY"):
            raise Unavailable("no_key")
    try:
        with openai.OpenAI(base_url=url, api_key=key, max_retries=0, timeout=wait) as client:
            reply = client.responses.create(**_openai_request(model, messages, max_tokens, json_out, think, effort))
    except openai.APIError as e:
        raise _unavailable(e) from None
    return reply.output_text


def _mac(model: str, messages: list[dict], max_tokens: int, wait: float, json_out: bool, think: bool,
         fast: bool = False, effort: str = "") -> str:
    """This Mac's helper server (MEMORY_URL), as before: no thinking, the same model the questions were measured on.
    Asked during a call it is kept loaded (Ollama's keep_alive), so the next quick check finds it warm."""
    import openai
    if not os.environ.get("MEMORY_URL"):
        raise Unavailable("not_here", lasting=True)
    try:
        with openai.OpenAI(base_url=os.environ["MEMORY_URL"], api_key="local", max_retries=0, timeout=wait) as client:
            reply = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens + (8000 if think else 0), temperature=0,
                extra_body={"reasoning_effort": effort or ("high" if think else "none"), **({"keep_alive": -1} if fast else {})},
                **({"response_format": {"type": "json_object"}} if json_out else {}))
    except openai.APITimeoutError:
        raise Unavailable("timeout") from None
    except openai.APIConnectionError:
        raise Unavailable("unreachable") from None
    except openai.APIStatusError as e:
        raise Unavailable(f"status_{e.status_code}") from None
    return (reply.choices[0].message.content or "") if reply.choices else ""
