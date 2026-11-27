"""Feelings: Viventium's own persistent, reactive inner state (main Viventium's Feelings, Light-native).

Before each turn `capsule()` gives the turn's note: main's fact guard, then the words-only feeling
capsule, to place just before the user's words. It also remembers those words. After her reply,
`completed()` hands them to the Reaction Cortex: a detached process (a call's shutdown can't cut it)
that asks one appraiser model how the moment moves her and commits typed changes for later turns.
The reply never waits. Only the user's words are appraised: never her reply, and nothing happens for
a greeting, a Worker result or a scheduled wake-up (they have no user words). Feelings fail open: an
error means no capsule, never a broken turn. Pure logic and the band definitions: feelings_kernel.py.

One state for the user on every channel and process: state/feelings/feelings.json (untracked), read
whole (atomic writes) and changed under a file lock. Settings (profiles/*.env):
  FEELINGS                 Nature: grounded | candid | warm | curious; off turns everything off
  FEELINGS_URL, _MODEL     the appraiser: an OpenAI-compatible endpoint (a bare host gets /v1), its model
  FEELINGS_API_KEY         when that endpoint needs a key
  FEELINGS_EFFORT          reasoning effort sent to it (default none: no thinking; empty: not sent)
  FEELINGS_FALLBACK_MODEL  (+ FEELINGS_FALLBACK_URL, FEELINGS_FALLBACK_API_KEY) used when the first fails
  FEELINGS_TIMEOUT         seconds per appraisal attempt (default 30)
  FEELINGS_REACTION        always (default) | classified (a classifier decides first) | disabled (hold)
"""
import asyncio
import datetime as dt
import fcntl
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from brain import feelings_kernel as kernel
from core.state import STATE_ROOT, closed_file, logs

ROOT = Path(__file__).resolve().parents[1]
STATE = STATE_ROOT / "feelings"      # feelings.json; pending.json holds waiting words until appraised


def _log_file() -> Path:
    """The reactor's log (one line per reaction, never words), with the logs of the state in use: the run's own when
    it names them (the bench's, VX_LOGS), this checkout's for her own state, else inside a test's own state; never his
    logs/feelings.log for a state that is not his (a bench's reactor once wrote its lines into his)."""
    return logs() / "feelings.log"  # (core/state.py: the one place that says whose logs a run's lines go to)


LOG = _log_file()
MAX_PENDING = 4                       # reactions waiting while one runs: the latest wait, older ones give way
MAX_AGE = 30 * 60                     # s: words older than this are no longer appraised
READ_TIMEOUT = 2                      # s: a turn gets no capsule rather than wait longer
RETRYABLE = {"timeout", "provider_rate_limited", "empty_output"}
# How an appraisal on this Mac's own model gave way (to his turn, his speech going on, or work of his there): never
# retried at once, and tried once more when her reply ends (_react), so a reaction is never simply lost.
GAVE_WAY = {"foreground_turn", "she_kept_talking", "your_work"}
RETRY_WAIT = 300.0  # s: how long a reaction that gave way waits for her reply to end before it is asked once more
ACTIVATION_THRESHOLD = 0.55           # classified mode: main's default confidence
log = logging.getLogger("feelings")

_pending: dict[str, list[dict]] = {}  # session -> the user's words awaiting her reply (this process)


class ReactionError(Exception):
    def __init__(self, code: str, detail: str | None = None, route: dict | None = None) -> None:
        super().__init__(code)
        self.code, self.detail, self.route = code, detail, route or {}


def nature() -> str:
    return os.environ.get("FEELINGS", "off")  # off | grounded | candid | warm | curious


def init() -> None:
    """Once per process start: Feelings on, with the chosen Nature and reaction mode."""
    if nature() == "off":
        return
    try:
        with _locked():
            state = _read(writing=True)
            if _settle(state) or not (STATE / "feelings.json").exists():  # first start, or a setting changed
                _save(state)
    except Exception as e:
        log.warning("feelings init failed: %s", type(e).__name__)


async def capsule(session: str, turn: int, text: str, reaction_id: str | None = None, *, peek: bool = False) -> str:
    """This turn's note ("" when off or on any error), and the user's words kept for completed().
    `reaction_id` names this moment uniquely (default: a new uuid). `turn` is the caller's counter only:
    it restarts with the process, so it never identifies a reaction. peek: the note as it reads now, with nothing
    marked or kept (a draft of her reply made before his turn has ended: Queen._draft)."""
    if nature() == "off":
        return ""
    try:
        if (text or "").strip() and not peek:  # (his words: a turn of theirs has begun)
            _mark_turn(session, turn)
        snapshot = await asyncio.wait_for(asyncio.to_thread(_snapshot), READ_TIMEOUT)
        if snapshot["enabled"] and (text or "").strip() and not peek:
            waiting = _pending.setdefault(session, [])
            waiting.append(_stimulus(text, reaction_id, snapshot["controlEpoch"]))
            del waiting[:-MAX_PENDING]
        note = kernel.manner(snapshot.get("mannerId")) if snapshot["enabled"] else ""
        return "\n\n".join(filter(None, (kernel.prompt("user_fact_guard"), snapshot["capsule"], note, _own_words(snapshot))))
    except Exception as e:
        log.warning("feelings capsule skipped: %s", type(e).__name__)
        return ""


def _turn_file(session: str) -> Path:
    import hashlib
    return STATE / "turns" / (hashlib.sha256(f"{os.getpid()}:{session}".encode()).hexdigest() + ".json")


TRANSCRIPT_WAIT = 2.0  # s: speech of his that ends with no words yet holds her this long for them, then lets go


def _speech_file(session: str) -> Path:
    """His speech's own marker, beside the turn's (one per session of this process): a cough, or an echo of her own
    voice, while a turn of his is being answered never touches that turn's marker."""
    import hashlib
    return STATE / "turns" / (hashlib.sha256(f"{os.getpid()}:{session}:speech".encode()).hexdigest() + ".json")


