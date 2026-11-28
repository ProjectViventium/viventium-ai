"""Work the user is owed: each Worker job from hand-off until its result is told, across channels.

A hang-up does not stop a Worker. Its job stays here (state/core/jobs.json, untracked) with everything that decides its
telling: his exact words (`asked`), the channel he asked on, an explicit destination or time (`dest`, `not_before`),
quiet, its outcome (`result`, `state`, `version`: xPerfect's run, so a question and the answer after it are told apart),
the telling in flight or done (`telling`, `told`), failed tellings per channel (`fails`, `wait`), whether xPerfect is
answering (`unreachable_since`), and whether it holds the job's run for room, with its own reason (`waiting`).
`state`, typed, as far as is known: starting (accepted, being admitted), admitted (xPerfect has it), queued (xPerfect
holds its run for room: `waiting` says why), running, unreachable (xPerfect not answering: its work may still run), then
its outcome's own word (completed, failed, needs_input: its Worker's `question` waits for his answer, cancelled).
A stop moves from stopping to stopped or stop_unconfirmed while its exact work is checked. A backup waiting for
terminal proof becomes backup_on_hold. Both provisional notices leave the job open after delivery.
A moment that woke her for it keeps its `schedule` and `occurrence` (core/clock).

Who tells it: the process that owns it (`owner`, a live pid): the channel he asked on, while it lives. A job nobody
owns goes to the channel he is on (`here`): a talking call first, then a typed chat around his turns, then Telegram; one
asked to be told somewhere goes only there. A job leaves only when told (or cancelled); one told but unconfirmed, a
question waiting for his answer, a quiet result and an unknown delivery stay, visible to her, never told again by
themselves.
"""
import fcntl
import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

from core.state import STATE_ROOT

FILE = STATE_ROOT / "core" / "jobs.json"
HERE = "here.json"  # beside the jobs file: the channels that can tell now, {pid: {"channel", "at"}}
TAKERS = ("call", "typed", "telegram")  # who takes a job nobody owns, first to last
FRESH = 45.0  # s a channel's word that it is there holds (each says it every 20 s)
FOLLOW_UP = 3600.0  # s a finished job keeps its route for his answer or a follow-up, then it leaves
WORKING = ("starting", "admitted", "queued", "running", "stopping")
STOP_CONFIRM_WAIT = 15.0  # seconds to wait for terminal proof before showing the stop as unconfirmed
STOP_UNCONFIRMED = "stop_unconfirmed"
STOPPING = ("stopping", STOP_UNCONFIRMED)
BACKUP_ON_HOLD = "backup_on_hold"
PROVISIONAL_RESULTS = (STOP_UNCONFIRMED, BACKUP_ON_HOLD)
TRIES = 3  # failed tellings on one channel before the job is released to another
WAIT = 300.0  # s the channel that failed waits before it tries again, doubling each time
PLAN_RETIRED = "ChatGPT plan background work ended. Its workspace and receipts were kept."
# Called with each job id that leaves (told and past FOLLOW_UP, told with no route to keep, or cancelled), after the
# file is written: what was kept for that job elsewhere goes with it (brain/queen.py adds xPerfect's forget_texts).
LEAVING: list = []
log = logging.getLogger("jobs")


@contextmanager
def _locked(file: Path | None = None, default=dict):
    """Read-modify-write under a file lock: a call and Telegram may touch jobs at the same time. (The jobs file by
    default, read when called: a test moves it, inside its own state.) Every file of it is his alone from the start
    (core/state.private_file: 0600 in folders 0700, never through a link): a job holds his words and its Worker's whole
    brief, the outbox her words to him."""
    from core.state import private_file
    file = Path(file or FILE)
    with private_file(file.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(file.read_text()) if file.exists() else default()
        yield data
        tmp = file.with_suffix(".tmp")
        with private_file(tmp, "w") as out:
            out.write(json.dumps(data, indent=1))
        os.replace(tmp, file)


def _here_file() -> Path:
    """Where the channels say they can tell now: beside the jobs file (a test moves it)."""
    return Path(FILE).with_name(HERE)


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError, PermissionError):
        return False


def update(job_id: str, **fields) -> None:
    with _locked() as jobs:
        job = jobs.setdefault(job_id, {"job_id": job_id, "t": round(time.time(), 3), "owner": os.getpid()})
        job.update(fields)


