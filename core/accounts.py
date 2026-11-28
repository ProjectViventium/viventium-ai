"""Your accounts as Viventium last found them: each route it uses (a Worker's subscription, the mind's key), whether
it is answering, and if not, why, typed (a limit, a log-in needed, not answering) and since when. Written where it
is learned: a Worker's route found down or a job done on it (brain/queen.py, Workers), the mind set aside by its
backup or taken back (queen_llm). Read by the settings page, which shows it on the account. Typed facts only,
never a provider's words or a key.

Which accounts you turned off is not kept here: that is a choice of yours, kept with your other choices
(settings/service.py)."""
import fcntl
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar

from core.state import STATE_ROOT, closed_file

FILE = STATE_ROOT / "core" / "accounts.json"

# Captured when a request starts, never a process-wide readiness switch. A time limit on
# unattended writing says nothing about whether the account can answer its human.
BACKGROUND_WRITE: ContextVar[bool] = ContextVar("background_write", default=False)


@contextmanager
def background_write():
    """Scope unattended writing without hiding provider refusals or attended failures."""
    token = BACKGROUND_WRITE.set(True)
    try:
        yield
    finally:
        BACKGROUND_WRITE.reset(token)


# A Worker's harness, as the account it runs on (settings/catalog.py ACCOUNTS: plan ids)
PLANS = {"claude-code": "claude", "codex-cli": "codex", "grok-build": "grok"}
# A sign-in Light makes itself, for her mind (core/grok_sign_in): its own account, apart from the Worker's plan of the
# same provider (a Grok Build job done never clears what her mind's sign-in was last found)
OWN = {"grok_mind", "chatgpt_mind"}
# xPerfect's typed failure classes, as one word for the page
LIMITED = {"provider_rate_limited", "provider_quota_exhausted"}
SIGN_IN = {"provider_auth_missing", "provider_unauthorized"}
REFUSED = {"provider_forbidden"}  # (the key is known and valid, but not allowed this: its permissions, at the provider)


@contextmanager
def _locked():
    with closed_file(FILE.with_suffix(".lock"), "w") as lock:  # (his alone from the start: core/state.py)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            known = json.loads(FILE.read_text()) if FILE.exists() else {}
        except ValueError:
            known = {}
        yield known
        tmp = FILE.with_suffix(".tmp")
        with closed_file(tmp, "w") as out:
            out.write(json.dumps(known, indent=1))
        tmp.replace(FILE)


def route(harness_or_name: str) -> str:
    """The account a route is: "plan:claude" for a Worker's harness on this Mac's own sign-in, "account:<id>" for an
    account connected in xPerfect ("claude-code@<id>"), "signin:grok_mind" for a sign-in Light made itself (OWN), or
    "key:OPENAI_API_KEY" for a key's name."""
    if harness_or_name in OWN:
        return f"signin:{harness_or_name}"
    harness, _, account = harness_or_name.partition("@")
    if account and harness in PLANS:
        return f"account:{account}"
    if harness_or_name in PLANS:
        return f"plan:{PLANS[harness_or_name]}"
    return harness_or_name if ":" in harness_or_name else f"key:{harness_or_name}"


def kind(failure_class: str) -> str:
    return ("limited" if failure_class in LIMITED else "sign_in" if failure_class in SIGN_IN
            else "refused" if failure_class in REFUSED else "down")


def failure_of(status: int, subscription: bool = False) -> str:
    """A provider's own HTTP status, as a failure class (never its wording): 401 a log-in or key needed, 403 refused for
    this key or account, 429 its limit; for a subscription Light signs in to itself (OWN) 402 too, its plan's limit
    (reported on xAI's subscription route); anything else is not answering (a key allowed only the voice
    endpoint was shown as "not answering" while every chat turn was refused)."""
    known = {401: "provider_unauthorized", 403: "provider_forbidden", 429: "provider_rate_limited",
             **({402: "provider_quota_exhausted"} if subscription else {})}
    return known.get(status, "")


# Her mind as the last start found it (vx mind_answers keeps its verdict in logs/mind-answer: what happened on its first
# line, the profile it is of on its second), and when her mind last gave a word on any channel (kept here by
# brain/queen.py bounded, as each step of hers ends). Her page reads both by the same rule (call/ui app/api/token/mind.ts).
ANSWERED = STATE_ROOT / "core" / "mind-answered"
FIRST_FAILURE = ANSWERED.with_name("mind-first-failure")
NEEDS_CHANGE = ("sign_in", "refused")  # (kind(): a key or a sign-in needed, or refused for this key or account)


