"""Can her mind be reached? One word asked of the chosen online model, the way a call asks it.

    python -m settings.probe          her mind as a call builds it, its declared backup with it. A key that exists can
                                      still be refused, belong to another endpoint, or lack the model: said in one plain
                                      line. Exit 0 when it answers.
    python -m settings.probe answer   ./vx up and ./vx ready (vx mind_answers): her chosen online mind alone, never its
                                      backup (vx asks that one itself), bounded in time (VX_MIND_WAIT seconds). Exit 0 when
                                      a word came back; else NOT_THERE (3) when its provider has no such model there (a
                                      setup that can never work: not_there), 1 for anything else, then what happened on one
                                      line, by structure ("refused STATUS": its provider's own 4xx; "silent": no answer in
                                      time, the only one that may pass by asking again; "failed [STATUS]": a server error,
                                      no connection, or an answer with no word in it) and the same in plain words on the
                                      next (no gender, no path: the app shows it).

What is only for now (a key or a subscription refused, a limit, a server error, no answer in time) is her declared
backup's to answer, at a start and in ./vx ready alike; only NOT_THERE is never covered by a backup (vx mind_answers).
Either way an answer is a word: a stream that ends with none (usage only, or nothing) is not one."""
import asyncio
import os
import select
import stat
import sys

NAMES = {"ollama": "Ollama", "openai": "OpenAI", "anthropic": "Anthropic", "xai": "SpaceXSI", "xai_plan": "SpaceXSI", "chatgpt_plan": "ChatGPT"}
# What a provider's refusal is, in plain words, by its own HTTP status (never its wording); another 4xx is "refused it".
REFUSED = {401: "{p} refused its key", 403: "{p} does not let its key use this model", 404: "{p} does not have this model",
           429: "{p}'s limit is reached"}
# The same for a mind on your subscription, signed in by Light itself (QUEEN=xai_plan): it has no key
SIGNED_IN = {"xai_plan", "chatgpt_plan"}
REFUSED_PLAN = {**REFUSED, 401: "{p} needs you to sign in again (Settings, System)", 402: "{p}'s limit is reached",
                403: "{p} does not let your subscription be used here"}
# A setup that can never work: the provider answered that it has no such model there (not deployed on that endpoint, or
# not offered to that account). Exit code of `answer`, and of ./vx ready, so the settings page can say so.
NOT_THERE = 3
THERE_NOT = "{p} does not have the model {m}"  # (its plain words: the model as configured, never the provider's words)
# Statuses that are only for now, whatever else the answer says: a key or a subscription refused (401, 403), a payment
# or plan limit (402), no answer in time (408), a conflict (409), a limit (429). Her backup answers meanwhile.
FOR_NOW = frozenset({401, 402, 403, 408, 409, 429})
# Providers' own error codes for "no such model or deployment" (OpenAI, Azure OpenAI, Anthropic), matched whole: they
# make another client error (400, 422) a setup that can never work, as HTTP 404 is by itself.
NO_SUCH_MODEL = frozenset({"model_not_found", "DeploymentNotFound", "not_found_error"})


class Unanswered(Exception):
    """Her mind's stream ended with no word in it."""


async def ask(llm=None, wait: float | None = None) -> None:
    from brain.queen import queen_llm
    from livekit.agents import APIConnectOptions
    from livekit.agents.llm import ChatContext
    chat = ChatContext.empty()
    chat.add_message(role="user", content="Say OK.")
    # (one attempt, in the time it is given: its own retries would only stretch a refusal past it)
    stream = (llm or queen_llm()).chat(chat_ctx=chat, **({"conn_options": APIConnectOptions(max_retry=0, timeout=wait)} if wait else {}))
    try:
        async for chunk in stream:
            if str(getattr(getattr(chunk, "delta", None), "content", None) or "").strip():
                return
    finally:
        await stream.aclose()
    raise Unanswered


def why(error: Exception, provider: str = "") -> str:
    code = getattr(error, "status_code", None)
    words = ({401: "a sign-in is needed again", 402: "the limit is reached", 403: "the subscription may not be used here"}
             if provider in SIGNED_IN else {401: "the key was refused", 403: "the key may not use this model"})
    return {**words, 404: "the model was not found there", 429: "the limit is reached"}.get(code) or ("no answer in time" if isinstance(error, asyncio.TimeoutError) else
                                                         "no word in its answer" if isinstance(error, Unanswered) else
                                                         f"{type(error).__name__}{f' {code}' if code else ''}")


def codes(body) -> set:
    """A provider's own error codes in its answer's body, by its structure only: "code" and "type", at its top and in
    its "error" object (the OpenAI SDK keeps the inner object, Anthropic's the whole answer, a redacted one is JSON
    text). Never its message."""
    import json
    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except ValueError:
            return set()
    found, places = set(), [body]
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        places.append(body["error"])
    for place in places:
        if isinstance(place, dict):
            found |= {str(place[k]) for k in ("code", "type") if isinstance(place.get(k), (str, int))}
    return found


def not_there(error: Exception) -> bool:
    """Whether the provider answered that it has no such model there: a setup that can never work (NOT_THERE). Decided
    by its HTTP status (404) or its own error code (NO_SUCH_MODEL) on another client error; a status in FOR_NOW is
    never this, whatever its code says (a refused key or a limit is her backup's to answer)."""
    from livekit.agents import APIStatusError
    if not isinstance(error, APIStatusError) or getattr(error, "turned_off", False):
        return False
    code = error.status_code
    if not 400 <= code < 500 or code in FOR_NOW:
        return False
    return code == 404 or bool(codes(error.body) & NO_SUCH_MODEL)


