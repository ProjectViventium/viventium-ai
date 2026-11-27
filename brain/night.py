"""Sleep and Dreaming: what Viventium does at night (the requirement: sleep and dreaming as recurring
routines that make deeper connections and harden memory).

Each is a built-in routine on the same clock as your reminders: a moment every night at its time (core/routines.py,
core/schedules.set_routine). When it comes, the always-on channel starts it here, in a process of its own, so it
outlives a restart of that channel: one run on a Worker that can read and write files, given the routine's own words
(brain/routines/sleep.md, dreaming.md, the Scheduling page), where your Life folder and the day's conversations are, on
the routine's Worker type and thinking effort (on the Local profile: the Worker on this Mac), in the Subconscious' own
project, never mixed with your jobs. Its Worker is told truthfully that it writes your Life folder.

One night at a time, Sleep first (both started on the same tick, shared their files, and Dreaming ran out of
its time beside Sleep). A night is known by its evening's date (core/schedules.night_of), whatever the clock times say.
A run starts only when no other night run holds the night, and Dreaming only once that night's Sleep has ended (done,
failed, missed) or Sleep is off; this is decided and claimed under the schedules' lock, before any process starts.
Sleep's end wakes Dreaming at once. A claim is let go only when xPerfect shows the run ended.

Each routine has its own folder (state/core/night/<routine>/, owner-only): the day it goes through (day.txt, removed
after the run and when the next one starts), the claim (claim.json), the attempt (attempt.json: occurrence, try, route,
its xPerfect, Worker and run id, the span, then its outcome and the finishing steps done), where it stands and why
(status.json), where its last run that did its work ended (progress.json), what your Life folder was before this night
(before-<night>.json, kept across its tries), and Dreaming's note (note.txt). Only Dreaming writes what it leaves for
the morning (state/core/for-the-morning.json, with its own identity and whether it is being presented).

Waiting without losing the night. Your work comes first: it starts only while no job of yours runs or waits in line on
that place, and never during a call; on this Mac's model a call that begins, or the start of your day, makes it give
this Mac back. No Worker free (xPerfect's typed "no room"), xPerfect away: it says why and comes again ten minutes later.
Its route down: the next route you chose, as a cortex does (brain/rounds.py), and the route that did it is recorded. Its
window ends when your day begins (the beat's first hour); past it, its history line says "missed" and why. Each run goes
through a fixed span of the day and records it; the next run of that routine starts where the last one that did its
work ended (its progress mark, else its last history line that did its work; a week at most, and a longer backlog is
said, never dropped quietly); a part of the record that cannot be read is said, and goes to the next night.

Restart. Each attempt keeps where its run is: this Mac's xPerfect or the other, by its address, its state, a fingerprint
of that state's token and the principal it ran for, and its Worker and run id. After a restart its run is followed
there, by its id, to its end (on this Mac's model giving way to a call and to your day, the Mac held awake meanwhile);
an attempt that does not say all of that is never taken for the same xPerfect. Another run starts only once xPerfect
shows that run's own end: a stop asked is a request, a 404 is no proof, and the night is held, saying why and where you
stop it yourself (that xPerfect's own Workers page: its stop also stops the Worker). Every look of the clock takes up a
night left half done. A run that ended is finished as a journal: its outcome kept first, then its progress, Dreaming's
note, the commit (its own mark kept before it is made, so it is found wherever it is) and its history line, each once
and resumed after a crash, never run again; a routine switched off meanwhile still gets its line.

A night is done only when its routine's own outputs are there: its Changed: list (or "Changed: nothing") and, for
Dreaming, its one thing (its Worth saying: line, or "nothing", or its note). Else it failed, saying why, and its day goes
to the next night (a Dreaming whose Worker answered with broken text was recorded as done).

What a night wrote: each text file of your Life folder as it was before the night (its hash), against after; the files
its Worker names, as exact paths in the Life folder (one outside it is said, never used). Its history line keeps both.
With NIGHT_COMMIT=local, before its Worker is admitted, a private copy of every text
file of your Life is made and verified (one that is not whole stops that night, saying why; the last 3 nights' copies
are kept); then the files its Worker named and that changed, and only those, every path literal, are committed in your
Life's own git (never a repository it only sits inside), locally, never pushed, leaving everything else as it was.

Nobody is waiting: nothing is said at night. What it hands back is its history line on the Scheduling page. Dreaming's
one thing worth saying waits for the morning's first moment of continuous awareness (core/routines.py).

    python -m brain.night run <routine> <occurrence>     (started by the clock: brain/night.start)
    python -m brain.night commit <routine> <night>       (the files that night's run named, committed in Life's git)
"""
import asyncio
import datetime as dt
import hashlib
import inspect
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core import relationship, routines, schedules
from core.state import STATE_ROOT, call_live, closed_dir, log_file, private_dir, private_file, setting

ROOT = Path(__file__).resolve().parents[1]
NIGHT = schedules.NIGHT
NAMES = {"sleep": "Sleep", "dreaming": "Dreaming"}
WAIT = float(os.environ.get("NIGHT_WAIT") or 3 * 3600)  # one night's run, at most, from when it starts (bench: NIGHT_WAIT)
HOME = STATE_ROOT / "core" / "night"
FOR_MORNING = STATE_ROOT / "core" / "for-the-morning.json"  # what Dreaming left for the morning (only Dreaming writes it)
COPIES = STATE_ROOT / "night-copies"  # the private copy of Life files already changed before a night (the way back)
FRESH = 20 * 3600  # (left for this morning: by the next evening it is stale)
LONG = 2000  # (characters of a long Worker result kept in the day file; the rest is named by its line in the record)
OLDEST = 7 * 24 * 3600  # (a run goes through at most a week; an older backlog is said in its line)
WORTH = "Worth saying:"  # Dreaming's last line: the one thing worth saying in the morning, or "nothing"
CHANGED = "Changed:"  # the run's own list of the Life files it created, changed, renamed or deleted
BULLET = re.compile(r"^(?:[-*•]|\d+[.)])\s+")  # a list's own mark before a path, never part of its name
ENDED = ("completed", "failed", "cancelled", "interrupted", "timeout")
TEXT = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".org", ".tsv", ".html", ".xml", ".toml"}
log = logging.getLogger("night")


# -- its own files --

def folder(routine: str) -> Path:
    """A routine's own folder, his alone (core/state.private_dir: 0700, never through a link)."""
    return private_dir(HOME / routine)


def day_file(routine: str) -> Path:
    return folder(routine) / "day.txt"


def note_file() -> Path:
    return folder("dreaming") / "note.txt"  # where Dreaming's run leaves its one thing (a last line is no place)


def _read(path: Path) -> dict:
    try:
        found = json.loads(path.read_text())
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with private_file(tmp, "w") as f:  # (0600 from the start, never through a link: core/state)
        f.write(json.dumps(data, indent=1))
    tmp.replace(path)


def _status(routine: str, **fields) -> None:
    """Where a routine stands now, and why (the Scheduling page and the morning read it)."""
    _write(folder(routine) / "status.json", {"routine": routine, "since": dt.datetime.now().isoformat(timespec="seconds"), **fields})


def status(routine: str) -> dict:
    return _read(HOME / routine / "status.json")


# -- which process holds the night --

def _me() -> dict:
    return schedules.me()  # (its pid and when it started: core/schedules, shared with a reminder's telling)


def _alive(who: dict) -> bool:
    """Whether that process lives: its pid, and the same start (a pid taken again after a restart is not it)."""
    return schedules.alive(who)


def _holds(routine: str) -> dict:
    """The claim this routine holds on the night now ({} when none): its process alive, its run at xPerfect not yet
    known to have ended, or a start just being made."""
    claim = _read(HOME / routine / "claim.json")
    if not claim:
        return {}
    if claim.get("process") and _alive(claim["process"]):
        return claim
    if _pending(_read(HOME / routine / "attempt.json")):
        return claim  # (its run may still be going at xPerfect, or its finishing is not done: only a process that
        # follows or finishes it may go on)
    if not claim.get("process") and time.time() - float(claim.get("t") or 0) < 60:
        return claim  # (being started now: start() claims before the process exists)
    return {}


def _ended(routine: str, night: str, item: dict) -> bool:
    """Whether that routine's run of that night has ended: its history line (done, failed, missed, stopped), or it has
    moved past that night with nothing waiting for it (switched on after its time)."""
    zone = item.get("zone", "")
    if any(r["id"] == routine and (r.get("night") or schedules.night_of(r["due"], zone)) == night for r in schedules._load("runs")):
        return True
    if any(e["id"] == routine and schedules.night_of(e["occurrence"], zone) == night for e in schedules._load("due")):
        return False
    return schedules.night_of(schedules.stamp(schedules._at(item), zone), zone) > night


def turn(routine: str, occurrence: str, zone: str = "") -> str:
    """Why this routine's run may not start now ("" when it may): another night run holds the night, or (Dreaming)
    its night's Sleep has not ended. Read under the schedules' lock (exclusive)."""
    other = "dreaming" if routine == "sleep" else "sleep"
    if _holds(other):
        return f"{NAMES[other]} is running"
    if routine == "dreaming":
        sleep = next((i for i in schedules._load() if i["id"] == "sleep"), None)
        if sleep is not None and not sleep.get("paused") and not _ended("sleep", schedules.night_of(occurrence, zone), sleep):
            return "it comes after that night's Sleep"
    return ""