def amend(job_id: str, *, clear: tuple[str, ...] = (), **fields) -> bool:
    """update() for a job only while it is still here (a late word about a job cancelled meanwhile never makes it again)."""
    with _locked() as jobs:
        if job_id not in jobs:
            return False
        job = jobs[job_id]
        stop_states = (*STOPPING, "stopped")
        if job.get("state") in stop_states and fields.get("state") not in stop_states:
            return False
        for name in clear:
            job.pop(name, None)
        job.update(fields)
        return True


def request_stop(job_id: str) -> tuple[dict, bool]:
    """Keep the stop and discard the previous outcome in one write. Its notice follows the person."""
    with _locked() as jobs:
        job = jobs.get(job_id)
        if not job or job.get("state") in (*STOPPING, "stopped"):
            return dict(job or {}), False
        for name in ("result", "plain_result", "dest", "wait", "fails", "checking", "finished"):  # (a stop is not finished)
            job.pop(name, None)
        job.update(state="stopping", version=f"stop:{job_id}", owner=os.getpid(), stop_requested_at=time.time(), asking=False,
                   waiting=None, approvals={}, approval=None, approval_page_until=None, quiet=False,
                   held=None, told=None, telling=None, not_before=None)
        return dict(job), True


def end_admission(job_id: str) -> None:
    """Release this process's admission fence, including when another channel requested stop."""
    with _locked() as jobs:
        if (job := jobs.get(job_id)) and job.get("admitting") == os.getpid():
            job.pop("admitting")


def admitting(job: dict) -> bool:
    return _alive(job.get("admitting"))


def plan_bound(job: dict) -> bool:
    """Recognize the saved authorities from before attended-only plan use."""
    return (job.get("route") == "chatgpt-plan" or job.get("harness") == "chatgpt-plan"
            or bool(job.get("plan_authorizations"))
            or any((job.get("plan_admission") or {}).values()))


def _retire_plan(job: dict) -> None:
    if job.get("end_reason") != PLAN_RETIRED:
        job.update(state="failed", end_reason=PLAN_RETIRED, finished=time.time(), asking=False, waiting=None)
        job.setdefault("result", PLAN_RETIRED)


def retire_plan(job_id: str) -> bool:
    if not plan_bound(get(job_id)):
        return False
    with _locked() as jobs:
        if (job := jobs.get(job_id)) and plan_bound(job):
            _retire_plan(job)
            return True
    return False


def _left(job_ids) -> None:
    for job_id in job_ids:
        for hook in LEAVING:
            try:
                hook(job_id)
            except Exception as e:  # noqa: BLE001 (never in the way of the telling that settled it)
                log.warning("what was kept for job %s could not be removed: %s", job_id, e)


def drop(job_id: str) -> None:
    with _locked() as jobs:
        gone = jobs.pop(job_id, None) is not None
    _left([job_id] if gone else [])


def forget(job_id: str, *fields: str) -> None:
    """These fields of a job no longer hold (a question answered: its outcome and telling go, the job runs again)."""
    with _locked() as jobs:
        for name in fields:
            (jobs.get(job_id) or {}).pop(name, None)