def happened(error: Exception, provider: str) -> tuple[str, str]:
    """What happened to an online mind that gave no word, and its plain words, by the error's type and its provider's
    own HTTP status: no answer in time ("silent": it may pass by asking again), a refusal (4xx), else failed (a server
    error, no connection, or an answer with no word)."""
    from livekit.agents import APIStatusError, APITimeoutError
    name = NAMES.get(provider, provider)
    if isinstance(error, (APITimeoutError, asyncio.TimeoutError)):  # (first: a timeout is also a connection error)
        return "silent", f"{name} is not answering"
    code = error.status_code if isinstance(error, APIStatusError) else -1
    if getattr(error, "turned_off", False):  # (you turned it off, and no backup is declared: brain/queen._TurnedOff)
        return f"refused {code}", f"{name}: your subscription is turned off for the conscious mind (Settings, System)"
    if 400 <= code < 500:
        return f"refused {code}", (REFUSED_PLAN if provider in SIGNED_IN else REFUSED).get(code, "{p} refused it").format(p=name)
    if isinstance(error, Unanswered):
        return "failed", f"{name} gave no answer"
    if code >= 500:
        return f"failed {code}", f"{name} answered with an error"
    return "failed", f"{name} could not be reached"


def answer(*, attended=False) -> int:
    from core import chatgpt_sign_in, grok_sign_in
    grok_sign_in.checking()  # (a check: it never forces a refresh for a refusal, and never signs her out)
    provider, wait = os.environ.get("QUEEN", "ollama"), float(os.environ.get("VX_MIND_WAIT") or 25)
    if provider == "chatgpt_plan":
        status = chatgpt_sign_in.connection.status()
        state = status["state"]
        if state == "connected":
            models = status.get("models")
            if models is not None and os.environ.get("QUEEN_MODEL") not in models:
                state = "model_unavailable"
            elif not attended or not live_setup():
                print("connected")
                return 2
            else:
                from brain import greeting
                try:
                    if asyncio.run(greeting.write_first(attended=live_setup)):
                        return 0
                    if not live_setup():
                        print("connected")
                        return 2
                    state = "stream_ended"
                except Exception as error:
                    state = getattr(error, "plan_state", "unavailable")
        status_code = {"limited": 429, "model_unavailable": 404, "unavailable": 503,
                       "refresh_unavailable": 503, "stream_ended": 503, "timeout": 504}.get(state, 401)
        print(f"{'failed' if status_code >= 500 else 'refused'} {status_code}")
        print(chatgpt_sign_in.STOP_WORDS.get(state, chatgpt_sign_in.STOP_WORDS["unavailable"]))
        return 1  # (a subscription that does not offer the model is its backup's to answer, as any refusal of a plan)
    from brain.queen import _mind
    try:
        mind = _mind(provider, os.environ["QUEEN_MODEL"], os.environ.get("QUEEN_EFFORT"), os.environ.get("QUEEN_URL"))
        asyncio.run(asyncio.wait_for(ask(mind, wait), wait + 2))
    except Exception as e:  # noqa: BLE001 (any failure is the answer: decided by its type and status, never its words)
        there = not_there(e)
        print(f"her mind did not answer: {type(e).__name__} {getattr(e, 'status_code', '')}{' (no such model there)' if there else ''}"
              .rstrip(), file=sys.stderr)
        kind, words = happened(e, provider)
        if there:
            words = THERE_NOT.format(p=NAMES.get(provider, provider), m=os.environ.get("QUEEN_MODEL", ""))
        print(f"{kind}\n{words}")
        return NOT_THERE if there else 1
    return 0


def live_setup() -> bool:
    """The AppKit setup window holds open the writing end of this start's input pipe."""
    if os.environ.get("VX_SETUP_WINDOW") != "1" or not os.environ.get("VX_FROM_APP") or os.environ.get("VX_KEEPING"):
        return False
    try:
        return stat.S_ISFIFO(os.fstat(0).st_mode) and not select.select([0], [], [], 0)[0]
    except OSError:
        return False


def connection_reason() -> str:
    """Check the current connection without asking a model or refreshing the grant."""
    from core import chatgpt_sign_in as sign_in
    from core.provider_switch import turned_off
    from core.state import logs

    try:
        state = ("off" if turned_off(sign_in.NEEDS, marker=logs() / f"{sign_in.NEEDS}.off")
                 else sign_in.connection.status()["state"])
    except (OSError, ValueError, sign_in.SignInError):
        state = "unavailable"
    return "" if state == "connected" else sign_in.STOP_WORDS.get(state, sign_in.STOP_WORDS["unavailable"])


if __name__ == "__main__":
    if sys.argv[1:] == ["connection"]:
        print(connection_reason())
        sys.exit(0)
    if sys.argv[1:] in (["answer"], ["greeting"]) or os.environ.get("QUEEN") == "chatgpt_plan":
        sys.exit(answer(attended=sys.argv[1:] == ["greeting"]))
    from core import grok_sign_in
    grok_sign_in.checking()
    provider = os.environ.get("QUEEN", "ollama")
    try:
        asyncio.run(asyncio.wait_for(ask(), 25))
    except Exception as e:  # noqa: BLE001 (any failure is the answer)
        print(f"Her mind could not be reached on {NAMES.get(provider, provider)} ({why(e, provider)}).")
        sys.exit(1)