def _mark_speech(session: str = "", hold: float | None = None) -> None:
    """His voice, heard: she is held while he speaks, and while his words are judged (Wing mode's check); `hold`, once he
    stopped: only this many seconds more, for its words (speech that never becomes a turn lets go by itself)."""
    from core.state import private_file
    try:
        path = _speech_file(session)
        tmp = path.with_suffix(".tmp")
        with private_file(tmp, "w") as f:
            json.dump({"pid": os.getpid(), "speech": True, **({"until": time.time() + hold} if hold is not None else {})}, f)
        os.replace(tmp, path)
    except OSError:
        log.warning("could not mark his speech")


def _end_speech(session: str = "") -> None:
    """His words were heard and were not a turn of hers (Listen, or Wing and not to her): his speech lets go; a turn of
    hers being answered stays held by its own marker."""
    _speech_file(session).unlink(missing_ok=True)


def _mark_turn(session: str = "", turn: int = 0) -> None:
    """Keep an active turn until its reply ends; other processes see it too. (His speech before a turn has its own
    marker: _mark_speech.)"""
    from core.state import private_file
    try:
        path = _turn_file(session)
        with private_file(path.parent / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                previous = json.loads(path.read_text())
                if previous.get("pid") == os.getpid() and previous.get("turn", -1) > turn:
                    return
            except (OSError, ValueError):
                pass
            tmp = path.with_suffix(".tmp")
            with private_file(tmp, "w") as f:
                json.dump({"pid": os.getpid(), "turn": turn}, f)
            os.replace(tmp, path)
    except OSError:
        log.warning("could not mark foreground turn")


def _end_turn(session: str = "", turn: int | None = None) -> None:
    """An old reply cannot release a newer turn; a closed session releases any of its turns, and his speech."""
    path = _turn_file(session)
    if not path.parent.exists():
        return
    if turn is None:
        _end_speech(session)
    from core.state import private_file
    try:
        with private_file(path.parent / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if turn is None or json.loads(path.read_text())["turn"] == turn:
                path.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError):
        pass


def her_turn() -> bool:
    """Any unfinished foreground turn, including a long one; dead processes do not hold admission."""
    for path in (STATE / "turns").glob("*.json"):
        try:
            marked = json.loads(path.read_text())
            pid = int(marked["pid"])
            os.kill(pid, 0)
            if "until" in marked and float(marked["until"]) < time.time():  # (his speech that never became a turn)
                continue
            return True
        except ProcessLookupError:
            path.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            return True  # a turn marker being written is still busy
    return False


def _own_words(snapshot: dict) -> str:
    """The owner's own words for the level each feeling is at now, said once more as the note's last lines, after the
    line in brain/prompts/feelings/own_words.md. They are inside the capsule too (main's place for them), and there the
    local mind did not follow them: with Play resting high and an addition asking for a joke in every reply,
    qwen3.6 joked in 3 of 40 replies, where main Viventium jokes in 31 of 40 (tests/own_words_eval.py). What
    is last in her notes is what she follows."""
    if not snapshot["enabled"]:
        return ""
    bands, bounds = snapshot["bands"], snapshot["levelBounds"]
    own = [text for band, levels in kernel.normalize_additions(snapshot["rangePromptOverrides"]).items() for level_id, text in levels.items()
           if bands[band]["enabled"] and kernel.LEVEL_IDS[kernel.level(bands[band]["current"], bounds.get(band))] == level_id]
    return "\n".join((kernel.prompt("own_words"), *own)) if own else ""


def completed(session: str, turn: int, reply: str, reaction_id: str | None = None, words: str | None = None,
              route: dict | None = None, *, end_turn: bool = True) -> None:
    """Her reply is out: appraise the user's words that led to it, detached (fire-and-forget).
    By default the words this session's capsule() kept; `reaction_id` picks one of them; `words` gives
    them directly. The reply itself is never appraised. route: where the appraisal runs, as the Subconscious
    page's Emotional reaction card sets it (brain/rounds.Place.word(): "helpers", "mac" or "worker"); None is
    this profile's own appraiser (FEELINGS_URL)."""
    if end_turn:
        _end_turn(session, turn)
    if nature() == "off" or not (reply or "").strip():
        return
    waiting = [s for s in _pending.pop(session, []) if time.time() - s["at"] < MAX_AGE]
    if words is not None:
        jobs, keep = ([_stimulus(words, reaction_id, None)] if words.strip() else []), waiting
    else:
        jobs = [s for s in waiting if reaction_id in (None, s["id"])]
        keep = [s for s in waiting if s not in jobs]
    if route:
        jobs = [job | {"route": route} for job in jobs]
    if keep:
        _pending[session] = keep
    try:
        if jobs:
            threading.Thread(target=_dispatch, args=(jobs,), name="feelings").start()
    except Exception as e:  # e.g. the process is shutting down
        log.warning("feelings reaction not started: %s", type(e).__name__)


def state() -> dict:
    """Her feelings now, for a dashboard or a Soul Face: per band Current (decayed), Nature and its word;
    the Inner state line, the typed trail, reaction health and the capsule. Off: {"enabled": False}."""
    if nature() == "off":
        return {"enabled": False}
    try:
        snapshot = _snapshot()
    except Exception:
        return {"enabled": False}
    bands, bounds = snapshot["bands"], snapshot["levelBounds"]
    return {"enabled": snapshot["enabled"], "nature": snapshot["profileId"], "manner": snapshot.get("mannerId"), "version": snapshot["version"],
            "asOf": snapshot["asOf"], "reactionMode": snapshot["reactionActivationMode"],
            "bands": {band.id: {"name": band.name, "low": band.low, "high": band.high, "color": band.color,
                                "current": round(bands[band.id]["current"], 2), "nature": bands[band.id]["baseline"],
                                "halfLifeMinutes": bands[band.id]["halfLifeMinutes"], "enabled": bands[band.id]["enabled"],
                                "word": band.words[kernel.level(bands[band.id]["current"], bounds.get(band.id))]} for band in kernel.BANDS},
            # (where each band's levels begin, every band, and what his levels say in place of main's: the settings page's
            # Advanced part, which reads both and edits them through control("bounds") and control("says"))
            "levelBounds": {band.id: list(kernel.bounds_of(bounds.get(band.id))) for band in kernel.BANDS},
            "levelWords": snapshot["levelWords"],
            "innerState": snapshot["innerState"], "trail": snapshot["trail"], "additions": snapshot["rangePromptOverrides"],
            "reactionHealth": snapshot["reactionHealth"], "capsule": snapshot["capsule"],
            "capsuleLimited": snapshot["capsuleLimited"]}


def control(action: str, choice: str = "", band: str = "", value: float = 0) -> str:
    """The user's own controls, through her (a tool) or the settings page: show, pause, resume, reset (back to
    Nature), erase (also the history), a new Nature, one band's Current ("set") or resting value ("rest"), one
    band "on" / "off", how fast one band comes back ("pace": its half-life in minutes), the owner's own words
    added to one band's level ("words": `value` is the level 0-4, `choice` the text, "" takes them away), what one
    band's level says in her capsule in place of main's words ("says": `value` the level 0-4, `choice` the text, at
    most 1,200 characters; "" puts main's words back), or where one band's five levels begin ("bounds": `choice` four
    rising whole numbers, "25,45,65,85", each level at least five points wide; "" brings back 20,40,60,80).
    A choice outlives restarts; each change drops a reaction in flight (cancel-on-edit)."""
    if nature() == "off":
        return "Feelings are off on this Mac (FEELINGS=off in the profile)."
    if action == "show":
        now = state()
        lines = [f"Nature: {now['nature']}" + ("" if now["enabled"] else " (paused)")]
        lines += [f"{b['name']}: {b['word']} ({b['current']:.0f}; rests at {b['nature']:.0f})" for b in now["bands"].values()]
        if now.get("innerState"):
            lines.append("Inner state: " + now["innerState"]["text"])
        lines += [f"Lately: {e['band']} {e['direction']} {e['strength']} ({e.get('cause') or e.get('sourceType')})"
                  for e in now["trail"][-8:]]
        health = now["reactionHealth"]
        lines.append(f"Reactions: {health.get('status')}" + (f", last error {health['lastErrorClass']}"
                                                             if health.get("lastErrorClass") else ""))
        return "\n".join(lines)
    bands = {b.id for b in kernel.BANDS}
    cuts = _cuts(choice) if action == "bounds" else None
    if action not in ("pause", "resume", "reset", "erase", "nature", "set", "rest", "on", "off", "pace", "words", "says",
                      "bounds") \
            or (action == "nature" and choice not in kernel.PROFILES) \
            or (action in ("set", "rest", "on", "off", "pace", "words", "says", "bounds") and band not in bands) \
            or (action in ("set", "rest") and not 0 <= value <= 100) \
            or (action == "pace" and not kernel.MIN_HALF_LIFE <= value <= kernel.MAX_HALF_LIFE) \
            or (action in ("words", "says") and (value not in range(len(kernel.LEVEL_IDS)) or len(choice) > kernel.MAX_ADDITION)):
        raise ValueError(f"Use show, pause, resume, reset, erase, nature ({', '.join(kernel.PROFILES)}), "
                         f"set/rest with a band ({', '.join(sorted(bands))}) and a value 0-100, or on/off with a band.")
    if action == "bounds" and cuts is None:
        raise ValueError(f"Thresholds are four rising whole numbers, each level at least {kernel.MIN_LEVEL_WIDTH} points "
                         "wide, like 20,40,60,80 (or nothing, for those).")
    with _changing() as current:
        now, chosen = _now(), current.setdefault("userSet", {})
        if action == "pause":
            current["enabled"], chosen["paused"] = False, True
        elif action == "resume":
            current["enabled"] = True
            chosen.pop("paused", None)
        elif action in ("on", "off"):  # one band in or out of what shapes her (it keeps resting meanwhile)
            bands_now = kernel.materialize(current["bands"], now)
            bands_now[band]["enabled"] = action == "on"
            current["bands"] = bands_now
        elif action == "pace":  # how fast this one comes back to where it rests
            bands_now = kernel.materialize(current["bands"], now)
            bands_now[band]["halfLifeMinutes"] = float(value)
            current["bands"] = bands_now
        elif action in ("words", "says"):  # his words added to a level, or what the level says in place of main's
            key = "rangePromptOverrides" if action == "words" else "levelWords"
            kept = {name: dict(levels) for name, levels in current.get(key, {}).items()}
            kept.setdefault(band, {})[kernel.LEVEL_IDS[int(value)]] = choice
            current[key] = kernel.normalize_additions(kept)  # (empty text drops the entry: main's words again)
        elif action == "bounds":  # where this band's five levels begin (its Current and its rest stay where they are)
            current["levelBounds"] = kernel.normalize_bounds({**current.get("levelBounds", {}), band: list(cuts)})
        elif action in ("set", "rest"):  # one band only: where it is now, or where it rests (its Nature)
            bands_now = kernel.materialize(current["bands"], now)
            key = "current" if action == "set" else "baseline"
            before = bands_now[band][key]
            bands_now[band].update({key: float(value), "updatedAt": kernel.iso(now)})
            if action == "rest":  # (a resting point you set applies now, as a personality's do: kernel.apply_nature)
                bands_now[band]["current"] = float(value)
            current["bands"] = bands_now
            if before != value:
                current["trail"] = (current["trail"] + [{
                    "timestamp": kernel.iso(now), "band": band, "direction": "up" if value > before else "down",
                    "strength": kernel.strength_for(abs(value - before)), "sourceType": "manual",
                    "cause": "manual_adjustment", "before": before, "after": float(value)}])[-kernel.MAX_TRAIL:]
            if action == "rest":
                current["profileId"], chosen["nature"] = "custom", "custom"
        else:
            values = kernel.PROFILES[choice] if action == "nature" else {
                band: current["bands"][band]["baseline"] for band in current["bands"]}
            current["bands"], trail = kernel.apply_nature(kernel.materialize(current["bands"], now), values, now)
            current["trail"] = (current["trail"] + trail)[-kernel.MAX_TRAIL:]
            current["innerState"] = None
            if action == "erase":
                current["trail"], current["processedStimulusKeys"] = [], []
            if action == "nature":
                current["profileId"], chosen["nature"], current["mannerId"] = choice, choice, choice
        current["version"] += 1
        current["controlEpoch"] += 1
    return {"pause": "Paused: no feeling now shapes you, and nothing moves them.", "resume": "Resumed.",
            "reset": "Back to your Nature, calm and rested.", "erase": "Erased: back to your Nature, no history.",
            "nature": f"Your Nature is now {choice}.", "set": f"{band} is now {value:.0f}.",
            "rest": f"{band} now rests at {value:.0f}.", "on": f"{band} is on.", "off": f"{band} is off.",
            "pace": f"{band} now comes halfway back in {value:.0f} minutes.", "words": f"Kept for {band}.",
            "says": f"{band}: " + (f"level {int(value)} now says your words." if choice.strip() else f"level {int(value)} says main's words again."),
            "bounds": f"{band}: its levels now begin at " + ", ".join(str(c) for c in (cuts or ())) + "."}[action]


def _cuts(choice: str):
    """Four bounds from "25,45,65,85" ("" is the default), or None when they are not four rising whole numbers that
    leave each level its room (feelings_kernel.bounds_of)."""
    if not str(choice).strip():
        return kernel.DEFAULT_BOUNDS
    try:
        numbers = [float(part) for part in str(choice).replace(" ", "").split(",")]
    except ValueError:
        return None
    return tuple(int(n) for n in numbers) if kernel.valid_bounds(numbers) else None


def voice_expression() -> str:
    """How her feelings shape her voice, with the active voice's documented controls (TTS, TTS_MODEL):
    Chatterbox's [laugh] [sigh] [gasp], xAI's speech tags. "" when Feelings are off or the voice has none."""
    if nature() == "off":
        return ""
    try:
        controls = _voice_controls()
        rules = "voice_expression_main" if _online_mind() else "voice_expression"
        return (kernel.prompt(rules).replace("{{controls}}", controls) + voice_usage()) if controls else ""
    except Exception as e:
        log.warning("feelings voice rules skipped: %s", type(e).__name__)
        return ""


# -- State: one JSON document under a file lock --

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@contextmanager
def _locked():
    """One writer at a time, across processes (a call and Telegram are separate processes)."""
    with closed_file(STATE / "feelings.lock", "a") as lock:  # (his alone from the start, its folders too)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


@contextmanager
def _changing():
    """Read, change and save the state under the lock (nothing is saved if the change fails)."""
    with _locked():
        state = _read(writing=True)
        yield state
        _save(state)


def _read(writing: bool = False) -> dict:
    """The stored state, else a fresh one from Nature. A corrupt file is never fatal: a writer sets it aside."""
    path, now = STATE / "feelings.json", _now()
    try:
        return kernel.normalize_state(json.loads(path.read_text(encoding="utf-8")), nature(), now)
    except FileNotFoundError:
        return kernel.new_state(nature(), now)
    except ValueError:
        if writing:
            path.rename(path.with_name(f"feelings.corrupt.{int(time.time())}.json"))
        return kernel.new_state(nature(), now)


def _write(path: Path, value) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(value, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save(state: dict) -> None:
    state["updatedAt"] = kernel.iso(_now())
    _write(STATE / "feelings.json", state)


def _settle(state: dict) -> bool:
    """This process's settings into the state. Each change is a control change: version and controlEpoch
    move, so a reaction already in flight is cancelled instead of landing across it (cancel-on-edit).
    A Nature tuned by hand ("custom") is kept."""
    now, changed, chosen = _now(), False, state.get("userSet", {})  # the user's own choices win over settings
    if nature() in kernel.PROFILES and state["profileId"] not in (nature(), "custom") and "nature" not in chosen:
        state["bands"], trail = kernel.apply_nature(kernel.materialize(state["bands"], now), kernel.PROFILES[nature()], now)
        state["trail"] = (state["trail"] + trail)[-kernel.MAX_TRAIL:]
        state["profileId"], state["mannerId"], state["innerState"], changed = nature(), nature(), None, True
    mode = os.environ.get("FEELINGS_REACTION")
    if mode in kernel.ACTIVATION_MODES and state["reactionActivationMode"] != mode:
        state["reactionActivationMode"], changed = mode, True
    if not state["enabled"] and not chosen.get("paused"):
        state["enabled"], state["innerState"], changed = True, None, True
    if changed:
        state["version"] += 1
        state["controlEpoch"] += 1
    return changed


def _snapshot() -> dict:
    """The state as of now (Current decayed) and its capsule: what one turn sees."""
    state, now = _read(), _now()
    bands = kernel.materialize(state["bands"], now)
    text, limited = kernel.render_capsule(state["enabled"], bands, state["rangePromptOverrides"], state["levelWords"],
                                          state["levelBounds"])
    return state | {"bands": bands, "capsule": text, "capsuleLimited": limited, "asOf": kernel.iso(now)}


def _stimulus(words: str, reaction_id: str | None, epoch: int | None) -> dict:
    return {"id": reaction_id or uuid.uuid4().hex, "words": kernel.bounded_stimulus(words.strip()),
            "epoch": epoch, "at": time.time()}


def _read_pending() -> list:
    try:
        return json.loads((STATE / "pending.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


# -- Reactions: queued, then one detached reactor at a time for the user --

def _dispatch(jobs: list[dict]) -> None:
    """Queue the words (until appraised) and make sure a reactor runs."""
    try:
        with _locked():
            epoch = _read()["controlEpoch"]
            queue = (_read_pending() + [job | {"epoch": epoch if job["epoch"] is None else job["epoch"]}
                                        for job in jobs])[-MAX_PENDING:]
            _write(STATE / "pending.json", queue)
        _start_reactor()
    except Exception as e:
        log.warning("feelings reaction not queued: %s", type(e).__name__)


# What an appraisal may run on besides FEELINGS_*: her quick helpers (core/helpers.py: their settings and the keys they
# use), this Mac's model, and a run on a Worker harness (xPerfect), as the Emotional reaction card chooses.
REACTOR_KEYS = ("PATH", "HOME", "USER", "LANG", "TMPDIR", "VX_STATE", "MEMORY_URL", "MEMORY_MODEL", "QUEEN", "QUEEN_URL",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "WORKERS", "WORKER_PROFILE", "WORKER_FALLBACK", "WORKERS_LOCAL",
                "MANAGER_PROFILE")
REACTOR_PREFIXES = ("FEELINGS", "HELPERS", "XPERFECT_")


def _reactor_env() -> dict:
    """What the reactor process is given: the appraiser's settings and what its places need, nothing else."""
    return {key: value for key, value in os.environ.items() if key in REACTOR_KEYS or key.startswith(REACTOR_PREFIXES)}


def _start_reactor() -> None:
    """A detached reactor process with only the appraiser's settings in its environment."""
    env = _reactor_env()
    with closed_file(LOG, "a") as out:  # (his alone from the start: core/state.py)
        subprocess.Popen([sys.executable, "-m", "brain.feelings", "react", str(STATE)], cwd=ROOT, env=env,
                         stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)


def _reactor(appraise=None) -> None:
    """Appraise waiting words one at a time, oldest first. At most one reactor runs for the user: a second
    one leaves the queue to it, and the first looks again after letting go, so nothing is stranded."""
    with closed_file(STATE / "reactor.lock", "a") as runner:
        while _read_pending():
            try:
                fcntl.flock(runner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            try:
                while job := _take():
                    _react(job, appraise or _appraise)
            finally:
                fcntl.flock(runner, fcntl.LOCK_UN)


def _requeue(job: dict) -> None:
    """A reaction that gave way to his turn, back in line: the reactor takes it next, and it waits for her to be free
    (her reply ended) before it is asked."""
    with _locked():
        _write(STATE / "pending.json", (_read_pending() + [job])[-MAX_PENDING:])


def _take() -> dict | None:
    with _locked():
        queue = [job for job in _read_pending() if time.time() - job.get("at", 0) < MAX_AGE]
        job = queue.pop(0) if queue else None
        _write(STATE / "pending.json", queue)
    return job


def _react(job: dict, appraise) -> dict:
    """One reaction: appraise the user's words against the latest state, then commit its typed changes. One that gave
    way to his turn before is asked again only once her reply has ended (at most RETRY_WAIT from now)."""
    if job.get("retried"):
        until = time.monotonic() + RETRY_WAIT
        while her_turn() and time.monotonic() < until:
            time.sleep(0.2)
    started, key = time.monotonic(), kernel.stimulus_key(job["id"])
    snapshot = _snapshot()
    skip = ("disabled" if not snapshot["enabled"] else
            "already_processed" if key in snapshot["processedStimulusKeys"] else
            "cancelled_by_control" if snapshot["controlEpoch"] != job["epoch"] else
            "activation_disabled" if snapshot["reactionActivationMode"] == "disabled" else None)
    if skip:
        return _outcome(started, "skipped", reason=skip, health=skip not in ("disabled", "already_processed"))
    _health(status="running", lastStartedAt=kernel.iso(_now()))
    global _place
    _place = job.get("route")  # (one job at a time in the reactor: where this one runs, for _call)
    try:
        if snapshot["reactionActivationMode"] == "classified" and not _activated(snapshot, job["words"]):
            return _outcome(started, "skipped", reason="not_activated")
        changes, inner, route = appraise(snapshot, job["words"])
    except ReactionError as e:
        if e.detail in GAVE_WAY and not job.get("retried"):  # (it gave way to his turn on this Mac's model:
            _requeue(job | {"retried": True})                           # once more, when her reply ends, never lost)
            return _outcome(started, "skipped", reason="gave_way", route=e.route)
        return _outcome(started, "degraded", error=e.code, detail=e.detail, route=e.route)
    except Exception as e:
        return _outcome(started, "degraded", error="reaction_failed", detail=type(e).__name__)
    finally:
        _place = None
    return _commit(job, key, snapshot, changes, inner, route, started)


def _commit(job: dict, key: str, snapshot: dict, changes: list, inner: str, route: dict, started: float) -> dict:
    """Rebase the typed changes onto the latest state and commit it in one compare-and-set under the lock:
    never twice for one stimulus, never across a control change made meanwhile."""
    trail = []
    with _changing() as state:
        now = _now()
        skip = ("already_processed" if key in state["processedStimulusKeys"] else
                "disabled_while_running" if not state["enabled"] else
                "cancelled_by_control" if state["controlEpoch"] != job["epoch"] else None)
        if not skip:
            bands, trail = kernel.apply_changes(kernel.materialize(state["bands"], now), changes, now)
            for entry in trail:
                state["bands"][entry["band"]] = bands[entry["band"]]
            state["trail"] = (state["trail"] + trail)[-kernel.MAX_TRAIL:]
            if state["version"] == snapshot["version"]:  # else the line would describe a state that moved on
                state["innerState"] = {"text": inner, "generatedAt": kernel.iso(now)}
            state["processedStimulusKeys"] = (state["processedStimulusKeys"] + [key])[-kernel.MAX_PROCESSED_KEYS:]
            state["version"] += 1
            state["reactionHealth"] |= _health_fields(started, "healthy", route=route)
    if skip:
        return _outcome(started, "skipped", reason=skip, health=skip != "already_processed")
    return _outcome(started, "healthy", route=route, health=False,
                    moved=[f"{e['band']}{'+' if e['direction'] == 'up' else '-'}{kernel.STRENGTHS[e['strength']]}"
                           for e in trail])


def _health_fields(started: float, status: str, reason=None, error=None, detail=None, route=None) -> dict:
    if os.environ.get("FEELINGS_URL") == "helpers":  # (her quick helpers: the first one asked)
        from core import helpers
        first = (helpers.routes() or [("helpers", "")])[0]
        url, model = first[0], first[1]
    else:
        (url, model, _), _ = _routes()
    route = route or {}
    return {"status": status, "lastCompletedAt": kernel.iso(_now()),
            "lastDurationMs": round((time.monotonic() - started) * 1000), "lastSkipReason": reason,
            "lastErrorClass": error, "lastErrorDetail": detail, "requestedProvider": url or "openai",
            "requestedModel": model, "lastUsedProvider": route.get("provider"), "lastUsedModel": route.get("model"),
            "lastFallbackUsed": route.get("fallbackUsed"), "lastPrimaryErrorClass": route.get("primaryErrorClass"),
            "lastPassedOver": route.get("passedOver", [])}


def _health(**fields) -> None:
    """Reaction health only: no version change (the capsule does not depend on it)."""
    with _changing() as state:
        state["reactionHealth"] |= fields


def _outcome(started: float, status: str, reason=None, error=None, detail=None, route=None, health=True,
             moved=None) -> dict:
    if health:
        _health(**_health_fields(started, status, reason, error, detail, route))
    line = {"t": round(time.time(), 3), "status": status, "reason": reason, "error": error,
            "ms": round((time.monotonic() - started) * 1000), "model": (route or {}).get("model"),
            "fallback": (route or {}).get("fallbackUsed"), "moved": moved}
    _record({key: value for key, value in line.items() if value is not None})
    return line


def _record(line: dict) -> None:
    print(json.dumps(line), flush=True)  # the reactor's stdout is logs/feelings.log


# -- The appraiser: one JSON-mode call to an OpenAI-compatible endpoint, no tools --

def _base_url(url: str | None) -> str | None:
    """A bare host:port gets the OpenAI-compatible /v1 path; no URL means OpenAI's own endpoint."""
    if not url:
        return None
    url = url.rstrip("/")
    return url + "/v1" if urlsplit(url).path in ("", "/") else url


def _routes() -> tuple[tuple, tuple | None]:
    """(url, model, key) of the appraiser and of its optional fallback model."""
    key = os.environ.get("FEELINGS_API_KEY") or "local"
    primary = (_base_url(os.environ.get("FEELINGS_URL")), os.environ.get("FEELINGS_MODEL", ""), key)
    if not os.environ.get("FEELINGS_FALLBACK_MODEL"):
        return primary, None
    url = os.environ.get("FEELINGS_FALLBACK_URL")
    return primary, (_base_url(url) if url else primary[0], os.environ["FEELINGS_FALLBACK_MODEL"],
                     os.environ.get("FEELINGS_FALLBACK_API_KEY") or key)


_cancel = threading.local()  # (the request a watcher may close: _asked() sets it for the thread that asks)


def _failed(route: tuple, code: str) -> dict:
    """The receipt of a request that gave no answer: no provider was used; it is named as tried, with why."""
    return {"provider": None, "model": None, "answered": False, "fallbackUsed": False, "primaryErrorClass": code,
            "passedOver": [[route[0] or "openai", code]]}


def _complete(route: tuple, messages: list) -> tuple[str, dict]:
    """One chat completion in JSON mode. Failures become closed error classes, never provider text. A watcher may close
    its client while it runs (a turn of his began: _asked), which ends the request at once."""
    import openai
    url, model, key = route
    if not model:
        raise ReactionError("not_configured", route=_failed(route, "not_configured"))
    request = {"model": model, "messages": messages, "response_format": {"type": "json_object"},
               "max_completion_tokens": 512}
    if effort := (_place or {}).get("effort") or os.environ.get("FEELINGS_EFFORT", "none"):  # (the card's, if set)
        request["reasoning_effort"] = effort
    errors = ((openai.APITimeoutError, "timeout"), (openai.RateLimitError, "provider_rate_limited"),
              (openai.APIConnectionError, "provider_unavailable"), (openai.AuthenticationError, "provider_auth"),
              (openai.PermissionDeniedError, "provider_auth"), (openai.NotFoundError, "provider_model_unavailable"),
              (openai.BadRequestError, "request_rejected"))
    cancel = getattr(_cancel, "event", None)
    try:
        with openai.OpenAI(base_url=url, api_key=key, max_retries=0,
                           timeout=float(os.environ.get("FEELINGS_TIMEOUT") or 30)) as client:
            if cancel is not None:
                _cancel.holder["client"] = client  # (the watcher closes it: the request in flight ends with it)
                if cancel.is_set():
                    raise ReactionError("timeout", detail="foreground_turn", route=_failed(route, "foreground_turn"))
            response = client.chat.completions.create(**request)
    except openai.OpenAIError as e:
        if cancel is not None and cancel.is_set():
            raise ReactionError("timeout", detail="foreground_turn", route=_failed(route, "foreground_turn")) from None
        code = next((code for kind, code in errors if isinstance(e, kind)), "provider_error")
        raise ReactionError(code, route=_failed(route, code)) from None
    text = response.choices[0].message.content if response.choices else None
    if not (text or "").strip():
        raise ReactionError("empty_output", route=_failed(route, "empty_output"))
    return text, {"provider": url or "openai", "model": response.model or model, "answered": True, "fallbackUsed": False,
                  "primaryErrorClass": None, "passedOver": []}


def _this_mac(url: str | None) -> bool:
    """A route served by this Mac's own model server (her reply shares it when she runs on this Mac): the one kind of
    appraiser that gives way to a turn of his. An online one shares nothing with her reply here."""
    return (urlsplit(url or "").hostname or "").lower() in ("127.0.0.1", "localhost", "::1")


def _asked(route: tuple, messages: list, deadline: float) -> tuple[str, dict]:
    """One request of the appraiser. On this Mac's own model server: it waits for her turn first and is given up the
    moment a turn of his begins (its client closed, its answer never used), and is tried once more when her reply
    ends (_react). Online: asked at once, and what it started finishes."""
    if not _this_mac(route[0]):
        return _complete(route, messages)
    while her_turn():
        if time.monotonic() >= deadline:
            raise ReactionError("timeout", detail="foreground_turn", route=_failed(route, "foreground_turn"))
        time.sleep(0.1)
    cancel, done, out, holder = threading.Event(), threading.Event(), {}, {}

    def ask() -> None:
        _cancel.event, _cancel.holder = cancel, holder
        try:
            out["answer"] = _complete(route, messages)
        except BaseException as e:  # noqa: BLE001 (handed to the caller as it was)
            out["error"] = e
        finally:
            _cancel.event = _cancel.holder = None
            done.set()
    threading.Thread(target=ask, name="feelings-request", daemon=True).start()
    while not done.wait(0.1):
        if her_turn():  # (a turn of his began: the request is closed and its answer, if any, never used)
            cancel.set()
            if (client := holder.get("client")) is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 (closing is all that is asked of it)
                    pass
            raise ReactionError("timeout", detail="foreground_turn", route=_failed(route, "foreground_turn"))
    if "error" in out:
        raise out["error"]
    return out["answer"]


_place: dict | None = None  # where the job being appraised runs (the Emotional reaction card), None: FEELINGS_URL


def _elsewhere(place: dict, messages: list) -> tuple[str, dict]:
    """The appraisal where the Emotional reaction card puts it (this Mac's model, a run on a Worker harness, her quick
    helpers), asked the way the Subconscious asks every part (brain/rounds.ask), so the same admission holds for it:
    a part waits for her and for work of yours running on this Mac, and stops cleanly when either begins
    (before, the helpers were asked directly, past that admission)."""
    import asyncio
    import inspect
    from brain import rounds
    where = rounds.Place(**{k: place.get(k, "") for k in ("kind", "chose", "effort", "harness", "name")})
    ran: dict = {}
    extra = {"ran": ran} if "ran" in inspect.signature(rounds.ask).parameters else {}  # (rounds says where it really ran)
    # (her turn goes first: a turn of theirs that just began, in whichever process of hers took it, holds this part as
    # the rounds' admission holds any; the reactor is a process of its own and cannot ask her)
    async def admitted():
        wait = float(os.environ.get("FEELINGS_TIMEOUT") or (300 if where.kind == "worker" else 30))
        deadline = time.monotonic() + wait
        # (her online helpers are asked at once and finish: only a part on this Mac's own model, or a Worker's run,
        # waits for her first; one held off past its wait gave way to her, and is tried once more: _react)
        if (where.kind != "helpers" or rounds.gives_way(where)) and not await rounds._held_off(her_turn, deadline):
            return "", "foreground_turn"
        return await rounds.ask(where, messages[0]["content"], "\n\n".join(m["content"] for m in messages[1:]),
                                name="Cortex: Emotional reaction", max_tokens=512,
                                json_out=where.kind in ("mac", "helpers"), wait=max(0, deadline - time.monotonic()),
                                busy=her_turn, **extra)
    asking = admitted()
    try:
        asyncio.get_running_loop()
    except RuntimeError:  # (the reactor: a thread or process of its own, with no loop running)
        text, how = asyncio.run(asking)
    else:  # (asked from inside a running loop: on a thread of its own, so that loop is never blocked by it)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            text, how = pool.submit(asyncio.run, asking).result()
    # What really ran (the helper that answered, and whether one before it in his order failed: a fallback), never
    # only what was chosen (it said fallbackUsed=False after a rate limit)
    tried = [list(step) for step in ran.get("tried") or []]
    answered = how == "ok" and bool((text or "").strip())
    if not answered:  # (nothing answered: no provider was used; every route tried is named, with why, a closed class)
        why = "empty_output" if how == "ok" else how  # (a route that "completed" with no words answered nothing)
        if how == "ok":
            tried.append([ran.get("route") or where.kind, why])
        receipt = {"provider": None, "model": None, "answered": False, "fallbackUsed": False,
                   "primaryErrorClass": tried[0][1] if tried else why, "passedOver": tried}
        raise ReactionError("timeout" if how == "timeout" or how in GAVE_WAY else "empty_output" if how == "ok"
                            else "provider_unavailable", detail=why, route=receipt)
    # (the route that answered, and the ones passed over before it: a fallback only when one before it failed)
    return text, {"provider": ran.get("route") or where.kind, "model": ran.get("model") or ran.get("name") or where.name,
                  "answered": True, "fallbackUsed": bool(tried), "primaryErrorClass": tried[0][1] if tried else None,
                  "passedOver": tried}


HELPERS_PLACE = {"kind": "helpers", "chose": "helpers", "effort": "none", "harness": "", "name": "quick helpers"}


def _call(messages: list) -> tuple[str, dict]:
    """The appraiser; its fallback model when it fails. FEELINGS_URL=helpers: her quick helpers instead (Hybrid and
    Cloud: Claude, then OpenAI, then this Mac; core/helpers.py). A job the Emotional reaction card puts on this Mac's
    model, on a Worker or on the helpers runs there, and the helpers are asked as any part is (_elsewhere)."""
    if _place and _place.get("kind") in ("mac", "worker", "helpers"):
        return _elsewhere(_place, messages)
    if os.environ.get("FEELINGS_URL") == "helpers":
        return _elsewhere(HELPERS_PLACE | {"effort": os.environ.get("FEELINGS_EFFORT", "none") or "none"}, messages)
    deadline = time.monotonic() + float(os.environ.get("FEELINGS_TIMEOUT") or 30)
    primary, fallback = _routes()
    try:
        return _asked(primary, messages, deadline)
    except ReactionError as first:
        if not fallback or first.detail in GAVE_WAY:  # (a turn of his ended it: never the fallback's to answer)
            raise
        try:
            text, receipt = _asked(fallback, messages, deadline)
        except ReactionError as second:  # (neither answered: no provider was used, both are named as tried)
            second.route = _failed(primary, first.code) | {"passedOver": [
                *(first.route or {}).get("passedOver", [[primary[0] or "openai", first.code]]),
                *(second.route or {}).get("passedOver", [[fallback[0] or "openai", second.code]])]}
            raise
        # (the fallback answered: it is the one used, and the primary is named as tried)
        return text, receipt | {"fallbackUsed": True, "primaryErrorClass": first.code,
                                "passedOver": (first.route or {}).get("passedOver", [[primary[0] or "openai", first.code]])}


def _messages(system: str, snapshot: dict, words: str) -> list:
    return [{"role": "system", "content": system},
            {"role": "user", "content": kernel.reaction_input(snapshot["bands"], snapshot["trail"], words)}]


def _appraise(snapshot: dict, words: str) -> tuple[list, str, dict]:
    """Main's Emotional Reaction contract, at most two attempts: a malformed answer is retried once with the
    shape restated; a timeout, rate limit or empty answer once as is (unless the fallback already ran)."""
    contract = kernel.output_contract()
    system = "\n\n".join((kernel.prompt("execution"), contract, kernel.prompt("untrusted_stimulus"),
                          "Viventium's configured reaction preference:\n" + snapshot["reactionInstruction"]))
    messages = _messages(system, snapshot, words)
    for attempt in (1, 2):
        try:
            text, receipt = _call(messages)
        except ReactionError as e:
            tried = len((e.route or {}).get("passedOver") or [])  # (the routes really asked: each is asked once at most)
            if attempt == 1 and e.code in RETRYABLE and e.detail not in GAVE_WAY and tried <= 1:
                time.sleep(0.15)
                continue
            raise
        try:
            changes, inner = kernel.parse_appraisal(text)
            return changes, inner, receipt
        except ValueError as e:
            if attempt == 2:
                raise ReactionError("invalid_output", detail=str(e), route=receipt) from None
            messages = messages[:2] + [{"role": "user", "content": "Retry the same appraisal. The prior response "
                                        "failed the required JSON schema.\n\n" + contract}]


def _activated(snapshot: dict, words: str) -> bool:
    """Classified mode: whether these words could move a feeling at all (main's activation classifier)."""
    system = "## Cortex Activation Criteria:\n" + kernel.prompt("activation") + "\n\n" + kernel.ACTIVATION_FORMAT
    text, _ = _call(_messages(system, snapshot, words))
    try:
        verdict = json.loads(kernel.unfence(text))
        return verdict.get("should_activate") is True and float(verdict.get("confidence", 0)) >= ACTIVATION_THRESHOLD
    except (ValueError, TypeError, AttributeError):
        raise ReactionError("invalid_activation_output") from None


def _voice() -> dict:
    """The active voice's typed capability (main's shared/voice data), {} for a voice it does not list."""
    providers = json.loads((kernel.PROMPTS / "tts_provider_capabilities.json").read_text(encoding="utf-8"))["providers"]
    model = os.environ.get("TTS_MODEL", "mlx-community/chatterbox-turbo-8bit")
    provider = os.environ.get("TTS", "mlx_local")
    provider = "xai" if provider == "xai_plan" else provider
    return providers.get(provider) or (next(
        (p for p in providers.values() if any(m["id"] == model for m in p["runtime_models"])), {})
        if provider == "mlx_local" else {})


def _online_mind() -> bool:
    """Whether her mind is an online model (main's voice rules, verbatim) rather than this Mac's (the rules tuned
    on it: qwen3.6 laughed at 18 % of everyday replies with main's wording)."""
    return os.environ.get("QUEEN", "ollama") != "ollama"


def voice_usage() -> str:
    """How the active voice's controls are written (main's per-provider rules), "" for a voice without any. With an
    online mind and xAI's voice: main's own rule, verbatim, its tags filled in, and no restraint line of Light's."""
    try:
        mode = _voice().get("inline_controls", {}).get("mode")
        if mode == "xai_speech_tags" and _online_mind():
            controls = _voice().get("inline_controls", {})
            tags = json.loads((kernel.PROMPTS / controls["dialect_contract"]).read_text(encoding="utf-8"))["speech_tags"]
            inline, wrapping = _heard(tags["inline"]), _heard_wrapping(tags["wrapping"])
            if not inline and not wrapping:  # (none heard on this voice: natural speech, no rule to follow)
                return ""
            return " " + kernel.prompt("voice_provider_xai_main").replace("{{xai.inline_tags}}", ", ".join(inline) or "none") \
                .replace("{{xai.wrapping_tags}}", ", ".join(f"<{tag}>words</{tag}>" for tag in wrapping) or "none")
        name = {"chatterbox_nonverbal_markers": "voice_provider_chatterbox", "xai_speech_tags": "voice_provider_xai"}.get(mode)
        controls = _voice_controls()
        if not controls:  # (none heard on this voice: natural speech, no rule to follow)
            return ""
        listed = f" Its tags: {controls}." if mode == "xai_speech_tags" else ""  # (Chatterbox's rule names its own)
        # (the judgment line sits before the list of tags: after it, the list is the last thing she reads, and
        # she laughed at 7 of 8 fun facts instead of 3)
        return " " + kernel.prompt(name).replace("{{controls}}", controls) + " " + kernel.prompt("voice_restraint") + listed if name else ""
    except Exception as e:
        log.warning("voice usage rules skipped: %s", type(e).__name__)
        return ""


def _heard(tokens: list[str]) -> list[str]:
    """The voice's offered native controls, intersected with its typed documentation. Eve keeps its measured gate;
    Chatterbox keeps its best-effort markers. No clip qualifies a runtime sound."""
    import re
    measured = {tag.lower() for tag in re.findall(r"\[[^\]\s]+\]", os.environ.get("TTS_TAGS", ""))}
    try:
        from speech import sounds
        qualified = {f"[{tag}]" for tag in sounds.heard()}
        if sounds.voice() in sounds.INLINE:
            measured = qualified
        else:
            measured |= qualified
    except Exception as e:  # (capability unreadable: the profile's measured list alone)
        log.warning("heard tags unread: %s", type(e).__name__)
    return [tag for tag in tokens if tag.lower() in measured]


def _heard_wrapping(names: list[str]) -> list[str]:
    """The documented wrapping controls measured to be heard on this profile's voice (its TTS_TAGS names each one as
    <name>, from ./vx test-sound's delivery checks); none without that evidence."""
    import re
    measured = {name.lower() for name in re.findall(r"<([a-z][a-z-]*)>", os.environ.get("TTS_TAGS", ""))}
    return [name for name in names if name.lower() in measured]


def _voice_controls() -> str:
    """The active voice's documented controls, found by its typed capability (main's shared/voice data),
    narrowed to its allowed native controls."""
    controls = _voice().get("inline_controls", {})
    if controls.get("mode") == "chatterbox_nonverbal_markers":
        return ", ".join(_heard(controls["exact_tokens"]))
    if controls.get("mode") == "xai_speech_tags":
        tags = json.loads((kernel.PROMPTS / controls["dialect_contract"]).read_text(encoding="utf-8"))["speech_tags"]
        inline, wrapping = _heard(tags["inline"]), _heard_wrapping(tags["wrapping"])
        return "; ".join(([", ".join(inline)] if inline else []) + (
            ["or around a few words: " + ", ".join(f"<{tag}>words</{tag}>" for tag in wrapping)] if wrapping else []))
    return ""  # no documented controls: natural, unmarked speech


if __name__ == "__main__" and sys.argv[1:2] == ["react"]:  # the detached reactor (_start_reactor)
    STATE = Path(sys.argv[2])
    _reactor()