def mind_answered(answered_by: tuple[str, str] | None = None) -> None:
    """Her mind gave a word, now: the start's verdict older than this no longer stands (mind_down)."""
    try:
        closed_file(ANSWERED, "a").close()
        os.utime(ANSWERED)
        if answered_by is not None:
            provider, model = answered_by
            with _locked() as known:
                known["mind_last"] = {"profile": os.environ.get("PROFILE", ""), "provider": provider, "model": model}
    except OSError:
        pass  # (how she was last found is never her answer's concern)


def mind_first_failure(error: Exception) -> None:
    """Persist the safe reason for a definitive failure of an attended plan request."""
    from core.chatgpt_sign_in import STOP_WORDS

    state = getattr(error, "plan_state", "")
    if state not in ("refused", "unauthorized", "stale_session", "session_expired", "grant_changed",
                     "consent_changed", "account_changed", "signed_out", "scope_missing", "off",
                     "revoking", "revoked", "revocation_unconfirmed", "model_unavailable"):
        return
    try:
        with closed_file(FIRST_FAILURE) as out:
            out.write(STOP_WORDS[state] + "\n")
    except OSError:
        pass


def last_mind(profile: str) -> dict:
    last = states().get("mind_last") or {}
    return last if last.get("profile") == profile else {}


def mind_down() -> bool:
    """Whether the start's verdict, as it stands, says her mind cannot answer until something is changed: this Mac could
    not run its model ("load"), or her provider refused it or needs a key or a sign-in (its own status, as failure_of
    classes it). A server error, a limit, no connection, no word or no answer in time may pass by itself: never (before, a
    startup 503 left "choose another mind" after the provider came back). And only while it is of the
    profile running now (logs/profile: no marker, no profile in it, another profile's: it does not count), no older than
    her agent's start (logs/agent.pid, written as it starts) and newer than her last answer on any channel. Its
    structure only, never its words."""
    from speech import live
    logs = live.home() / "logs"
    try:
        said = (logs / "mind-answer").read_text().splitlines()
        written = (logs / "mind-answer").stat().st_mtime
        profile = (logs / "profile").read_text().strip()
    except OSError:
        return False
    what = said[0].split() if said else []
    if not what or not profile or len(said) < 2 or said[1].strip() != profile:
        return False
    if not (what[0] == "load" or what[0] == "refused" and len(what) > 1 and what[1].isdigit()
            and kind(failure_of(int(what[1]))) in NEEDS_CHANGE):
        return False
    for later in (logs / "agent.pid", ANSWERED):
        try:
            since = later.stat().st_mtime
        except OSError:
            continue
        if since > written if later.name == "agent.pid" else since >= written:
            return False
    return True


def down(name: str, failure_class: str = "", seen: float | None = None) -> None:
    """This account was found not answering (a Worker's route down, the mind set aside), as of now. seen (a sign-in Light
    makes itself, OWN, whose finding is kept behind the answer): when it was found; a finding older than its last answer
    is dropped, never written over it."""
    with _locked() as known:
        last = known.get(route(name), {})
        if seen is not None and float(last.get("answered") or 0) >= seen:
            return
        at = round(time.time(), 1) if seen is None else round(seen, 1)
        known[route(name)] = {"state": kind(failure_class), "since": last.get("since") or at, "seen": at}


def up(name: str, seen: float | None = None) -> None:
    """This account answered again (a job done on it, the mind taken back). seen (OWN, kept behind the answer): when it
    answered, kept so a failure found earlier but written later never lands over it."""
    with _locked() as known:
        if seen is None:
            known.pop(route(name), None)
        elif float(known.get(route(name), {}).get("seen") or 0) <= seen:
            known[route(name)] = {"answered": round(seen, 3)}


# How long a route last found needing a log-in, or at its limit, rests before a job tries it among the first again (it is
# still tried, after every other route: Workers.routes). Before, each job lost seconds on an account found needing a
# log-in days earlier. A log-in again (settings: an account's sign-in) or an answer clears it.
RESTS = {"sign_in": 24 * 3600.0, "limited": 30 * 60.0}


def resting(name: str, now: float | None = None) -> bool:
    """Whether this route was last found needing a log-in (within a day) or at its limit (within 30 minutes): typed, as
    down() kept it, never a provider's words."""
    last = states().get(route(name)) or {}
    rest = RESTS.get(str(last.get("state") or ""))
    if rest is None:
        return False
    return (time.time() if now is None else now) - float(last.get("seen") or 0) < rest


def states() -> dict:
    """Each account not answering, as {"plan:claude": {"state": "limited", "since": t, "seen": t}}; the rest answer."""
    try:
        return json.loads(FILE.read_text()) if FILE.exists() else {}
    except (OSError, ValueError):
        return {}