def start(item: dict) -> bool:
    """A night routine came due: claimed and started in a process of its own once it is its turn. False when it is not
    its turn yet or its run is going (the clock wakes it again; Sleep's end wakes Dreaming at once)."""
    routine, occurrence = item["id"], item["occurrence"]
    with schedules.exclusive():
        mine = _holds(routine)
        if mine and (not mine.get("process") or _alive(mine["process"])):
            return False  # (its run is going, or being started right now: never a second process)
        if not mine:  # (else its process ended while its run at xPerfect may still go on: a new one follows it again)
            why = turn(routine, occurrence, item.get("zone", ""))
            if why:
                _status(routine, state="waiting", why=why, occurrence=occurrence)
                return False
        claim = _read(HOME / routine / "claim.json") if mine else {}
        _write(folder(routine) / "claim.json", {**claim, "routine": routine, "occurrence": claim.get("occurrence", occurrence),
                                                 "night": schedules.night_of(occurrence, item.get("zone", "")), "t": time.time(),
                                                 "process": {}})
    try:
        out = log_file("night.log")  # (this run's own logs, his alone: core/state.py)
        subprocess.Popen([sys.executable, "-m", "brain.night", "run", routine, occurrence], cwd=ROOT,
                         stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
    except OSError:
        (HOME / routine / "claim.json").unlink(missing_ok=True)
        return False
    return True


def _let_go(routine: str) -> None:
    """The night is free again, unless this routine's run at xPerfect is not shown to have ended or its finishing is not
    done (the next process follows or finishes it)."""
    if _pending(_read(HOME / routine / "attempt.json")):
        return
    (HOME / routine / "claim.json").unlink(missing_ok=True)


# -- where it runs --

def place(routine: dict, env=None) -> tuple[bool, str, str]:
    """Where a night routine runs: (on this Mac's own xPerfect of a mix, the harness, its thinking effort). It writes
    files, so always on a Worker: the one its card names; on the Local profile, the Worker on this Mac."""
    from brain import xperfect
    from settings import catalog
    env = env if env is not None else os.environ
    if env.get("WORKERS", "local") == "local":
        return False, env.get("WORKER_PROFILE", "claude-code"), ""
    option = catalog.option("hands", routine.get("runs_on", ""))
    if option and option["where"] == "plan":
        effort = routine.get("effort", "")
        return False, option["harness"], effort if effort in option.get("efforts", []) else option.get("effort", "")
    if option and option["where"] == "mac" and xperfect.mixed():
        return True, env.get("WORKERS_LOCAL_PROFILE", "claude-code"), ""
    return False, env.get("WORKER_PROFILE", "codex-cli"), ""


def on_this_mac(local: bool) -> bool:
    """Whether a run on that place uses this Mac's model (one GPU, shared with her voice)."""
    return local or os.environ.get("WORKERS", "local") == "local"


def _working(job: dict) -> bool:
    """Whether a job of yours is at work or waiting in line for a place (xPerfect's own queue too, `waiting` for room
    with its reason): not one waiting for your answer, nor one whose xPerfect cannot be reached (they would
    hold the night until morning). Its typed state first; core/jobs.working where it is
    (an unreachable job is kept at state "running" with unreachable_since)."""
    from core import jobs
    rule = getattr(jobs, "working", None)
    if callable(rule):
        try:
            return bool(rule(job))
        except Exception:  # noqa: BLE001 (a job record of another shape: read as below)
            pass
    if "result" in job:
        return False
    state = str(job.get("state") or job.get("status") or "")
    if state:
        return state in ("starting", "admitted", "queued", "running")
    return not (job.get("question") or job.get("needs_input") or job.get("unreachable") or job.get("unreachable_since"))


def _busy(local: bool, harness: str) -> str:
    """Why the night waits now ("" when it need not): a call is on, or a job of yours runs or waits on that place."""
    from brain import xperfect
    from core import jobs
    if call_live():
        return "a call is on"
    first = os.environ.get("WORKER_PROFILE", "")
    if any(_working(j) and (xperfect.on_this_mac(j) if local else (j.get("harness") or first) == harness or not xperfect.mixed())
           for j in jobs.open_jobs()):
        return "your work is running"
    return ""


async def make_room(local: bool, harness: str = "") -> bool:
    """A job of yours is being handed off: when a night run holds a place it needs (that place is full with it), the
    run stops, and its routine stays due (it comes again once your work is done). Whether one was stopped."""
    from brain import xperfect
    from brain.xperfect import THINKING_TITLE, XPerfect
    from core import jobs
    for routine in NIGHT:
        held = _read(HOME / routine / "attempt.json")
        if not held.get("worker") or held.get("ended") or bool(held.get("local")) != bool(local):
            continue
        if held.get("harness") != harness:
            continue  # (another harness: places of its own)
        first = os.environ.get("WORKER_PROFILE", "")
        yours = sum(1 for j in jobs.open_jobs() if _working(j) and bool(xperfect.on_this_mac(j)) == bool(local)
                    and (j.get("harness") or first) == harness)
        if yours + 1 <= xperfect.slots(local):
            return False  # (room for both)
        _write(folder(routine) / "stop.json", {"why": "your work needed its place", "t": time.time()})
        await XPerfect(local=local, title=THINKING_TITLE).interrupt(held["worker"])
        log.info("%s: stopped for your work; it comes again", routine)
        return True
    return False


def room(local: bool, harness: str) -> int:
    """How much the night's model holds at once, in tokens, where its place says so: this Mac's model, through Claude
    Code, compacts at the model server's context (vx). 0 where it does not say (an online model holds far more)."""
    from brain import xperfect
    key = {"claude-code": "WPR_CLAUDE_CODE_MAX_CONTEXT_TOKENS"}.get(harness)
    try:
        return int(xperfect._config(local)["env"].get(key) or 0) if key else 0
    except (KeyError, OSError, ValueError, TypeError):
        return 0


# -- the day it goes through --

def _progress(routine: str) -> float | None:
    """Where this routine's last run that did its work ended: the record's own time, exactly (kept in whole
    seconds it reread a prefix, or skipped an unread line)."""
    kept = _read(HOME / routine / "progress.json")
    try:
        return float(kept["to_t"]) if "to_t" in kept else dt.datetime.fromisoformat(kept["to"]).timestamp()
    except (KeyError, ValueError, TypeError):
        return None


def _first_tried(routine: str) -> float | None:
    tried = [schedules.instant(r.get("due_at") or r["due"]).timestamp() for r in schedules._load("runs") if r["id"] == routine and r.get("due")]
    return min(tried) if tried else None


def _last_work(routine: str) -> float | None:
    """Where this routine's last run that did its work ended, by its history line (its span's end; a line from before
    spans were kept: its time): the first night after an update reads from there (with no progress file
    it went back four days, to a day before the first night that ever tried)."""
    for line in reversed(schedules._load("runs")):
        if line["id"] == routine and line.get("how") == "work":
            try:
                if line.get("span_t"):
                    return float(line["span_t"][1])
                return schedules.instant((line.get("span") or [None, None])[1] or line.get("due_at") or line["due"]).timestamp()
            except (KeyError, TypeError, ValueError, IndexError):
                continue
    return None


def span(routine: str, occurrence: str, now: float | None = None, zone: str = "") -> dict:
    """The fixed part of the conversation a run goes through: from where this routine's last run that did its work
    ended (its progress mark, else its last history line that did its work; with none: a day before its first night
    that tried), to now; Dreaming
    goes through the day its night's Sleep went through, to where Sleep stopped. At most a week: an older backlog is
    said ("limited"), never dropped quietly."""
    end = now or time.time()
    if routine == "dreaming":
        night = schedules.night_of(occurrence, zone)
        slept = next((r for r in reversed(schedules._load("runs")) if r["id"] == "sleep" and r.get("night") == night
                      and r.get("how") == "work" and r.get("span")), None)
        if slept:
            end = dt.datetime.fromisoformat(slept["span"][1]).timestamp()
    begin = _progress(routine)
    if begin is None:
        begin = _last_work(routine)
    if begin is None:
        tried = _first_tried(routine)
        begin = (tried - 24 * 3600) if tried is not None else end - 24 * 3600
    out = {"from": begin, "to": end}
    if end - begin > OLDEST:
        out.update(limited=f"the {round((end - OLDEST - begin) / 86400)} day(s) before "
                           f"{dt.datetime.fromtimestamp(end - OLDEST).strftime('%d %b %H:%M')} were not gone through", **{"from": end - OLDEST})
    return out


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


def day(routine: str, part: dict) -> tuple[int, int, str]:
    """The conversations of every channel in that span, with what the Workers did, oldest first, into the routine's
    own day file, each entry exactly as kept (line breaks too) under one line that says when, where, who, and its line
    in the record; files named under it. A Worker result longer than LONG is cut, naming its line in the record. (lines,
    words, problem): problem says why the record could not be read ("" when it could; an empty span is no problem).
    Lines of the record that cannot be read inside the span are said in part["unread"], and part["read_to"] is where
    the run's day may end for the next night (the unread part is gone through again then)."""
    target = day_file(routine)
    entries, problem, changes = [], "", []
    from core import life  # (each message as it stands now, by its line in the record alone)
    try:
        changes = life.in_force()  # (the change list unreadable: the day is not given at all, never as said)
        record = life.record_rows()
    except life.Unreadable as e:
        record, problem = [], f"what the user corrected and asked to forget could not be read ({e})"
        part["read_to"] = part["from"]  # (none of it was gone through: its day stays for the next night)
    except OSError as e:
        record, problem = [], f"the conversation record could not be read ({type(e).__name__})"
        part["read_to"] = part["from"]  # (none of it was gone through: its day stays for the next night)
    rows, unreadable = [], []
    for n, row in enumerate(record, 1):
        try:
            rows.append((n, float(row.get("t") or 0), row))
        except (ValueError, TypeError, AttributeError):
            unreadable.append(n)
    # (the record is kept in time order: a line that cannot be read lies in the span when it sits between the last
    # line before the span and the first line after it)
    before_n = max((n for n, at, _ in rows if at < part["from"]), default=0)
    after_n = min((n for n, at, _ in rows if at >= part["to"]), default=len(record) + 1)
    lost = [n for n in unreadable if before_n < n < after_n]
    for n, at, row in rows:
        if not part["from"] <= at < part["to"]:
            continue
        if lost and n > lost[0]:
            break  # (what follows the first unread line is gone through next night, with it)
        # (its line in the record is its one identity: what he asked to forget is left out, a correction said first,
        # from the record's own words; never matched by its words or its time)
        text = life.row_now(n, str(row.get("text") or ""), changes) if changes else str(row.get("text") or "")
        if not text.strip():
            continue
        if row.get("role") == "worker" and len(text) > LONG:
            text = text[:LONG] + f"\n(cut here: the whole result is line {n} of {life.record_where(routine)})"
        files = row.get("files") or []
        entries.append((at, n, row.get("channel") or "-", row.get("role") or "-", text, files))
    part.pop("unread", None)
    if not problem:
        part.pop("read_to", None)
    if lost:
        last = entries[-1][0] if entries else part["from"]
        part["unread"] = (f"{len(lost)} line(s) of the conversation record could not be read (line {lost[0]} on); "
                          f"its day from {dt.datetime.fromtimestamp(last).strftime('%d %b %H:%M')} goes to the next night")
        # (the next night starts just after the last line gone through, to the exact record time: nothing reread, nothing
        # skipped; with none gone through it starts where this one did)
        part["read_to"] = math.nextafter(last, math.inf) if entries else part["from"]
        if not entries:
            problem = f"the conversation record could not be read ({len(lost)} lines)"
    words = " ".join(e[4] for e in entries)
    mark = secrets.token_hex(4)
    while mark in words:
        mark = secrets.token_hex(4)
    head = (f"Their conversations from {_iso(part['from'])} to {_iso(part['to'])}, every channel, oldest first: "
            f"{len(entries)} entries.\nEach entry starts with a line \"=== {mark} | time | channel | who | record line\" "
            "and then is exactly what was said, its line breaks kept; a file sent or received is named under it.\n")
    body = []
    for at, n, channel, role, text, files in entries:
        body.append(f"=== {mark} | {dt.datetime.fromtimestamp(at).strftime('%Y-%m-%d %H:%M')} | {channel} | {role} | {n}\n{text}")
        for f in files:
            body.append("file: " + " ".join(str(f.get(k)) for k in ("path", "name", "kind") if isinstance(f, dict) and f.get(k)))
    with private_file(target, "w") as f:  # (his words on disk: his alone)
        f.write(head + "\n" + "\n".join(body) + ("\n" if body else "(nothing was said in this span)\n"))
    return len(entries), len(words.split()), problem


def sizes(folder_path, part: int = 0) -> str:
    """The Life folder's own top files, each with its size: what is large is known before anything is read (told
    to read large files in parts, the night's Worker still read a large one whole, the first its folder asks for). part:
    the bytes it reads at a time; a larger file says how many of its lines that is (Dreaming read 200 lines at a time,
    and two hundred of that file's long lines were near 50,000 characters: its model compacted after each)."""
    try:
        files = sorted(p for p in Path(folder_path).iterdir() if p.is_file() and not p.name.startswith("."))
    except OSError:
        return ""
    told, small = [], 0
    for p in files:
        size = p.stat().st_size
        if size < 1024:  # (tiny files are no risk to its room: counted, not listed)
            small += 1
            continue
        note = ""
        if part and size > part:
            try:
                with p.open("rb") as f:
                    lines = max(1, sum(1 for _ in f))
            except OSError:
                lines = 1
            note = (f" in {lines:,} lines: read it {max(1, part * lines // size)} lines at a time" if size / lines < part / 4
                    else ", its lines run long: search it (grep -n), never read it whole")
        told.append(f"{p.name} {size:,} bytes{note}")
    told = told[:40]
    if small:
        told.append(f"and {small} more, each under 1 KB")
    return "; ".join(told)


def instruction(routine: dict, part: dict | None = None, lines: int = 0, words: int = 0, now: dt.datetime | None = None,
                local: bool | None = None, harness: str | None = None, occurrence: str = "") -> str:
    """The routine's own words, then where things are on this Mac, as they are. Without `part`, its span for that
    occurrence (else now) is taken and its day file written first."""
    from core import life
    now = now or dt.datetime.now()
    if part is None:
        occurrence = occurrence or schedules.stamp(schedules.instant(now))
        part = {**span(routine["id"], occurrence, now=now.timestamp()), "night": schedules.night_of(occurrence)}
        lines, words, _ = day(routine["id"], part)
    folder_path = life.life()
    dreaming = routine["id"] == "dreaming"
    if local is None or harness is None:
        local, harness = place(routine)[:2]
    where = [f"- The person's Life folder: {folder_path}. Read its AGENTS.md first and follow it." if folder_path else
             "- There is no Life folder on this Mac: write nothing, and say so in what you hand back.",
             f"- Their conversations from {_iso(part['from'])[:16]} to {_iso(part['to'])[:16]}, every channel, with what "
             f"the Workers did: {day_file(routine['id'])} ({lines} entries, about {words:,} words, oldest first; each "
             "under a line with its time, channel, who (user, assistant or worker) and its line in the record; exactly "
             "as said). Yours to go through, all of it."
             + (f" Not gone through: {part['limited']}." if part.get("limited") else ""),
             f"- Everything said before that, to look something up (search it, never read it whole): "
             f"{life.record_where(routine['id'])} (JSON lines: t in seconds since the epoch, role, text, channel; line for "
             "line with the record, as it stands now)."]
    try:
        note = life.changes_note()  # (what he corrected and asked to forget, in words)
    except life.Unreadable as e:
        note = (f"What the user corrected and asked to forget could not be read ({e}): write nothing from their "
                "conversations into the Life folder tonight.")
    if note:
        where.append("- " + note + " Never write a forgotten thing back into the Life folder; write a correction into "
                     "it as their Life's own rules say (keep both, with their dates, and mark which is current).")
    held = room(local, harness)
    bite = held // 8  # (bytes read at a time on a model whose room is known: many small reads fit between compactions)
    if folder_path and sizes(folder_path, bite):
        where.append(f"- The Life folder's own top files, with their sizes: {sizes(folder_path, bite)}.")
    where.append("- Read the Life folder and the files named here, nothing else on this Mac. Read a large file in parts: "
                 "its size and lines first (wc -c -l), search it (grep -n), and read only the lines you need; change "
                 "files by small edits." + (f" This run's model holds about {held:,} tokens at once, its own instructions "
                 f"and tools taking about a quarter of that: read no more than about {bite:,} bytes at a time, never a "
                 "large file whole, even one its folder asks you to read first." if held else ""))
    if dreaming:
        slept = next((r for r in reversed(schedules._load("runs")) if r["id"] == "sleep" and r.get("how") == "work"
                      and r.get("night") == part.get("night") and r.get("result")), None)
        if slept:
            where.append(f"- What that night's Sleep handed back: {slept['result'][:600]}")
        # (before, it wrote a file of that name into the Life folder's Insights, and nothing
        # reached the morning)
        where.append(f"- Where to leave the one thing worth saying in the morning: the file {note_file()}, in Viventium's "
                     "own folder, never in the Life folder (that sentence alone, as you would say it to them; write no "
                     "file if nothing is).")
    ask = (f"\n\nAt the end, on lines of their own: {CHANGED} and then every file in the Life folder you created, changed, "
           f"renamed or deleted, one path per line relative to the Life folder (or {CHANGED} nothing).")
    ask += (f" Then, on its own last line, {WORTH} and the same sentence, or {WORTH} nothing.") if dreaming else ""
    return (f"{routine['prompt'].strip()}\n\nIt is {now.strftime('%A %d %B %Y, %H:%M')}. Where things are, on this Mac:\n"
            + "\n".join(where) + "\nChange nothing outside the Life folder" + (" and that one file" if dreaming else "")
            + ", and send no message to anyone." + ask)


def worth_saying(text: str) -> tuple[str, str]:
    """Dreaming's answer as (what it hands back, the one thing worth saying in the morning or "")."""
    lines = (text or "").strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        bare = _bare(lines[i])
        if bare.lower().startswith(WORTH.lower()):
            said = bare[len(WORTH):].strip().strip("*_\"' ")
            rest = "\n".join(lines[:i] + lines[i + 1:]).strip()
            return rest, "" if said.lower().rstrip(".") in ("", "nothing") else said
    return (text or "").strip(), ""


def _bare(line: str) -> str:
    """A line as its heading is read: quoted, in bold, italics or code, still the same line ("*Worth saying:*"
    read as content)."""
    return re.sub(r"[*_`]+", "", line.strip().lstrip(">").strip()).strip()


def _heading(line: str) -> bool:
    """Whether a line is one of a run's own declared headings (CHANGED, WORTH), however quoted or formatted."""
    bare = _bare(line).lower()
    return bare.startswith(CHANGED.lower()) or bare.startswith(WORTH.lower())


def _said_after(text: str, mark: str) -> str | None:
    """What a run's answer says after one of its own declared lines (CHANGED, WORTH), as named_changes and worth_saying
    read them (quoted or in bold too): the rest of that line, and for CHANGED its list below it. None with no such line."""
    lines = (text or "").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        bare = _bare(lines[i])
        if not bare.lower().startswith(mark.lower()):
            continue
        said = [bare[len(mark):].strip().strip("`*_\"' ")]
        if mark == CHANGED:
            for below in lines[i + 1:]:
                if not below.strip() or _heading(below):
                    break
                said.append(BULLET.sub("", below.strip()).strip().strip("`"))
        return " ".join(p for p in said if p)
    return None


def missing(routine: str, text: str, note: str = "") -> str:
    """What of a routine's own outputs its answer lacks ("" when nothing): its CHANGED list (files, or "nothing") and,
    for Dreaming, its one thing (its WORTH line with a sentence or "nothing", or the note it left). A heading with
    nothing after it is missing, not work. A Dreaming whose Worker answered with broken text
    and a chat reply to him, none of it Dreaming's work, was recorded "work"."""
    lacks = []
    if not _said_after(text, CHANGED):
        lacks.append(f'no "{CHANGED}" list (nor "{CHANGED} nothing")')
    if routine == "dreaming" and not _said_after(text, WORTH) and not note.strip():
        lacks.append(f'no "{WORTH}" line with its sentence (nor "{WORTH} nothing") and no note')
    return "; ".join(lacks)


def named_changes(text: str) -> tuple[str, list[str]]:
    """A run's answer as (what it hands back, the Life files it says it created, changed, renamed or deleted): the lines
    after its own "Changed:" line, until a blank line or Dreaming's last line."""
    lines = (text or "").strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if _bare(lines[i]).lower().startswith(CHANGED.lower()):
            paths, j = [], i + 1
            raw = lines[i]  # (a path on its own line after the heading, its own characters kept: `_` is no formatting there)
            first = raw[raw.lower().find(CHANGED.lower()) + len(CHANGED):].strip().strip("*_` ")
            if first and first.lower().rstrip(".") != "nothing":
                paths.append(first)
            while j < len(lines) and lines[j].strip() and not _heading(lines[j]):
                # (a list's bullet only when a space follows it: a file named `*.md` keeps its star)
                paths.append(BULLET.sub("", lines[j].strip()).strip().strip("`"))
                j += 1
            rest = "\n".join(lines[:i] + lines[j:]).strip()
            return rest, [p for p in paths if p and p.lower().rstrip(".") != "nothing"]
    return (text or "").strip(), []


# -- what a night wrote --

def committing() -> bool:
    """Whether a night commits what its Worker named (NIGHT_COMMIT=local or the
    setting; off by default)."""
    return os.environ.get("NIGHT_COMMIT") == "local" or setting("night_commit") is True


def _git(root: Path, *args) -> subprocess.CompletedProcess:
    """Git in the Life folder, every path given to it literal (`*.md` is that one file, never a pattern)."""
    return subprocess.run(["git", "--literal-pathspecs", "-C", str(root), *args], capture_output=True, text=True, timeout=60)


def _own_repo(root: Path) -> str:
    """Why the Life folder's git is not its own ("" when it is): a night commits only where the repository's top is the
    Life folder itself (with Life inside a larger repository, a line of that repository not yet committed went into the night's
    commit)."""
    got = _git(root, "rev-parse", "--show-toplevel")
    if got.returncode != 0:
        return "the Life folder is not a git repository"
    try:
        same = Path(got.stdout.strip()).resolve() == Path(root).resolve()
    except OSError:
        same = False
    return "" if same else "the Life folder is inside a larger git repository, not one of its own"


def life_path(root: Path, name: str) -> str | None:
    """A file its Worker named, as its exact path relative to the Life folder (no character dropped: `.plan.md` stays
    `.plan.md`; an absolute path inside the Life folder is made relative), or None for anything not inside it: `../x.md`,
    a path elsewhere, its own git folder, a folder of it that is a link out."""
    name = (name or "").strip()
    if not name or "\0" in name:
        return None
    raw = os.path.normpath(name if os.path.isabs(name) else os.path.join(str(root), name))
    rel = None
    for top in (os.path.normpath(str(root)), os.path.realpath(str(root))):
        if raw == top or not raw.startswith(top.rstrip(os.sep) + os.sep):
            continue
        rel = Path(raw[len(top.rstrip(os.sep)) + 1:])
        break
    if rel is None or not rel.parts or rel.parts[0] in ("..", ".git"):
        return None
    base = Path(os.path.realpath(str(root)))
    if not Path(os.path.realpath(str(base / rel.parent))).is_relative_to(base):
        return None  # (one of its folders is a link that leads out of the Life folder)
    return rel.as_posix()


def _text_files(root: Path) -> tuple[list[tuple[str, Path]], str]:
    """The Life folder's text files, as (path relative to it, the file), its own git folder and links aside, and why the
    scan is not whole ("" when it is): a folder that could not be listed is said, never skipped quietly (a
    PermissionError mid-scan left a "complete" copy of one file)."""
    found, problems = [], []

    def refused(error: OSError) -> None:
        problems.append(f"{Path(error.filename or '?').name} could not be listed ({type(error).__name__})")
    for top, folders, names in os.walk(root, onerror=refused, followlinks=False):
        here = Path(top)
        if here == Path(root):
            folders[:] = [f for f in folders if f != ".git"]
        for name in sorted(names):
            path = here / name
            if path.suffix.lower() not in TEXT or path.is_symlink() or not path.is_file():
                continue
            found.append((path.relative_to(root).as_posix(), path))
    return sorted(found), "; ".join(problems[:3]) + (f" and {len(problems) - 3} more" if len(problems) > 3 else "")


def _life_files(root: Path) -> tuple[dict, str]:
    """The Life folder's text files, each with its content's hash, and why that is not all of them ("" when it is)."""
    out, problems = {}, []
    found, scan = _text_files(root)
    for rel, path in found:
        try:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as e:
            problems.append(f"{rel} could not be read ({type(e).__name__})")
    return out, "; ".join(p for p in (scan, *problems[:3]) if p)


def _dirty(root: Path) -> list[str] | None:
    """Life files already changed (or new) in its git before the night, relative to the Life folder: None when Life is
    not a repository of its own."""
    got = _git(root, "status", "--porcelain", "-z", "--untracked-files=all")
    if got.returncode != 0:
        return None
    out, parts = [], got.stdout.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        if len(entry) > 3:
            out.append(entry[3:])
            if entry[0] in "RC":  # (a rename names its source next)
                i += 1
                if i < len(parts) and parts[i]:
                    out.append(parts[i])
        i += 1
    return out


SPARE = 5 * 1024 ** 3  # bytes of disk a copy leaves free at least (xPerfect refuses runs with too little)


def _copy(root: Path, target: Path) -> tuple[dict, str]:
    """Every text file of the Life folder into its private copy, read once (its hash is of what was copied), then each
    copy read back and checked against that hash: (the files and their hashes, why the copy is not whole or "")."""
    shutil.rmtree(target, ignore_errors=True)  # (an earlier try's, never trusted)
    found, scan = _text_files(root)
    if scan:
        return {}, f"the Life folder could not be read whole: {scan}"
    try:
        size = sum(path.stat().st_size for _, path in found)
        free = shutil.disk_usage(private_dir(target.parent)).free
    except OSError as e:
        return {}, f"its size could not be read ({type(e).__name__})"
    if free - size < SPARE:
        return {}, f"this Mac has too little free disk for it ({free // 1024 ** 3} GB free, {size // 1024 ** 2} MB to copy)"
    files = {}
    for rel, path in found:
        try:
            data = path.read_bytes()
        except OSError as e:
            return {}, f"{rel} could not be read ({type(e).__name__})"
        try:
            with private_file(target / rel, "wb") as out:  # (his alone: core/state)
                out.write(data)
        except OSError as e:
            return {}, f"{rel} could not be copied ({type(e).__name__})"
        files[rel] = hashlib.sha256(data).hexdigest()
    for rel, digest in files.items():
        try:
            if hashlib.sha256((target / rel).read_bytes()).hexdigest() != digest:
                return {}, f"the copy of {rel} is not what was read"
        except OSError as e:
            return {}, f"the copy of {rel} could not be read back ({type(e).__name__})"
    return files, ""


def _prune_copies(keep: int = 3) -> None:
    """Only the last `keep` nights' copies stay."""
    try:
        made = [p for p in COPIES.iterdir() if p.is_dir() and not p.is_symlink()]
    except OSError:
        return
    nights = sorted({p.name[:10] for p in made}, reverse=True)[:keep]
    for p in made:
        if p.name[:10] not in nights:
            shutil.rmtree(p, ignore_errors=True)


def _valid(kept: dict) -> str:
    """Why a night's "before" cannot be used now ("" when it can): it holds only for the commit setting and the copy it
    was made with (one made with commits off was reused once they were on, with no copy at all)."""
    if not kept:
        return "none was taken"
    if bool(kept.get("commit")) != committing():
        return "commits were switched " + ("on" if committing() else "off") + " since it was taken"
    if committing():
        copy = Path(kept.get("copy") or "")
        files = kept.get("files") or {}
        if not kept.get("copy") or not copy.is_dir():
            return "its copy is gone"
        for rel, digest in files.items():  # (each file as copied, read back: an altered copy is no copy)
            try:
                if hashlib.sha256((copy / rel).read_bytes()).hexdigest() != digest:
                    return "its copy is not what was copied any more"
            except OSError:
                return "its copy is not whole any more"
    return ""


def before(routine: str, night: str) -> dict:
    """What the Life folder was before this night's run of this routine: each text file's hash, kept across its tries (a
    run stopped for your work and started again does not take a second "before"), valid only for the commit setting and
    copy it was made with. With commits on, first a private copy of every one of its
    text files, verified, before its Worker is admitted: {"failed": why} when the Life folder could not be read whole or
    copied whole, and that night does not run. With commits off, no copy; a scan that is not whole is said in its line."""
    from core import life
    path = folder(routine) / f"before-{night}.json"
    kept = _read(path)
    root = life.life()
    if not root:
        return kept
    why_again = _valid(kept) if kept else ""
    if kept and not why_again:
        return kept
    own = _own_repo(root)
    dirty = None if own else _dirty(root)
    copy, scan = "", ""
    if committing():
        target = COPIES / f"{night}-{routine}"
        files, why = _copy(root, target)
        if why:
            shutil.rmtree(target, ignore_errors=True)
            log.warning("%s: no copy of the Life folder before the night: %s", routine, why)
            return {"failed": why}
        copy = str(target)
        _prune_copies()
    else:
        files, scan = _life_files(root)
    for old in folder(routine).glob("before-*.json"):  # (an earlier night's, or this one's no longer valid)
        old.unlink(missing_ok=True)
    kept = {"night": night, "at": time.time(), "files": files, "dirty": dirty, "git": not own, "why_no_commit": own,
            "copy": copy, "commit": committing(), **({"scan": scan} if scan else {}),
            **({"taken_again": why_again} if why_again else {})}
    _write(path, kept)
    log.info("%s: the Life folder before the night of %s: %d files%s", routine, night, len(files), ", copied" if copy else "")
    return kept


def wrote(routine: str, night: str, named: list[str]) -> dict:
    """What changed in the Life folder since this night's "before": the files the run named and that changed (clean
    before: these may be committed), those it named that were already changed before the night, every other change
    ("changed during the night, not named"), and what it named outside the Life folder (never committed)."""
    from core import life
    was = _read(folder(routine) / f"before-{night}.json")
    root = life.life()
    if not was or not root:
        return {}
    now, scan = _life_files(root)
    old = was.get("files") or {}
    changed = sorted({p for p in set(old) | set(now) if old.get(p) != now.get(p)})
    inside = [(n, life_path(root, n)) for n in named]
    mine = {rel for _, rel in inside if rel}
    dirty = set(was.get("dirty") or [])
    picked = [p for p in changed if p in mine]
    out = {"committable": [p for p in picked if p not in dirty] if was.get("git") else [],
           "was_changed": [p for p in picked if p in dirty], "not_named": [p for p in changed if p not in mine],
           "named_unchanged": sorted(p for p in mine if p not in changed), "copy": was.get("copy", "")}
    if outside := [n for n, rel in inside if not rel]:
        out["named_outside"] = outside[:20]
    if was.get("why_no_commit"):
        out["why_no_commit"] = was["why_no_commit"]
    if was.get("scan") or scan:  # (what could not be read before or after: what it wrote there is not known)
        out["scan_incomplete"] = "; ".join(p for p in (was.get("scan", ""), scan) if p)
    if was.get("taken_again"):
        out["before_taken_again"] = was["taken_again"]
    return out


def _message(routine: str, night: str) -> str:
    return f"Viventium {NAMES.get(routine, routine)}, night of {night}"


MARK = "Viventium-Night:"  # (the trailer a night's commit carries: its own mark, kept in the journal before it is made)


def commit(routine: str, night: str, paths: list[str] | None = None, mark: str = "") -> str:
    """The files that night's run named and that changed (clean before it), committed in the Life folder's own git:
    only those, every path literal, locally, never pushed; what is staged or changed there otherwise stays exactly as it
    was. Never in a repository whose top is not the Life folder. The commit's id, or "" (nothing to commit, no git of
    its own, or it could not be made)."""
    from core import life
    root = life.life()
    if root is None or _own_repo(root):
        return ""
    if paths is None:
        last = next((r for r in reversed(schedules._load("runs")) if r["id"] == routine and r.get("night") == night
                     and r.get("how") == "work"), {})
        paths = (last.get("life") or {}).get("committable") or []
    paths = list(dict.fromkeys(p for p in (life_path(root, p) for p in paths) if p))
    if not paths:
        return ""
    known = set(_git(root, "ls-files", "-z", "--", *paths).stdout.split("\0"))
    new = [p for p in paths if p not in known and (root / p).exists()]
    if new and _git(root, "add", "--", *new).returncode != 0:
        _git(root, "reset", "-q", "--", *new)
        return ""
    who = ["-c", "user.name=Viventium (night)", "-c", "user.email=night@viventium.invalid"]
    got = _git(root, *who, "commit", "--only", "--no-verify", "-m", _message(routine, night),
               *(["-m", f"{MARK} {mark}"] if mark else []), "--", *paths)
    if got.returncode != 0:
        if new:
            _git(root, "reset", "-q", "--", *new)  # (his index as it was: the new files untracked again)
        return ""
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _committed(mark: str) -> str:
    """The commit a night made before a crash, found by its own mark wherever it is in the history, however many
    commits came after it: "" when there is none, so it was never made."""
    from core import life
    root = life.life()
    if root is None or _own_repo(root) or not mark:
        return ""
    got = _git(root, "log", "--all", "--fixed-strings", f"--grep={MARK} {mark}", "--format=%H")
    found = got.stdout.split() if got.returncode == 0 else []
    return found[0] if found else ""


# -- what Dreaming leaves for the morning --

OFFERS = 2  # beats that may offer one note: a second only when the first said something not known to be it


def _note_id(note: dict) -> str:
    """A note's identity: its Dreaming occurrence; a note from before ids were kept ({"text", "at"}, main's old night
    code) is note-<its time> (it raised KeyError 'id')."""
    return str(note.get("id") or f"note-{int(float(note.get('at') or 0))}")


def keep_for_morning(text: str, occurrence: str = "", night: str = "") -> None:
    """Dreaming's one thing, kept as something owed to the morning, with its own identity (Dreaming's occurrence)."""
    closed_dir(FOR_MORNING.parent)
    _write(FOR_MORNING, {"id": occurrence or f"note-{int(time.time())}", "night": night, "text": text, "at": time.time(),
                         "state": "waiting", "offers": 0})


def morning_note() -> dict:
    """Dreaming's note while it is owed to the morning ({} otherwise): waiting, or said by a beat whose words could not
    be checked (unverified: offered once more, at the next beat that can say it). One left too long (FRESH) is not
    handed over (stale); one a beat was presenting when its process ended may have been said (unknown: never again by
    itself)."""
    note = _read(FOR_MORNING)
    if not note.get("text"):
        return {}
    note["id"] = _note_id(note)
    state = note.get("state", "waiting")
    if state == "presenting":
        if _alive(note.get("by") or {}):
            return {}  # (a beat is presenting it now)
        handed(note, "unknown", "its beat ended before it was known whether it was said")
        return {}
    if state not in ("waiting", "unverified") or int(note.get("offers") or 0) >= OFFERS:
        return {}
    if time.time() - float(note.get("at") or 0) >= FRESH:
        handed(note, "stale")
        return {}
    from core import life
    try:  # (written before a forget made since, it may hold what he asked to forget: never said)
        if any(c["kind"] == "forget" and float(c.get("at") or 0) > float(note.get("at") or 0) for c in life.in_force()):
            handed(note, "stale", "a forget was made after it was written")
            return {}
    except life.Unreadable:
        return {}  # (nothing of it while the change list cannot be read)
    return note


def presenting(note: dict) -> bool:
    """A beat is about to let her say Dreaming's note: written before anything is sent, with the process that says it,
    so a crash in between is "unknown", never a second telling. False when it is no longer this beat's."""
    with schedules.exclusive():
        current = _read(FOR_MORNING)
        if not current.get("text") or _note_id(current) != note.get("id") or current.get("state", "waiting") not in ("waiting", "unverified"):
            return False
        _write(FOR_MORNING, {**current, "id": note["id"], "state": "presenting", "was": current.get("state", "waiting"),
                             "by": _me(), "presenting_at": time.time(), "offers": int(current.get("offers") or 0) + 1})
    return True


def handed(note: dict, state: str, detail: str = "") -> None:
    """What became of Dreaming's note at a beat: told (said), unverified (her delivered words could not be checked: it
    is offered once more), unknown (whether it was delivered is not known: never sent again by itself), kept (she
    keeps it in mind), refused (nothing went out: it waits again), or stale. Its history line says which, and when."""
    current = _read(FOR_MORNING)
    if not current.get("text") or _note_id(current) != _note_id(note):
        return  # (a newer night's note took its place)
    if state == "refused":
        if current.get("state") == "presenting":
            _write(FOR_MORNING, {**current, "id": _note_id(current), "state": current.get("was", "waiting"),
                                 "offers": max(0, int(current.get("offers") or 1) - 1)})
        return
    if state == "unverified" and int(current.get("offers") or 0) < OFFERS:
        _write(FOR_MORNING, {**current, "id": _note_id(current), "state": "unverified", "handed_at": time.time(),
                             **({"detail": detail} if detail else {})})
        return  # (offered once more; its line says so when that beat is done)
    _write(FOR_MORNING, {**current, "id": _note_id(current), "state": state, "handed_at": time.time(),
                         **({"detail": detail} if detail else {})})
    if _note_id(note).startswith("note-"):
        return
    schedules.annotate("dreaming", _note_id(note), morning=state, morning_at=dt.datetime.now().isoformat(timespec="seconds"))


def for_the_morning() -> str:
    """What Dreaming left for the morning, while it is fresh and not yet handed over: "" otherwise."""
    return morning_note().get("text", "")


def handed_over() -> None:
    """(The beat before core/routines.py: it handed the note to a thought of hers, whose outcome it did not know.)"""
    if note := morning_note():
        handed(note, "unknown", "handed to a thought")


# -- the run --

def _caffeinate() -> None:
    """This Mac stays awake while the run goes on (no setting changed: the assertion ends with this process)."""
    if shutil.which("caffeinate"):
        try:
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass


def _accepts(think, name: str) -> bool:
    try:
        return name in inspect.signature(think).parameters
    except (TypeError, ValueError):
        return False


ROLE = {"sleep": "Viventium's Sleep: it goes through the person's day and writes what should last into their Life folder "
                 "by small edits, following that folder's own rules; it changes nothing outside the Life folder and sends "
                 "no message to anyone",
        "dreaming": "Viventium's Dreaming: it wanders through the person's Life folder for connections nobody has made yet and "
                    "writes at most three to its Insights, and one note in Viventium's own folder; it changes nothing else and "
                    "sends no message to anyone"}
STOP_WAIT = 60.0  # s a stop may take before the run's end is shown (else its claim is kept)
LOOK = 10.0  # s between two looks for a call or the day's start while a run on this Mac's model goes on


def _fingerprint(state: str) -> str:
    """A fingerprint of that xPerfect state's own token (the start of its hash, never the token): a state or database put
    in its place comes with another."""
    try:
        token = json.loads((Path(state) / "secrets.json").read_text())["api_token"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    return hashlib.sha256(str(token).encode()).hexdigest()[:16]


def _where(local: bool) -> dict:
    """The xPerfect a run is made on, as its attempt keeps it: this Mac's own or the other, its address, its state and
    that state's token fingerprint (its principal is added once xPerfect answers: _principal)."""
    state = os.environ.get("XPERFECT_LOCAL_STATE" if local else "XPERFECT_STATE", "")
    return {"local": bool(local), "api": os.environ.get("XPERFECT_LOCAL_API" if local else "XPERFECT_API", ""),
            "xp_state": state, "xp_key": _fingerprint(state)}


async def _principal(xp) -> str:
    """Who this client is at that xPerfect (its tenant and user, /v1/me): "" when it does not answer."""
    code, me = await _get(xp, "/v1/me")
    return f"{me.get('tenant_id', '')}/{me.get('user_id', '')}" if code == 200 else ""


async def _not_same(held: dict, xp=None) -> str:
    """Why the xPerfect a run from before ran on cannot be shown to be the one set now ("" when it is): its address, its
    state, that state's token and its principal, each as kept with the attempt (a saved address alone does not
    prove the same server, database or principal; xPerfect answers 404 for another principal's run)."""
    now = _where(bool(held.get("local")))
    for key, said in (("api", "address"), ("xp_state", "state"), ("xp_key", "token"), ("principal", "principal")):
        if not held.get(key):  # (not kept with it: unknown, never a match)
            return f"its run from before does not say which xPerfect it ran on (no {said} was kept with it)"
    for key, said in (("api", "address"), ("xp_state", "state"), ("xp_key", "token")):
        if held[key] != now[key]:
            return f"its run from before ran on another xPerfect (its {said} differs)"
    if xp is None:
        return "the xPerfect it ran on cannot be asked"
    principal = await _principal(xp)
    if not principal:
        return "the xPerfect it ran on does not answer"
    if principal != held["principal"]:
        return "its run from before ran for another principal of that xPerfect"
    return ""


def _outcome(run: dict) -> dict:
    return {"state": run.get("state"), "output_text": run.get("output_text") or "", "error_text": run.get("error_text") or "",
            "failure_class": run.get("failure_class") or "", "run_id": run.get("run_id", ""),
            "usage": {k: run.get(k) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens", "total_tokens")}}


async def _get(xp, path: str) -> tuple[int, dict]:
    """(status, body) of one GET at xPerfect; status 0 when it could not be asked."""
    import httpx
    try:
        got = await xp.http.get(path)
        return got.status_code, (got.json() if got.content else {})
    except (httpx.HTTPError, ValueError):
        return 0, {}


async def _run_id(xp, attempt: dict, attempt_file: Path) -> str | None:
    """The run its Worker has at xPerfect, by its id, kept with the attempt once known. "" when its Worker has none (yet);
    None when xPerfect cannot be asked or does not know the Worker (never taken as an end: _look)."""
    if attempt.get("run_id"):
        return attempt["run_id"]
    code, body = await _get(xp, f"/v1/workers/{attempt['worker']}/runs")
    if code != 200:
        return None
    items = body.get("items") or []
    if not items:
        return ""
    attempt["run_id"] = max(items, key=lambda r: str(r.get("queued_at") or ""))["run_id"]
    _write(attempt_file, attempt)
    return attempt["run_id"]


async def _keep_run_id(xp, attempt: dict, attempt_file: Path) -> None:
    """While its run is being made: its id kept with the attempt as soon as xPerfect lists it."""
    while not attempt.get("run_id"):
        if attempt.get("worker"):
            await _run_id(xp, attempt, attempt_file)
        await asyncio.sleep(1.0)


async def _look(xp, attempt: dict, attempt_file: Path) -> tuple[str, dict | None, str]:
    """One look at the attempt's own run at xPerfect: ("ended", its record, ""), ("running", None, ""), ("away", None,
    why) when xPerfect does not answer, or ("unknown", None, why) when it answers but cannot show that run. Only
    xPerfect's own end of that run (its terminal state, for that Worker) ends it; a 404 is never proof. Its
    Worker that never had a run is ended only once that Worker is closed and shown closed, with still no run."""
    run_id = await _run_id(xp, attempt, attempt_file)
    worker = attempt["worker"]
    if run_id is None:
        code, _ = await _get(xp, f"/v1/workers/{worker}")
        return ("unknown", None, "its Worker is not known to the xPerfect it ran on") if code == 404 else \
            ("away", None, "xPerfect does not answer")
    if run_id == "":
        if await xp.close(worker):
            code, held = await _get(xp, f"/v1/workers/{worker}")
            listed, runs = await _get(xp, f"/v1/workers/{worker}/runs")
            closed = code == 200 and (held.get("state") == "terminated" or held.get("catalog_state") == "deleted" or held.get("closed"))
            if closed and listed == 200 and not (runs.get("items") or []):
                return "ended", {"state": "none"}, ""
        return "away", None, "its Worker had no run, and could not be shown closed"
    code, run = await _get(xp, f"/v1/runs/{run_id}")
    if code == 200 and run.get("worker_id") not in (None, "", worker):
        return "unknown", None, "that run belongs to another Worker there"
    if code == 200:
        return ("ended", _outcome(run), "") if run.get("state") in ENDED else ("running", None, "")
    if code == 404:
        return "unknown", None, "its run is not known to the xPerfect it ran on (never taken as ended)"
    return "away", None, "xPerfect does not answer"


async def _shown_end(xp, attempt: dict, attempt_file: Path) -> dict | None:
    """The end of the attempt's own run as xPerfect shows it; still going, it is asked to stop and watched for
    STOP_WAIT. None when the end cannot be shown: the claim is kept (a stop asked is a request, never proof)."""
    end = time.time() + STOP_WAIT
    asked = False
    while True:
        seen, outcome, why = await _look(xp, attempt, attempt_file)
        if seen == "ended":
            return outcome
        if seen == "running" and not asked:
            attempt["asked_stop"] = attempt.get("asked_stop") or time.time()
            _write(attempt_file, attempt)
            await xp.interrupt(attempt["worker"])
            asked = True
        if time.time() > end:
            attempt["why"] = why or "its stop is asked, and xPerfect has not shown it ended"
            return None
        await asyncio.sleep(1.0)


async def _follow(xp, attempt: dict, attempt_file: Path) -> dict | None:
    """A night run at xPerfect followed by its own run id to its end, where it ran (after a restart, or when the
    client lost it mid-way); past its time (WAIT from when it began), or with a stop asked before, it is asked to stop.
    Its record; None while xPerfect cannot show its end (attempt["why"] says why: it waits, never ended by a guess)."""
    deadline = float(attempt.get("began") or time.time()) + WAIT
    while True:
        if time.time() > deadline or attempt.get("asked_stop"):
            late = time.time() > deadline
            stopped = await _shown_end(xp, attempt, attempt_file)
            if stopped is None:
                return None
            return {**stopped, "state": "timeout"} if late and stopped["state"] in ("interrupted", "cancelled") else stopped
        seen, outcome, why = await _look(xp, attempt, attempt_file)
        if seen == "ended":
            return outcome
        if seen in ("away", "unknown"):
            attempt["why"] = why
            return None
        await asyncio.sleep(2.0)


async def _routes(local: bool, harness: str) -> list[str]:
    """The routes it may run on, in order (a cortex's order, brain/rounds.py): its harness on this Mac's sign-in, then
    the accounts you connected for it, then the other Workers you chose, the one on this Mac last. On this Mac's model
    only that one: nothing local moves online by itself."""
    from brain import xperfect
    if on_this_mac(local):
        return [harness]
    try:
        from brain.xperfect import THINKING_TITLE, XPerfect
        return (await XPerfect(title=THINKING_TITLE).routes([harness, *xperfect.backups(harness)])) or [harness]
    except Exception:  # noqa: BLE001 (xPerfect away: its own route; the run says why if it cannot start)
        return [harness]


def _effort_on(harness: str, effort: str) -> str:
    from settings import catalog
    option = next((o for o in catalog.PARTS["hands"]["options"] if o.get("harness") == harness and o["where"] == "plan"), None)
    if option is None:
        return ""
    return effort if effort in option.get("efforts", []) else option.get("effort", "")


def _kept_item(item: dict, routine_id: str) -> dict:
    """The routine's clock entry as it was when its run began: its line is written with it even if the routine is
    switched off meanwhile."""
    return {"what": item.get("what", routine_id), "repeat": item.get("repeat", "daily"), "routine": routine_id,
            **{k: item[k] for k in ("zone", "until") if item.get(k)}}


async def run(routine_id: str, occurrence: str, think=None) -> str:
    """One night routine, start to end: "work" (done), "failed", "stopped" (the day began on this Mac's model), "off"
    (switched off before it started), or "later" (not now: it stays due and comes again). think: the run itself
    (xPerfect's, unless a test gives its own)."""
    routine = next(r for r in routines.read() if r["id"] == routine_id)
    item = next((i for i in schedules._load() if i["id"] == routine_id), {})
    held = _read(HOME / routine_id / "attempt.json")
    zone = item.get("zone", "") or (held.get("item") or {}).get("zone", "")
    night = schedules.night_of(occurrence, zone)
    other = "dreaming" if routine_id == "sleep" else "sleep"
    with schedules.exclusive():
        claim = _read(HOME / routine_id / "claim.json")
        if claim.get("process") and _alive(claim["process"]) and claim["process"].get("pid") != os.getpid():
            return "later"  # (another process runs it)
        why = f"{NAMES[other]} is running" if _holds(other) else "" if claim or _pending(held) else turn(routine_id, occurrence, zone)
        if why:  # (a run by hand, not started by the clock, takes its turn the same way)
            _status(routine_id, state="waiting", why=why, occurrence=occurrence)
            return "later"
        _write(folder(routine_id) / "claim.json", {**claim, "routine": routine_id, "occurrence": claim.get("occurrence", occurrence),
                                                    "night": night, "t": time.time(), "process": _me()})
    try:
        return await _run(routine, item, occurrence, night, think)
    finally:
        _let_go(routine_id)


def _pending(attempt: dict) -> bool:
    """Whether an attempt holds the night: its run not shown to have ended, or its finishing not done up to its history
    line (journal). Once its line is written only its files are left to tidy: that never holds the night."""
    if attempt.get("outcome") is not None:
        return not (attempt.get("finish") or {}).get("line")
    return bool(attempt.get("worker") and not attempt.get("ended"))


def resume() -> list[str]:
    """Every look of the clock (core/clock: each channel's 20 s look, and the clock with no bot): a night run whose
    process ended while its run, or its finishing, was not over is taken up again in a process of its own, whatever its
    routine's clock says (switched off, or its moment settled). The routines taken up."""
    taken = []
    for routine in NIGHT:
        held = _read(HOME / routine / "attempt.json")
        if not held.get("occurrence") or not (_pending(held) or held.get("outcome") is not None):
            continue
        with schedules.exclusive():
            claim = _read(HOME / routine / "claim.json")
            if claim.get("process") and _alive(claim["process"]):
                continue  # (its own process is at it)
            if not claim.get("process") and claim and time.time() - float(claim.get("t") or 0) < 60:
                continue  # (being started right now)
            _write(folder(routine) / "claim.json", {**claim, "routine": routine, "occurrence": held["occurrence"],
                                                     "night": held.get("night", ""), "t": time.time(), "process": {}})
        try:
            out = log_file("night.log")
            subprocess.Popen([sys.executable, "-m", "brain.night", "run", routine, held["occurrence"]], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
            taken.append(routine)
        except OSError:
            (HOME / routine / "claim.json").unlink(missing_ok=True)
    return taken


async def _run(routine: dict, item: dict, occurrence: str, night: str, think) -> str:
    routine_id, zone = routine["id"], item.get("zone", "")
    attempt_file = folder(routine_id) / "attempt.json"
    held = _read(attempt_file)
    if think is not None and held.get("worker") and not held.get("ended") and held.get("outcome") is None:
        held = {}  # (a test's own run: nothing at xPerfect to follow)
    # A run from before (its process ended: a restart, a kill; or its stop was not yet shown): followed where it ran to
    # its end before anything else starts (another Worker never runs beside it in your Life folder), and a run that
    # ended is finished, never run again.
    if held.get("worker") and not held.get("ended") and held.get("outcome") is None:
        found = await _recover(routine, held, attempt_file)
        if found is None:
            return "later"
        held = _read(attempt_file)
    if held.get("outcome") is not None:
        how = _finish(routine, held)
        if held.get("occurrence") == occurrence or not item:
            return how
        held = {}
    elif held.get("occurrence") and held.get("occurrence") != occurrence:
        schedules.waiting(routine_id, held["occurrence"], running=False)  # (its window may end now: missed, with why)
    if not item:
        _status(routine_id, state="off", occurrence=occurrence)
        return "off"
    day_file(routine_id).unlink(missing_ok=True)  # (the last run's day: never left lying about)
    if why := _busy(*place(routine)[:2]):
        _status(routine_id, state="waiting", why=why, occurrence=occurrence)
        schedules.waiting(routine_id, occurrence, why)
        return "later"
    if schedules.instant(dt.datetime.now()) >= schedules._until(item, schedules.instant(occurrence, zone)):
        why = "your day had begun"
        _status(routine_id, state="waiting", why=why, occurrence=occurrence)
        schedules.waiting(routine_id, occurrence, why)
        return "later"
    part = {**(held.get("span_kept") if held.get("occurrence") == occurrence and held.get("span_kept")
               else span(routine_id, occurrence, zone=zone)), "night": night}
    lines, words, problem = day(routine_id, part)
    if problem and routine_id == "sleep":  # (Sleep has nothing to harden without the day: failed, its day carried)
        return _failed_before(routine_id, item, occurrence, night, problem)
    if problem:  # (Dreaming wanders his Life without the day: limited, and it says so; its day stays for the next night)
        part["limited"] = "; ".join(p for p in (part.get("limited", ""), problem) if p)
        part["read_to"] = part["from"]
    kept = before(routine_id, night)
    if kept.get("failed"):  # (no Worker writes his Life without its verified copy when a night commits)
        return _failed_before(routine_id, item, occurrence, night,
                              f"the copy of your Life folder before the night could not be made whole ({kept['failed']}); nothing was run")
    if routine_id == "dreaming":
        note_file().unlink(missing_ok=True)
    _caffeinate()
    outcome = await _try_routes(routine, item, occurrence, night, part, lines, words, think,
                                held if held.get("occurrence") == occurrence else {})
    if outcome is None:
        return "later"
    return _finish(routine, _read(attempt_file))


def _failed_before(routine_id: str, item: dict, occurrence: str, night: str, why: str) -> str:
    """A night that failed before any Worker was asked: its line says why; its day goes to the next night."""
    day_file(routine_id).unlink(missing_ok=True)
    schedules.done(routine_id, occurrence, how="failed", result=why, night=night, why=why, kept=_kept_item(item, routine_id))
    _status(routine_id, state="done", how="failed", why=why, occurrence=occurrence)
    return "failed"


UI = {8866: 8880, 8876: 8890}  # (each xPerfect's own Workers page, as vx sets them: the online Workers', this Mac's)


def _workers_page(held: dict) -> str:
    """Where he stops a night's run himself: xPerfect's own Workers page for the xPerfect it ran on (its stop also stops
    the Worker). By design: never a release of Light's own, which could free a night while a Worker
    still writes his Life."""
    from urllib.parse import urlsplit
    page = os.environ.get("XPERFECT_LOCAL_UI" if held.get("local") else "XPERFECT_UI", "")
    if not page:
        try:
            where = urlsplit(held.get("api") or "")
            page = f"http://{where.hostname}:{UI[where.port]}" if where.port in UI else ""
        except ValueError:
            page = ""
    return f"xPerfect's Workers page ({page})" if page else "xPerfect's Workers page"


async def _recover(routine: dict, held: dict, attempt_file: Path) -> bool | None:
    """A run from before, followed where it ran: the xPerfect its attempt keeps, checked to be that one (address,
    state, token, principal), never today's route. On this Mac's model it gives way to a call and to your
    day, and holds this Mac awake. True once xPerfect shows its end (its outcome kept with the attempt);
    None while it cannot (the claim is kept, and its status says why and where he stops it himself: nothing else starts
    on a guess)."""
    from brain.xperfect import THINKING_TITLE, XPerfect
    routine_id = routine["id"]
    occurrence = held.get("occurrence", "")
    where = bool(held.get("local"))
    xp, why = None, ""
    try:
        xp = XPerfect(local=where, title=THINKING_TITLE)
    except (KeyError, OSError, ValueError, RuntimeError) as e:
        why = f"its run from before cannot be followed ({type(e).__name__})"
    why = why or await _not_same(held, xp)
    found = None
    if not why:
        _caffeinate()
        watch = asyncio.create_task(_watch(routine_id, occurrence, where, held, attempt_file))
        try:
            found = await _follow(xp, held, attempt_file)
        finally:
            watch.cancel()
        if found is None:
            why = f"its run from before cannot be shown to have ended ({held.get('why') or 'xPerfect does not answer'})"
    if why:
        stop = (f"to stop it yourself: {_workers_page(held)}, Worker {held.get('worker', '?')}, Stop (it stops the Worker too); "
                "once no run of it is going, Clear lets the night go")
        why += f": nothing else starts until xPerfect shows it ended; {stop}"
        _status(routine_id, state="waiting", why=why, occurrence=occurrence, worker=held.get("worker", ""))
        schedules.waiting(routine_id, occurrence, why)
        log.warning("%s: %s", routine_id, why)
        return None
    held = _read(attempt_file) or held
    if found["state"] == "none":
        _write(attempt_file, {**held, "ended": True, "why": "its Worker from before never had a run, and is closed"})
        return True
    settled = _settle(routine_id, occurrence, found, held)
    _write(attempt_file, {**held, "ended": True, **({"outcome": settled} if settled is not None else {})})
    return True


ASK_WAIT = 5.0  # s each of his xPerfects has to answer Clear's question
PLACES = (("the online Workers' xPerfect", "XPERFECT_API", "XPERFECT_STATE", "http://127.0.0.1:8866", "state-cloud"),
          ("this Mac's xPerfect", "XPERFECT_LOCAL_API", "XPERFECT_LOCAL_STATE", "http://127.0.0.1:8876", "state-local"))


async def _still_running(held: dict) -> tuple[list[str], list[str]]:
    """Where a run of the attempt's Worker may not be over, as each of his xPerfects says it: both are asked (the online
    Workers' and this Mac's, each only if it is running), failing closed: one that answers but
    cannot be asked with its credentials, whose /v1/me fails, or (the one the attempt names) that answers 404 for the
    Worker, which may hide another principal's, cannot say. (where one is going, where it could not be said)."""
    import httpx
    from brain import xperfect
    worker, named = held["worker"], held.get("api") or ""
    seen, going, unknown = set(), [], []
    for name, api_env, state_env, api, state in PLACES:
        for where, home in ((os.environ.get(api_env), os.environ.get(state_env)), (api, str(ROOT / "brain" / state))):
            if not where or where in seen:
                continue
            seen.add(where)
            try:
                xperfect._refuse_live_for_tests(where, Path(home or "."))  # (a test never asks his live ones)
            except RuntimeError:
                continue
            async with httpx.AsyncClient(base_url=where, timeout=ASK_WAIT) as probe:
                try:
                    await probe.get("/v1/me")  # (any answer at all: it is running)
                except httpx.ConnectError:
                    continue  # (nothing listens there: not running, so it runs no Worker)
                except httpx.HTTPError:
                    unknown.append(f"{name} (it does not answer)")  # (running, and failing: never taken as not running)
                    continue
            try:
                token = json.loads((Path(home or "") / "secrets.json").read_text())["api_token"]
            except (OSError, ValueError, KeyError, TypeError):
                unknown.append(f"{name} (no credentials to ask it)")
                continue
            async with httpx.AsyncClient(base_url=where, timeout=ASK_WAIT, headers={"Authorization": f"Bearer {token}"}) as client:
                try:
                    me = await client.get("/v1/me")
                    got = await client.get(f"/v1/workers/{worker}/runs") if me.status_code == 200 else None
                except httpx.HTTPError:
                    unknown.append(name)
                    continue
            if got is None:
                unknown.append(f"{name} (it would not say who asks)")
            elif got.status_code == 404:
                if where == named:  # (the Worker was made there: a 404 may be another principal's, never proof)
                    unknown.append(f"{name} (it does not show that Worker)")
            elif got.status_code != 200:
                unknown.append(name)
            elif any(run.get("state") not in ENDED for run in (got.json().get("items") or [])):
                going.append(name)
    return going, unknown


def clear(routine: str) -> dict:
    """clearing(), for a caller with no event loop of its own (python -m brain.night clear <routine>)."""
    return asyncio.run(clearing(routine))


def _held_now(routine: str, held: dict) -> str:
    """Why the attempt cannot be cleared as it is now ("" when it can): read again, its outcome saved, its run ended,
    another Worker's, or a process following it (these could change during the asking)."""
    name = NAMES.get(routine, routine)
    now = _read(HOME / routine / "attempt.json")
    if now.get("outcome") is not None:
        return f"{name}'s run ended; it is being finished, and its line comes by itself"
    if not now.get("worker") or now.get("ended"):
        return f"{name} is not held by a run"
    if now.get("worker") != held.get("worker") or now.get("run_id") != held.get("run_id"):
        return f"{name} changed meanwhile: look again"
    claim = _read(HOME / routine / "claim.json")
    if claim.get("process") and _alive(claim["process"]):
        return f"{name}'s run is being followed now"
    return ""


async def clearing(routine: str) -> dict:
    """He clears a night held by a run Light cannot confirm (the Scheduling page's Clear).
    A run Light can still follow is never cleared: normal recovery finishes it (a follower is started). For one it
    cannot, both his xPerfects are asked (each only if running) for any run of that Worker not over, failing closed:
    while one is, or one cannot say, nothing is cleared. Else, read again under the schedules' lock, only the attempt
    record goes: what the night wrote stays, nothing of it is recorded as done, and the night may run again. {"ok", "why"}."""
    from brain.xperfect import THINKING_TITLE, XPerfect
    held = _read(HOME / routine / "attempt.json")
    name = NAMES.get(routine, routine)
    if why := _held_now(routine, held):
        return {"ok": False, "why": why}
    try:  # (recovery first: where its xPerfect is still the one it ran on, the night follows the run to its end)
        followable = not await _not_same(held, XPerfect(local=bool(held.get("local")), title=THINKING_TITLE))
    except (KeyError, OSError, ValueError, RuntimeError):
        followable = False
    if followable:
        resume()
        return {"ok": False, "why": f"{name}'s run can still be followed on the xPerfect it ran on: the night follows it to "
                                    "its end (Clear is only for a run Light cannot confirm)"}
    going, unknown = await _still_running(held)
    if going:
        return {"ok": False, "why": f"a run of its Worker is still going on {going[0]}: stop it there first ({_workers_page(held)})"}
    if unknown:
        return {"ok": False, "why": f"{unknown[0]} could not say whether a run of its Worker is still going"}
    with schedules.exclusive():
        if why := _held_now(routine, held):
            return {"ok": False, "why": why}
        (HOME / routine / "attempt.json").unlink(missing_ok=True)
    why = "cleared by you: no run of its Worker is going on either xPerfect"
    if held.get("occurrence"):
        schedules.waiting(routine, held["occurrence"], why, running=False)
    _status(routine, state="cleared", why=why, occurrence=held.get("occurrence", ""))
    log.info("%s: %s (Worker %s)", routine, why, held["worker"])
    return {"ok": True, "why": why}


def _settle(routine_id: str, occurrence: str, outcome: dict, attempt: dict) -> dict | None:
    """A run's end, shown, as what is recorded: stopped for your work or a call, it comes again (None); stopped by the
    day on this Mac's model, "stopped"; else its outcome."""
    stop = _read(folder(routine_id) / "stop.json")
    if outcome.get("state") in ("interrupted", "cancelled") and stop:
        why = stop.get("why") or "it was stopped"
        if stop.get("day"):
            return {**outcome, "state": "stopped", "why": why}
        _status(routine_id, state="waiting", why=why, occurrence=occurrence)
        schedules.waiting(routine_id, occurrence, why, running=False)
        log.info("%s: stopped (%s); it comes again", routine_id, why)
        return None
    return outcome


async def _try_routes(routine, item, occurrence, night, part, lines, words, think, held) -> dict | None:
    """Its run on the first route that can take it (a route down: the next, as a cortex does). Its outcome, kept with its
    attempt (the journal's first step) once xPerfect shows its run ended; None when it must come again later (no room
    now, xPerfect away, stopped for your work or a call, or its stop not yet shown: then its claim is kept)."""
    from brain import xperfect
    from brain.xperfect import THINKING_TITLE, XPerfect
    routine_id = routine["id"]
    local, harness, effort = place(routine)
    attempt_file = folder(routine_id) / "attempt.json"
    tries = int(held.get("try") or 0)
    failed_routes = []
    order = await _routes(local, harness) if think is None else [harness]
    attempt = {}
    for token in order:
        where_local, run_harness, account = local, harness, ""
        if token == xperfect.LOCAL:
            where_local, run_harness = True, os.environ.get("WORKERS_LOCAL_PROFILE", "claude-code")
        elif token != harness or think is None:
            run_harness, account = xperfect.parts(token)
        run_effort = effort if run_harness == harness else _effort_on(run_harness, effort)
        tries += 1
        attempt = {"occurrence": occurrence, "night": night, "try": tries, "route": token, **_where(where_local),
                   "harness": run_harness, "span_kept": {k: part[k] for k in ("from", "to", "limited", "unread", "read_to") if k in part},
                   "item": _kept_item(item, routine_id), "began": time.time(), "worker": "", "run_id": "", "ended": False,
                   "pid": os.getpid()}
        _write(attempt_file, attempt)
        (folder(routine_id) / "stop.json").unlink(missing_ok=True)
        xp = XPerfect(local=where_local, title=THINKING_TITLE) if think is None else None
        if xp is not None:  # (who this client is there: a run from before is followed only where this holds)
            attempt["principal"] = await _principal(xp)
            _write(attempt_file, attempt)
        finding = []

        def started(worker: str, a=attempt, xp=xp) -> None:
            a["worker"] = worker
            _write(attempt_file, a)
            _status(routine_id, state="running", occurrence=occurrence, route=a["route"], worker=worker)
            if xp is not None:
                finding.append(asyncio.get_running_loop().create_task(_keep_run_id(xp, a, attempt_file)))

        schedules.waiting(routine_id, occurrence, running=True)
        runner = think or xp.think
        kwargs = {"wait": WAIT}
        if account and _accepts(runner, "account"):
            kwargs["account"] = account
        if _accepts(runner, "started"):
            kwargs["started"] = started
        if _accepts(runner, "role"):
            kwargs["role"] = ROLE.get(routine_id, "")
        if _accepts(runner, "owned"):
            kwargs["owned"] = True
        watch = asyncio.create_task(_watch(routine_id, occurrence, where_local, attempt, attempt_file))
        try:
            outcome, why, shown = await _attempt(runner, routine, part, lines, words, where_local, run_harness, run_effort,
                                                 kwargs, attempt, attempt_file, xp)
        finally:
            watch.cancel()
            for task in finding:
                task.cancel()
        if shown is None:  # (its run not known to have ended: its claim is kept, and it is followed again next time)
            said = (f"{why}; " if why else "") + (attempt.get("why") or "its stop is asked, and xPerfect has not shown it ended")
            _write(attempt_file, {**attempt, "why": said})
            _status(routine_id, state="waiting", why=said, occurrence=occurrence)
            schedules.waiting(routine_id, occurrence, said)  # (still running: never declared missed under it)
            log.warning("%s: %s; it comes again", routine_id, said)
            return None
        attempt["ended"] = True
        if outcome is None:  # (no room now, xPerfect away, its Worker could not start: it comes again)
            _write(attempt_file, {**attempt, "why": why})
            _status(routine_id, state="waiting", why=why, occurrence=occurrence)
            schedules.waiting(routine_id, occurrence, why, running=False)
            log.warning("%s: %s; it comes again", routine_id, why)
            return None
        settled = _settle(routine_id, occurrence, outcome, attempt)
        if settled is None:
            _write(attempt_file, attempt)
            return None
        if settled.get("state") == "failed" and settled.get("failure_class") in xperfect.ROUTE_DOWN and token != order[-1]:
            failed_routes.append(f"{token}: {settled.get('failure_class')}")
            _write(attempt_file, attempt)
            continue
        if failed_routes:
            settled = {**settled, "routes_down": failed_routes}
        _write(attempt_file, {**attempt, "outcome": settled})  # (the journal's first step: never run again)
        return settled
    final = {"state": "failed", "failure_class": "no_route", "error_text": "every route was down: " + "; ".join(failed_routes),
             "routes_down": failed_routes}
    _write(attempt_file, {**attempt, "ended": True, "outcome": final})
    return final


async def _attempt(runner, routine, part, lines, words, where_local, run_harness, run_effort, kwargs, attempt, attempt_file,
                   xp) -> tuple[dict | None, str, dict | None]:
    """One route's run, and its end as xPerfect shows it (a stop asked, a timeout, a refusal after its Worker was made
    are requests, never proof). (outcome or None, why there is none, what xPerfect showed: None when its end
    could not be shown). With no Worker made there is no run; a client that lost its run mid-way (xPerfect restarting,
    a read failing) follows it again, and never stops it."""
    outcome, why, kind = None, "", ""
    try:
        outcome = await runner(f"Routine: {routine['name']}", instruction(routine, part, lines, words, local=where_local,
                                                                          harness=run_harness),
                               run_harness, run_effort, **kwargs)
    except Exception as e:  # noqa: BLE001 (no room now, xPerfect away, a refusal: it says why and comes again)
        kind = type(e).__name__
        why = ("no Worker free now" + (f": {e.reason}" if getattr(e, "reason", "") else "")
               + (f" ({getattr(e, 'capacity_class', '')})" if getattr(e, "capacity_class", "") else "")
               if kind == "PlaceBusy" else "xPerfect cannot be reached" if kind in ("Unreachable", "ConnectError",
               "ConnectionError", "ReadTimeout", "RemoteProtocolError") else f"its Worker could not start ({str(e)[:160] or kind})")
    if not attempt["worker"] or xp is None:
        return outcome, why, {"state": "none"}  # (no Worker made, or a test's own run: nothing at xPerfect)
    if outcome is None and kind != "PlaceBusy":
        shown = await _follow(xp, attempt, attempt_file)
        if shown is not None and shown["state"] != "none":
            return shown, "", shown
        return None, why, shown
    shown = await _shown_end(xp, attempt, attempt_file)
    if shown is None or outcome is None:
        return outcome, why, shown
    if outcome.get("state") in ("timeout", "failed") and shown["state"] in ("interrupted", "cancelled"):
        return {**shown, **{k: v for k, v in outcome.items() if v}}, why, shown  # (ran out of its time, or its route went down)
    if shown["state"] in ENDED:
        return {**outcome, "state": shown["state"], "run_id": shown.get("run_id", ""),
                "usage": outcome.get("usage") or shown.get("usage")}, why, shown
    return outcome, why, shown


async def _watch(routine_id: str, occurrence: str, local: bool, attempt: dict, attempt_file: Path | None = None) -> None:
    """While its run goes on (a new one, or one followed again after a restart): on this Mac's model a call that
    begins, or the start of your day, makes it give this Mac back (one GPU serves her voice); an online one goes on."""
    if not on_this_mac(local):
        return
    from brain.xperfect import THINKING_TITLE, XPerfect
    item = next((i for i in schedules._load() if i["id"] == routine_id), {}) or attempt.get("item") or {}
    end = schedules._until({"repeat": "daily", "routine": routine_id, **item}, schedules.instant(occurrence, item.get("zone", "")))
    while True:
        await asyncio.sleep(LOOK)
        why, day_began = "", False
        if call_live():
            why = "a call began"
        elif schedules.instant(dt.datetime.now()) >= end:
            why, day_began = "your day began: it gave this Mac back", True
        if why and attempt.get("worker"):
            _write(folder(routine_id) / "stop.json", {"why": why, "day": day_began, "t": time.time()})
            attempt["asked_stop"] = attempt.get("asked_stop") or time.time()
            if attempt_file is not None:
                _write(attempt_file, attempt)
            await XPerfect(local=local, title=THINKING_TITLE).interrupt(attempt["worker"])
            return


def _line_of(routine: dict, outcome: dict, attempt: dict) -> dict:
    """What a run's history line says, worked out once, from its outcome and what it left (the journal keeps it, so a
    finish resumed after a crash writes the same line)."""
    routine_id = routine["id"]
    night = attempt.get("night", "")
    state = outcome.get("state")
    text = (outcome.get("output_text") or "").strip()
    how = "work" if state == "completed" and text else "stopped" if state == "stopped" else "failed"
    part = attempt.get("span_kept") or {}
    left = ""
    if routine_id == "dreaming" and how == "work":
        try:  # (the file it left: the line may be missing, as it was)
            left = note_file().read_text(errors="replace").strip()
        except OSError:
            left = ""
    lacks = missing(routine_id, text, left) if how == "work" else ""
    if lacks:  # (not the routine's work, whatever its run's state says: failed, and its day carried)
        how = "failed"
        outcome = {**outcome, "error_text": f"its Worker's answer was not {NAMES.get(routine_id, routine_id)}'s work ({lacks}); "
                                            f"it said: {' '.join(text.split())[:200]}"}
    handed, named = named_changes(text) if how == "work" else (text, [])
    morning = ""
    if routine_id == "dreaming" and how == "work":
        handed, morning = worth_saying(handed)
        rest, line = worth_saying(left)  # (a file may hold the line itself; then that is the one thing)
        left = (line or ("" if rest.strip(".*\"' ").lower() in ("", "nothing") else rest))[:600]
        morning = left or morning
    if how == "failed":  # (what its Worker's side said, where it said it; "unknown" alone said nothing)
        handed = (outcome.get("error_text") or outcome.get("failure_class") or state or "no answer").strip()[:400]
        if state == "timeout":
            handed = f"it ran out of its {round(WAIT / 3600, 1):g} hours; what it wrote stays; its day goes to the next night"
    elif how == "stopped":
        handed = outcome.get("why") or "stopped"
    life_changes = wrote(routine_id, night, named) if how != "failed" or attempt.get("worker") else {}
    end = part["read_to"] if part.get("read_to") is not None else part.get("to")
    extra = {"night": night, "route": attempt.get("route", ""),
             "span": [_iso(part["from"]), _iso(end)] if part.get("from") else None,
             "span_t": [part["from"], end] if part.get("from") else None,
             "limited": part.get("limited", ""), "unread": part.get("unread", ""), "life": life_changes or None,
             "routes_down": outcome.get("routes_down") or None,
             "usage": {k: v for k, v in (outcome.get("usage") or {}).items() if v} or None}  # (what its run used, as xPerfect says)
    if how != "work":
        extra["why"] = handed
    return {"how": how, "result": handed, "morning": morning, "extra": extra, "progress_to": end or time.time()}


def _finish(routine: dict, attempt: dict) -> str:
    """A run whose end xPerfect showed, finished as a journal: its outcome was kept with its attempt first;
    then, each once and resumable after a crash, its progress mark, Dreaming's note for the morning, the commit (commits
    on), its history line (also for a routine switched off meanwhile), and its files cleaned."""
    routine_id = routine["id"]
    path = folder(routine_id) / "attempt.json"
    occurrence, night = attempt["occurrence"], attempt.get("night", "")
    if "line" not in attempt:
        attempt["line"] = _line_of(routine, attempt["outcome"], attempt)
        _write(path, attempt)
    line, steps = attempt["line"], attempt.setdefault("finish", {})
    how = line["how"]
    if how == "work" and not steps.get("progress"):
        _write(folder(routine_id) / "progress.json", {"to": _iso(line["progress_to"]), "to_t": line["progress_to"], "night": night})
        steps["progress"] = True
        _write(path, attempt)
    if line.get("morning") and not steps.get("note"):
        if _note_id(_read(FOR_MORNING)) != occurrence:  # (never a second copy over one already being handed)
            keep_for_morning(line["morning"], occurrence, night)
        steps["note"] = True
        _write(path, attempt)
    committable = (line["extra"].get("life") or {}).get("committable") or []
    started = steps.get("commit") if isinstance(steps.get("commit"), dict) else None
    if how == "work" and committable and committing() and (steps.get("commit") is None or started):
        mark = (started or {}).get("mark") or secrets.token_hex(8)
        made = _committed(mark) if started else ""
        if not made:
            steps["commit"] = {"mark": mark}  # (its mark first: a crash after the commit finds it by that mark)
            _write(path, attempt)
            made = commit(routine_id, night, committable, mark=mark)
        steps["commit"] = made
        _write(path, attempt)
    if not steps.get("line"):
        made = steps.get("commit") if isinstance(steps.get("commit"), str) else ""
        extra = {**line["extra"], **({"commit": made} if made else {})}
        schedules.done(routine_id, occurrence, how=how, result=line["result"], kept=attempt.get("item") or _kept_item({}, routine_id),
                       **extra)
        steps["line"] = True
        _write(path, attempt)
    day_file(routine_id).unlink(missing_ok=True)
    note_file().unlink(missing_ok=True) if routine_id == "dreaming" else None
    path.unlink(missing_ok=True)
    _status(routine_id, state="done", how=how, occurrence=occurrence, route=attempt.get("route", ""))
    if routine_id == "sleep":
        schedules.again("dreaming")  # (its turn has come: woken at the next look, not ten minutes later)
    log.info("%s: %s; wrote %s", routine_id, how,
             {k: len(v) for k, v in ((line["extra"].get("life") or {}).items()) if isinstance(v, list)} or "nothing known")
    return how


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) == 4 and sys.argv[1] == "run" and sys.argv[2] in NIGHT:
        print(asyncio.run(run(sys.argv[2], sys.argv[3])))
    elif len(sys.argv) == 4 and sys.argv[1] == "commit" and sys.argv[2] in NIGHT:
        print(commit(sys.argv[2], sys.argv[3]) or "nothing committed")
    elif len(sys.argv) == 3 and sys.argv[1] == "clear" and sys.argv[2] in NIGHT:
        print(json.dumps(clear(sys.argv[2])))
    else:
        sys.exit("python -m brain.night run sleep|dreaming <occurrence> | commit sleep|dreaming <night> | clear sleep|dreaming")