def peek(*, strict: bool = False) -> dict:
    """Every job as it is now, read only (no lock held, nothing written): for a reader that looks often (the
    Subconscious, each second). A write in progress is never seen half done (the file is replaced whole).
    Strict readers distinguish a missing job file from one that could not be read."""
    try:
        return json.loads(FILE.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        if strict:
            raise
        return {}


def get(job_id: str) -> dict:
    return dict(peek().get(job_id) or {})


def _finished_at(job: dict) -> float:
    # Older status replies could save a finish time while the run still needed checking.
    return 0.0 if job.get("state") in PROVISIONAL_RESULTS else float(job.get("finished") or 0)


def open_jobs(*, strict: bool = False) -> list[dict]:
    """Work owed or running (a job told and finished is no longer open: finished())."""
    return sorted((job for job in peek(strict=strict).values() if not _finished_at(job)), key=lambda job: job["t"])


def finished(within: float = 0) -> list[dict]:
    """Jobs told and finished, kept with their route for FOLLOW_UP so his answer to a Worker's question (in Light it
    comes as the Worker's result) or a "now also…" reaches the same Worker; the newest first."""
    now, keep = time.time(), within or FOLLOW_UP
    return sorted((job for job in peek().values() if (at := _finished_at(job)) and now - at < keep),
                  key=lambda job: -_finished_at(job))


def working(job: dict) -> bool:
    """At work or in line for a place (in xPerfect's own queue too, `waiting` for room with its reason): no outcome yet,
    and xPerfect answering. (A question waiting for his answer, an unreachable job and a result are not work running:
    the night gives way only to work running.)"""
    if "result" in job:
        return False
    if job.get("state") == "stopping" and (since := job.get("stop_requested_at")):
        return time.time() < since + STOP_CONFIRM_WAIT
    return job["state"] in WORKING if job.get("state") else not job.get("unreachable_since")


def tellable(job: dict) -> bool:
    """An outcome still to be told by itself: not quiet, not before its time, not told, not held, not unknown, not
    waiting for a verdict on a telling that reached him."""
    if "result" not in job or job.get("quiet") or job.get("held") or time.time() < float(job.get("not_before") or 0):
        return False
    told, telling = job.get("told") or {}, job.get("telling") or {}
    if told and told.get("version") == job.get("version"):
        return False
    return not (telling.get("version") == job.get("version") and telling.get("state") in ("delivered", "unknown"))


# -- The channel he is on --

# -- His asks that never started (a late check behind words of hers that did not start them): until his next turn --

OWED = "owed.json"  # beside the jobs file
OWED_FOR = 6 * 3600.0  # s an owed ask is kept for his next turn, whatever channel it comes on


def owe(words: str, why: str = "") -> None:
    """An ask of his that never started, kept (a restart or another channel still shows it at his next turn)."""
    with _locked(Path(FILE).with_name(OWED), list) as owed_now:
        keep = [o for o in owed_now if o["words"] != words and time.time() - float(o.get("at", 0)) < OWED_FOR][-2:]
        owed_now[:] = keep + [{"words": words, "why": why, "at": time.time()}]


def owed(take: bool = False) -> list[str]:
    """His asks still owed, oldest first; take: his next turn sees them now, and they go."""
    with _locked(Path(FILE).with_name(OWED), list) as owed_now:
        words = [o["words"] for o in owed_now if time.time() - float(o.get("at", 0)) < OWED_FOR]
        if take:
            owed_now.clear()
    return words


def here(channel: str) -> None:
    """This process can tell results on `channel` now: a call in Talk with him there, a typed chat around his turns,
    Telegram with its owner's chat. Said every 20 s; it lapses after FRESH or when this process ends."""
    with _locked(_here_file()) as seen:
        seen[str(os.getpid())] = {"channel": channel, "at": time.time()}


def gone() -> None:
    """This process can no longer tell (a hang-up, Listen only)."""
    with _locked(_here_file()) as seen:
        seen.pop(str(os.getpid()), None)


def present() -> str:
    """The channel he is on now ("" when none): a talking call, else a typed chat around his turns, else Telegram with
    its owner (taker). Reminders and beats follow the same rule (core/schedules)."""
    return taker()


def taker() -> str:
    """The channel he is on now, as the channels themselves say it: the first live one of TAKERS ("" when none)."""
    with _locked(_here_file()) as seen:
        live = {v["channel"] for pid, v in seen.items() if _alive(pid) and time.time() - float(v.get("at", 0)) < FRESH}
    return next((channel for channel in TAKERS if channel in live), "")


def claim(channel: str = "", *, page_approvals: bool = True, approvals_only: bool = False) -> list[dict]:
    """Jobs nobody alive owns, now owned by this process. With `channel`: never one asked to be told elsewhere, never
    one waiting for this channel after its failed tellings, and none while a channel before it in TAKERS is live and
    could take it (he is on a call: Telegram leaves it to the call)."""
    first = taker() if channel else ""
    with _locked() as jobs:
        mine = []
        for job in jobs.values():
            if plan_bound(job):
                _retire_plan(job)
                continue
            if _alive(job.get("owner")) or _finished_at(job):
                continue
            if job.get("state") in PROVISIONAL_RESULTS:
                job.pop("finished", None)
            if job.get("state") in STOPPING and not approvals_only:
                # Reconciliation can run here even when an older stop still names another destination.
                job["owner"] = os.getpid()
                mine.append(job)
                continue
            page_approval = time.time() < (job.get("approval_page_until") or 0)
            # An idle page may finish a saved receipt's file without speaking again.
            file_debt = (channel in ("call", "typed") and job.get("worker_files_pending")
                         and job["worker_files_pending"].get("version") == job.get("version")
                         and (job.get("telling") or {}).get("state") == "delivered"
                         and (job.get("telling") or {}).get("version") == job.get("version"))
            if approvals_only and not (page_approval or file_debt):
                continue
            if page_approval and (not page_approvals or channel not in ("call", "typed")):
                continue
            if channel and not page_approval:
                if job.get("dest") and job["dest"] != channel:
                    continue
                if time.time() < float((job.get("wait") or {}).get(channel, 0)):
                    continue
                if not job.get("dest") and first and first != channel and TAKERS.index(first) < TAKERS.index(channel):
                    continue
            job["owner"] = os.getpid()
            mine.append(job)
        return sorted((dict(job) for job in mine), key=lambda job: job["t"])


def release(job_id: str = "") -> None:
    """This process stops watching (a hang-up: all its jobs; or one job, for another channel to take at once)."""
    with _locked() as jobs:
        for job in jobs.values():
            if job.get("owner") == os.getpid() and job_id in ("", job["job_id"]):
                job["owner"] = None


def take(job_id: str, version) -> bool:
    """This process owns one job nobody alive owns (or its own), still at this outcome (`version`): held while it decides
    about it (a verdict on words that may have given it), so no other channel takes it meanwhile. False changes nothing."""
    with _locked() as jobs:
        job = jobs.get(job_id)
        if job is None or job.get("version") != version or (job.get("owner") != os.getpid() and _alive(job.get("owner"))):
            return False
        job["owner"] = os.getpid()
        return True


def failed(job_id: str, channel: str, why: str) -> bool:
    """A telling that did not reach him on `channel` (a refused or failed send, nobody there to hear it). After TRIES on
    one channel the job is released, and that channel waits (WAIT, doubling) before it tries again. True when released."""
    with _locked() as jobs:
        job = jobs.get(job_id)
        if job is None:
            return True
        fails = job.setdefault("fails", {})
        fails[channel] = fails.get(channel, 0) + 1
        job["why"] = why
        if fails[channel] % TRIES:
            return False
        cycles = fails[channel] // TRIES
        job.setdefault("wait", {})[channel] = time.time() + WAIT * 2 ** (cycles - 1)
        job["owner"] = None
        return True


def mark(job_id: str, version, owner: int | None = None, **fields) -> bool:
    """A change about one outcome of a job (its telling, a verdict on it), made only while the job is still at that
    outcome (`version`) and this process's or nobody's: a stale change, from an outcome since replaced or a channel that
    lost it, is refused (False) and changes nothing."""
    with _locked() as jobs:
        job = jobs.get(job_id)
        if job is None or job.get("version") != version or job.get("owner") not in (owner or os.getpid(), None):
            return False
        job.update(fields)
        return True


def settle(job_id: str, version, owner: int | None = None, keep: bool = False, **fields) -> bool:
    """Settle a telling if its version and owner still match. A provisional result keeps the job open so its run can
    still be checked. A caller can also keep a question or an unconfirmed telling open with `keep`."""
    gone = []
    with _locked() as jobs:
        job = jobs.get(job_id)
        if job is None or job.get("version") != version or job.get("owner") not in (owner or os.getpid(), None):
            return False
        provisional = job.get("state") in PROVISIONAL_RESULTS
        if keep or provisional:
            job.update(fields)
            if provisional:
                job.pop("finished", None)
        elif job.get("conversation_id"):  # told and finished: kept with its route for a while (finished())
            job.update(fields, finished=time.time())
        else:
            jobs.pop(job_id)
            gone.append(job_id)
        for old in [k for k, j in jobs.items() if (at := _finished_at(j)) and not plan_bound(j)
                    and time.time() - at > FOLLOW_UP]:
            jobs.pop(old)
            gone.append(old)
    _left(gone)
    return True
