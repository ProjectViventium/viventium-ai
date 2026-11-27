"""Moments she set for later: reminders, check-ins, recurring work, and her own routines (the beat, the night).

Light keeps the list of what was asked (state/core/schedules.json). xPerfect keeps the time: each moment is one of
its recurring schedules (core/xclock.py), and when one comes due xPerfect sends a signed notice to Light's
doorbell (core/doorbell.py), which puts it in a small inbox here. due() hands out what arrived, once; done() says
how it ended, and that is the history the Scheduling page shows.

The backup, declared: if no notice has come RING_AFTER seconds past a moment's time (xPerfect stopped, its notice
refused), Light rings it itself. A notice that comes later for the same occurrence is ignored.

Time. A one-off is an instant: it keeps the offset it was set with, so "in two hours" is still two hours later after a
flight. A repeating moment is a time on the wall clock: "every day at 8" is 8 where this Mac is, through travel and
daylight saving, or 8 in the zone it names. Every occurrence is known by its instant (an ISO time with its offset), so a
notice that comes after this Mac changed zone is still the same occurrence. A wall time that does not exist (the hour
skipped in spring) comes the same length of time later; one that happens twice (autumn) is the first.

Windows. Past its window a moment is not rung: it is recorded as missed and leaves the inbox, also one that was
waiting there. A one-off is still worth telling for 7 days, a daily or weekday one for 12 hours, a weekly one for 3
days; a beat for 5 minutes (a beat that was missed is never made up, and never comes at night); a night routine until
the start of the person's day (its `until`: the beat's first hour), with why it did not run. A night skipped while this
Mac slept has its own line, and so has each moment taken long after its time ("late": this Mac was asleep).

Who takes it. due(now, taker): the channel the person is on takes their moments (core/jobs' one rule for where they
are, once it has one; until then, a live call), or the channel a moment names; else the always-on channel (Telegram);
with no bot and no call, a moment is shown once on this Mac and waits for the next call or chat, which wakes her with
it. The beat is the always-on channel's (on a call it passes); a night routine any always-on process starts
(brain/night.py). No scheduler runs here: every channel asks due() every 20 s.

Settling is one write: the history line first, then the list, then the inbox, so a crash in between never wakes an
occurrence again.
"""
import datetime as dt
import fcntl
import json
import os
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.state import STATE_ROOT, call_live, closed_file

FILE = STATE_ROOT / "core" / "schedules.json"
REPEATS = {"daily": 1, "weekly": 7}  # plus "weekdays"; and "every" (a built-in routine's beat: see set_routine)
WINDOW = {"": 7 * 24 * 3600, "daily": 12 * 3600, "weekdays": 12 * 3600, "weekly": 3 * 24 * 3600,  # s a late moment is still told
          "every": 300}  # (a beat that was missed is never made up: the next one comes soon)
RING_AFTER = 90  # s without xPerfect's notice before Light rings a moment itself
FIRING_RETRY = dt.timedelta(minutes=10)  # an occurrence she never finished acting on is woken again
KEPT_RUNS = 300
NIGHT = ("sleep", "dreaming")  # her night routines (brain/night.py): their window ends when the person's day begins
TAKERS = ("call", "typed", "telegram", "clock")  # who asks due(): a call, the typed chat, Telegram, the clock with no bot
ASLEEP = 300  # s between two looks at the clock (every 20 s while it runs) past which this Mac was asleep or off
_looked: float | None = None  # this process's last look (due)


def _process_started(pid) -> str:
    """When a process started, as the system says it (with its pid, it names that process and no later one)."""
    try:
        return subprocess.run(["ps", "-p", str(int(pid)), "-o", "lstart="], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return ""


def me() -> dict:
    """This process, as a claim or a telling names it."""
    return {"pid": os.getpid(), "started": _process_started(os.getpid())}


def alive(who: dict) -> bool:
    """Whether that process lives: its pid, and the same start (a pid taken again after a restart is not it)."""
    try:
        os.kill(int(who["pid"]), 0)
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return not who.get("started") or _process_started(who["pid"]) == who["started"]


def _file(kind: str) -> Path:
    """The list itself, the inbox of what came due ("due"), or what happened to each ("runs")."""
    return FILE if kind == "list" else FILE.with_name(f"{FILE.stem}-{kind}.json")


@contextmanager
def _locked(*kinds: str):
    """Read-modify-write under one file lock: a call, Telegram and the doorbell may all touch these at once.
    One kind yields its list; several yield one list each, changed and saved together, in the order given."""
    kinds = kinds or ("list",)
    with closed_file(FILE.with_suffix(".lock"), "w") as lock:  # (his alone from the start: core/state.py)
        fcntl.flock(lock, fcntl.LOCK_EX)
        held = [_load(kind) for kind in kinds]
        before = [json.dumps(items) for items in held]
        yield held[0] if len(held) == 1 else held
        for kind, items, was in zip(kinds, held, before):
            if json.dumps(items) != was:
                tmp = _file(kind).with_suffix(".tmp")
                with closed_file(tmp, "w") as out:
                    out.write(json.dumps(items, indent=1))
                tmp.replace(_file(kind))


@contextmanager
def exclusive():
    """The schedules' own lock, held for a decision that must not race (brain/night.py: whose turn the night is)."""
    with closed_file(FILE.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _load(kind: str = "list") -> list[dict]:
    path = _file(kind)
    return json.loads(path.read_text()) if path.exists() else []


# -- time --

def _zone(name: str):
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def instant(when, zone: str = "") -> dt.datetime:
    """A moment as its exact instant (aware, UTC). A time with an offset is that instant; a wall time is read in its
    zone, or in this Mac's zone now (a missing hour moves forward by the gap; a repeated one is its first)."""
    if isinstance(when, str):
        when = dt.datetime.fromisoformat(when)
    if when.tzinfo is None:
        place = _zone(zone)
        when = when.replace(tzinfo=place) if place else when.astimezone()
    return when.astimezone(dt.timezone.utc)


def stamp(at: dt.datetime, zone: str = "") -> str:
    """An instant as the person reads it (in its zone, else this Mac's), with its offset: how an occurrence is known."""
    place = _zone(zone)
    return (at.astimezone(place) if place else at.astimezone()).isoformat(timespec="seconds")


def same(a: str, b: str, zone: str = "") -> bool:
    """Whether two occurrences are one instant (an old record without an offset reads as this Mac's time)."""
    try:
        return abs((instant(a, zone) - instant(b, zone)).total_seconds()) < 1
    except (TypeError, ValueError):
        return a == b


def local(when: dt.datetime) -> dt.datetime:
    """This Mac's local time, naive (a time given with an offset is converted, never compared raw)."""
    return when.astimezone().replace(tzinfo=None) if when.tzinfo else when


def _wall(item: dict, when: str | None = None) -> dt.datetime:
    """A moment's time as the wall clock reads it where it is kept (its zone, else this Mac's), naive."""
    w = dt.datetime.fromisoformat(when or item["when"])
    if w.tzinfo is not None:
        place = _zone(item.get("zone", ""))
        w = (w.astimezone(place) if place else w.astimezone()).replace(tzinfo=None)
    return w


def _at(item: dict, wall: dt.datetime | None = None) -> dt.datetime:
    """When a moment (or one of its turns, as a wall time) comes, as an instant."""
    return instant(wall if wall is not None else item["when"], item.get("zone", ""))


def night_of(occurrence: str, zone: str = "") -> str:
    """Which night an occurrence of a night routine belongs to: the date of its evening (noon to noon), whatever its
    time on the clock, so Sleep at 23:30 and Dreaming at 00:30 are one night, and Dreaming set before Sleep still
    comes after the Sleep of its own night."""
    at = instant(occurrence, zone)
    place = _zone(zone)
    wall = (at.astimezone(place) if place else at.astimezone()).replace(tzinfo=None)
    return (wall - dt.timedelta(hours=12)).date().isoformat()


def _until(item: dict, at: dt.datetime) -> dt.datetime:
    """The end of an occurrence's window: a night routine's is the start of the person's day after it."""
    if item.get("routine") in NIGHT and item.get("until"):
        place = _zone(item.get("zone", ""))
        wall = (at.astimezone(place) if place else at.astimezone()).replace(tzinfo=None)
        end = dt.datetime.combine(wall.date(), _clock_time(item["until"]))
        if end <= wall:
            end += dt.timedelta(days=1)
        return _at(item, end)
    return at + dt.timedelta(seconds=WINDOW[item["repeat"]])


def _booted() -> float:
    """When this Mac last started (seconds since the epoch; 0 when it cannot say)."""
    try:
        said = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
        return float(said.split("sec = ")[1].split(",")[0])
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def _asleep(gap: float | None) -> str:
    """Why a look comes long after the one before it (no look for over ASLEEP seconds): the Mac slept, or restarted."""
    if gap is None or gap <= ASLEEP:
        return ""
    import time
    booted = _booted()
    return "this Mac was restarted" if booted and time.time() - booted < gap else "this Mac was asleep"


# -- the list --

def _clock():
    """xPerfect's side (core/xclock.py), or None where it is off: a test's own state, or no xPerfect at all."""
    from core import xclock
    return xclock if xclock.on() else None


def _tell_clock(action: str, *args) -> None:
    """Best effort, never in the way: what xPerfect did not hear now, the doorbell's next look puts right."""
    clock = _clock()
    if clock is None:
        return
    try:
        getattr(clock, action)(*args)
    except Exception:
        pass


def add(when: dt.datetime, what: str, repeat: str = "", zone: str = "", to: str = "") -> dict:
    """A moment to keep. A one-off keeps its instant (the offset it was set with); a repeating one is a wall-clock
    time, where this Mac is or in `zone`. to: the channel it was asked for (one of TAKERS), when it names one."""
    repeat = repeat if repeat in (*REPEATS, "weekdays") else ""
    zone = zone if _zone(zone) else ""
    if repeat:
        wall = (when.astimezone(_zone(zone)).replace(tzinfo=None) if zone else local(when)) if when.tzinfo else when
        kept = wall.isoformat(timespec="seconds")
    else:
        kept = stamp(instant(when, zone), zone)
    item = {"id": uuid.uuid4().hex[:6], "when": kept, "what": what, "repeat": repeat,
            "set": dt.datetime.now().isoformat(timespec="seconds"),
            **({"zone": zone} if zone else {}), **({"to": to} if to in TAKERS else {})}
    with _locked() as items:
        items.append(item)
    _tell_clock("push", item)
    return item


def cancel(schedule_id: str) -> bool:
    """A moment she was asked to keep, removed. (A built-in routine is not one of those: set_routine switches it.)"""
    with _locked("list", "due") as (items, inbox):
        kept = [i for i in items if i["id"] != schedule_id or i.get("routine")]
        found = len(kept) < len(items)
        items[:] = kept
        if found:
            inbox[:] = [e for e in inbox if e["id"] != schedule_id]
    if found:
        _tell_clock("retire", schedule_id)
    return found


def pause(schedule_id: str, paused: bool = True) -> bool:
    """A paused moment stays, and does not come due (nor does one already waiting in the inbox). Resumed, a repeating
    one takes up at its next time (never a burst of the ones it slept through)."""
    changed = None
    with _locked("list", "due") as (items, inbox):
        for item in items:
            if item["id"] != schedule_id:
                continue
            if paused:
                item["paused"] = True
                inbox[:] = [e for e in inbox if e["id"] != schedule_id]
            else:
                item.pop("paused", None)
                if item["repeat"]:
                    wall, now = _wall(item), _wall(item, stamp(instant(dt.datetime.now())))
                    while wall <= now:
                        wall = _next(wall, item)
                    item["when"] = wall.isoformat(timespec="seconds")
            changed = dict(item)
    if changed is not None:
        _tell_clock("push", changed)
    return changed is not None


def upcoming(routines: bool = False) -> list[dict]:
    """The moments she was asked to keep, soonest first (routines: her own built-in ones too). A one-off's `when` is
    read as this Mac's local time now (its instant is `at`); a repeating one's is its wall time."""
    out = []
    for item in _load():
        if not routines and item.get("routine"):
            continue
        at = _at(item)
        shown = dict(item, at=stamp(at, item.get("zone", "")))
        if not item["repeat"]:
            shown["when"] = local(at).isoformat(timespec="seconds")
        out.append(shown)
    return sorted(out, key=lambda i: instant(i["at"]))


def _clock_time(text: str) -> dt.time:
    return dt.time(*map(int, text.split(":")))


def _next(when: dt.datetime, item: dict) -> dt.datetime:
    """A repeating moment's turn after `when` (wall times). A beat ("every") comes every so many minutes from the
    start of the awake hours to their end, and then waits for the next day's start."""
    if item["repeat"] == "every":
        start, end = _clock_time(item["from"]), _clock_time(item["to"])
        when += dt.timedelta(minutes=item["every"])
        if when.time() > end or when.time() < start:
            when = dt.datetime.combine(when.date() + dt.timedelta(days=when.time() > end), start)
        return when
    step = dt.timedelta(days=REPEATS.get(item["repeat"], 1))
    when += step
    while item["repeat"] == "weekdays" and when.weekday() >= 5:
        when += step
    return when


def set_routine(name: str, on: bool, every: int = 30, awake_from: str = "08:00", awake_to: str = "22:00",
                at: str = "", until: str = "") -> dict | None:
    """One of her own built-in routines, kept as set, or gone when it is switched off: one that comes round while you
    are awake (the heartbeat: its pace and hours; its next beat the next one on its grid, never one that has passed),
    or, with `at`, one that comes every night at that time (sleep, dreaming: brain/night.py), whose window ends at
    `until` (the start of your day)."""
    made = None
    with _locked("list", "due") as (items, inbox):
        have = next((i for i in items if i["id"] == name), None)
        if not on:
            if have is None:
                return None
            items.remove(have)
            inbox[:] = [e for e in inbox if e["id"] != name]
        else:
            want = ({"repeat": "daily", "at": at, **({"until": until} if until else {})} if at else
                    {"repeat": "every", "every": int(every), "from": awake_from, "to": awake_to})
            if have is not None and all(have.get(k) == v for k, v in want.items()) and (not at or have.get("until", "") == until):
                return have
            now = dt.datetime.now()
            item = {"id": name, "routine": name, "what": name, "set": now.isoformat(timespec="seconds"), **want}
            if at:  # tonight at that time, or tomorrow night once it has passed
                beat = dt.datetime.combine(now.date(), _clock_time(at))
                if beat <= now:
                    beat += dt.timedelta(days=1)
                if have is not None and have.get("at") == at:  # (only its end changed: its turn stays)
                    beat = _wall(have)
            else:
                # (from one turn before today's first beat: always at least one turn, so set before the awake hours, as
                # after midnight, its next beat is their start, never the turn before it; 01:00 once gave 07:30)
                beat = _next(dt.datetime.combine(now.date(), _clock_time(awake_from)) - dt.timedelta(minutes=item["every"]), item)
                while beat <= now:
                    beat = _next(beat, item)
            item["when"] = beat.isoformat(timespec="seconds")
            if have is not None:
                items.remove(have)
            items.append(item)
            made = item
    if made is None:
        _tell_clock("retire", name)
    else:
        _tell_clock("push", made)
    return made


def _settled(item_id: str, occurrence: str, runs: list[dict] | None = None) -> bool:
    return any(r["id"] == item_id and same(r.get("due_at") or r["due"], occurrence) for r in (runs if runs is not None else _load("runs")))


def awake(item: dict, at: dt.datetime) -> bool:
    """Whether `at` is inside a beat's awake hours, its last beat (at `to`) included, read on its own wall clock (a beat
    drained after its hour, the Mac asleep at 22:00 and awake at 22:04, is never run at night)."""
    if item.get("repeat") != "every" or not item.get("from") or not item.get("to"):
        return True
    place = _zone(item.get("zone", ""))
    wall = (at.astimezone(place) if place else local(at)) if at.tzinfo else at
    minute = wall.hour * 60 + wall.minute + wall.second / 60
    first, last = _clock_time(item["from"]), _clock_time(item["to"])
    start, end = first.hour * 60 + first.minute, last.hour * 60 + last.minute + 1  # (its last beat, within its minute)
    return start <= minute < end if start < end else minute >= start or minute < end  # (or awake across midnight)


def _turn_near(item: dict, at: dt.datetime) -> dt.datetime | None:
    """The turn of a moment that a notice for `at` is: its own current turn, or a later one it has not reached yet,
    within 90 s of `at`; None when the notice is for no turn of it (before its time, or another time)."""
    if not item["repeat"]:
        mine = _at(item)
        return mine if abs((mine - at).total_seconds()) <= 90 else None
    wall = _wall(item)
    if (_at(item, wall) - at).total_seconds() > 90:  # never before its own time (xPerfect keeps a time of day)
        return None
    while (_at(item, nxt := _next(wall, item)) - at).total_seconds() <= 90:
        wall = nxt
    mine = _at(item, wall)
    return mine if abs((mine - at).total_seconds()) <= 90 else None


def arrived(schedule_id: str, scheduled_at: dt.datetime, occurrence_id: str = "") -> bool:
    """xPerfect's notice that a moment has come (the doorbell calls this, after checking who sent it). Kept
    before the doorbell answers, so a notice is never lost; the same occurrence is kept once. False when it is
    not ours to keep (removed, paused, already acted on, or for another time: xPerfect keeps a repeating moment by
    its time of day, so it can ring before the first one; and after this Mac changed zone it rings the old
    zone's time until it is made again, core/xclock.py)."""
    at = instant(scheduled_at)
    item = next((i for i in _load() if i["id"] == schedule_id), None)
    if item is None or item.get("paused"):
        return False
    mine = _turn_near(item, at)
    if mine is None:
        return False
    occurrence = stamp(mine, item.get("zone", ""))
    if _settled(schedule_id, occurrence):
        return False
    with _locked("due") as inbox:
        if any(e["id"] == schedule_id and same(e["occurrence"], occurrence) for e in inbox):
            return False
        inbox.append({"id": schedule_id, "occurrence": occurrence, "occurrence_id": occurrence_id, "by": "xperfect",
                      "received": dt.datetime.now().astimezone().isoformat(timespec="seconds")})
    return True


def _note(run: dict) -> None:
    with _locked("runs") as runs:
        runs.append(run)
        del runs[:-KEPT_RUNS]


def where() -> str | None:
    """The channel the person is on now: core/jobs' one rule for it (a call with them in it, else a typed
    chat around their turns, else Telegram), and until it has one, a live call. None: the always-on channel."""
    from core import jobs
    rule = getattr(jobs, "present", None)
    if callable(rule):
        try:
            return rule() or None
        except Exception:  # noqa: BLE001 (never a lost reminder because the rule failed)
            pass
    return "call" if call_live() else None


def _takes(item: dict, taker: str | None, here: str | None) -> bool:
    """Whether this taker wakes her with this moment now. A moment that names a channel goes there; else the
    channel the person is on; else the always-on one. Her own routines are the always-on process's."""
    if taker is None:
        return True  # (a caller from before: everything, as before)
    if item.get("routine"):
        return taker in ("telegram", "clock")
    if named := item.get("to"):
        return taker == named or (taker == "clock" and named == "telegram")
    if here in ("call", "typed"):  # (without core/jobs' rule a live call is all that is known: either live chat takes it)
        from core import jobs
        return taker == here or (taker in ("call", "typed") and not callable(getattr(jobs, "present", None)))
    return taker in ("telegram", "clock")


def _off_why(at: dt.datetime) -> str:
    """Why a moment found no look at its time when this process had made none before it: this Mac started after it."""
    if not (seconds := _booted()):
        return ""
    booted = dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    return f"this Mac was off until {local(booted).strftime('%H:%M')}" if booted > at else ""


def _line(item: dict, occurrence: str, how: str, now: dt.datetime, why: str = "", by: str = "") -> dict:
    """One line of history. `due` reads as this Mac's time when it was written (as the page shows it); `due_at` is the
    occurrence's instant, with its offset (how it is known: core/schedules' top)."""
    at = instant(occurrence, item.get("zone", ""))
    return {"id": item["id"], "what": item["what"], "repeat": item["repeat"], "due": local(at).isoformat(timespec="seconds"),
            "due_at": stamp(at, item.get("zone", "")), "at": now.isoformat(timespec="seconds"), "how": how, "by": by,
            **({"routine": item["routine"]} if item.get("routine") else {}),
            **({"night": night_of(occurrence, item.get("zone", ""))} if item.get("routine") in NIGHT else {}),
            **({"why": why} if why else {})}


def due(now: dt.datetime, taker: str | None = None) -> list[dict]:
    """Moments that have come, each with its `occurrence`: what xPerfect's notice brought, and what Light rings
    itself because no notice came (see the top). They stay in the inbox, marked firing, until done() (her wake-up
    reply finished, even a no_reply): a restart or a busy moment never loses one, and an occurrence never finished
    is woken again after FIRING_RETRY, if it is still inside its window. Taken under the lock: once per moment.
    taker: who asks (TAKERS; see the top). The clock with no bot gets a moment of the person's once, to show it on
    this Mac (`notify_only`); it waits for a call or chat."""
    global _looked
    now_at = instant(now)
    import time as _time
    seen = _time.time()
    first = _looked is None
    late_why = _asleep(seen - _looked if _looked is not None else None)
    _looked = seen
    now_local = local(now_at)
    wait = dt.timedelta(seconds=RING_AFTER if _clock() is not None else 0)
    here = where() if taker is not None else None
    fired, missed = [], []
    with _locked("runs", "list", "due") as (runs, items, inbox):
        by_id = {i["id"]: i for i in items}
        for item in list(items):
            if item.get("paused"):
                continue
            zone = item.get("zone", "")
            if item["repeat"]:
                wall = _wall(item)
                if _at(item, wall) > now_at:
                    continue
                while _at(item, nxt := _next(wall, item)) <= now_at:  # only its latest turn counts (as xPerfect: coalesce)
                    skipped = stamp(_at(item, wall), zone)
                    if item.get("routine") in NIGHT and not _settled(item["id"], skipped, runs) \
                            and not any(e["id"] == item["id"] and same(e["occurrence"], skipped) for e in inbox):
                        missed.append(_line(item, skipped, "missed", now_local, late_why or (first and _off_why(_at(item, wall)))
                                            or "it was not run that night"))
                    wall = nxt
                item["when"] = wall.isoformat(timespec="seconds")
                at = _at(item, wall)
            else:
                at = _at(item)
                if at > now_at:
                    continue
            occurrence = stamp(at, zone)
            if any(e["id"] == item["id"] and same(e["occurrence"], occurrence) for e in inbox):
                continue
            if _settled(item["id"], occurrence, runs):  # (its line was written, the list not yet put right: a crash between)
                _past(item, items, now_at)
                continue
            if now_at > _until(item, at):  # too late to be worth telling: missed
                if item["repeat"] != "every":  # (a beat that was missed leaves no line: only what it did is its history)
                    missed.append(_line(item, occurrence, "missed", now_local,
                                        late_why or (first and _off_why(at)) or
                                        ("it found no moment before your day began" if item.get("routine") in NIGHT else "")))
                if item["repeat"]:
                    wall = _wall(item)
                    while _at(item, wall) <= now_at:
                        wall = _next(wall, item)
                    item["when"] = wall.isoformat(timespec="seconds")
                else:
                    items.remove(item)
            elif now_at - at >= wait:  # no notice came: Light rings it itself
                inbox.append({"id": item["id"], "occurrence": occurrence, "occurrence_id": "", "by": "light",
                              "received": now_local.astimezone().isoformat(timespec="seconds"),
                              **({"late": late_why} if late_why and (now_at - at).total_seconds() > ASLEEP else {})})
        for entry in list(inbox):
            item = by_id.get(entry["id"])
            if item is None or item not in items or item.get("paused"):
                inbox.remove(entry)
                continue
            if _settled(entry["id"], entry["occurrence"], runs):  # (settled already: its line was written before a crash)
                inbox.remove(entry)
                if not any(e["id"] == item["id"] for e in inbox):
                    _past(item, items, now_at)
                continue
            if by := entry.get("presenting"):  # (a telling under way: never sent twice, never missed under it)
                if alive(by):
                    continue
                how, why = _after_crash(item, entry)
                missed.append(_line(item, entry["occurrence"], how, now_local, why, entry.get("by", "")))
                inbox.remove(entry)
                if not any(e["id"] == item["id"] for e in inbox):
                    _past(item, items, now_at)
                continue
            at = instant(entry["occurrence"], item.get("zone", ""))
            if late_why and "late" not in entry and (now_at - at).total_seconds() > ASLEEP and not entry.get("firing_at"):
                entry["late"] = late_why
            if now_at > _until(item, at) and not entry.get("running"):  # its window ended while it waited
                if item["repeat"] != "every":
                    missed.append(_line(item, entry["occurrence"], "missed", now_local,
                                        entry.get("waiting") or entry.get("late") or
                                        ("no call or chat was open" if entry.get("shown") else "") or
                                        ("it found no moment before your day began" if item.get("routine") in NIGHT else ""),
                                        entry.get("by", "")))
                inbox.remove(entry)
                if not item["repeat"]:
                    items.remove(item)
                continue
            if item["repeat"] == "every" and not awake(item, now_at):  # (a beat drained after its hour: never at night)
                inbox.remove(entry)
                _past(item, items, now_at)
                continue
            if not _takes(item, taker, here):
                continue
            if taker == "clock" and not item.get("routine"):  # no channel: shown once on this Mac, it waits for one
                if not entry.get("shown") and not entry.get("firing_at"):
                    entry["shown"] = now_local.isoformat(timespec="seconds")
                    fired.append({**item, "occurrence": entry["occurrence"], "notify_only": True})
                continue
            started = entry.get("firing_at")
            if started and now_local - local(dt.datetime.fromisoformat(started)) < FIRING_RETRY:
                continue
            entry.update(firing_at=now_local.isoformat(timespec="seconds"), taker=taker or "", pid=os.getpid())
            fired.append({**item, "occurrence": entry["occurrence"], **({"late": entry["late"]} if entry.get("late") else {})})
        runs.extend(missed)
        del runs[:-KEPT_RUNS]
    for run in missed:
        if not run["repeat"]:
            _tell_clock("retire", run["id"])
    return fired


def _after_crash(item: dict, entry: dict) -> tuple[str, str]:
    """A moment whose telling was under way when its process ended: work accepted for it (the hand-off keeps the moment
    with its job) settles it as work; else whether it reached them is not known, and it is never sent again by itself."""
    from core import jobs
    if any(j.get("schedule") == item["id"] and same(str(j.get("occurrence", "")), entry["occurrence"], item.get("zone", ""))
           for j in jobs.open_jobs()):
        return "work", ""
    return "unknown", "its telling was under way when Viventium stopped: whether it reached you is not known"


def presenting(schedule_id: str, occurrence: str, on: bool = True) -> bool:
    """A moment's telling is about to go out (on: written before anything is sent, with the process sending it), or
    went nowhere (off). After a crash in between it is settled from what is known, else "unknown", never sent again.
    False when it is not this process's to present: settled, gone, or another live process presents it."""
    with _locked("runs", "due") as (runs, inbox):
        entry = next((e for e in inbox if e["id"] == schedule_id and same(e["occurrence"], occurrence)), None)
        if entry is None or _settled(schedule_id, occurrence, runs):
            return False
        if not on:
            entry.pop("presenting", None)
            return True
        by = entry.get("presenting")
        if by and by.get("pid") != os.getpid() and alive(by):
            return False
        entry["presenting"] = {**me(), "at": dt.datetime.now().isoformat(timespec="seconds")}
    return True


TRIES = 3  # a moment whose work could not start is tried this many times, then failed with why


def retry(schedule_id: str, occurrence: str, why: str, now: dt.datetime | None = None) -> bool:
    """A moment whose work could not start (no accepted job): tried again after FIRING_RETRY, at
    most TRIES times in all, then failed with why. Whether it will be tried again."""
    with _locked("due") as inbox:
        entry = next((e for e in inbox if e["id"] == schedule_id and same(e["occurrence"], occurrence)), None)
        if entry is None:
            return False
        entry.pop("presenting", None)
        entry["tries"] = int(entry.get("tries") or 0) + 1
        entry["waiting"] = why
        again_ = entry["tries"] < TRIES
    if not again_:
        done(schedule_id, occurrence, now, "failed", why=f"{why} ({TRIES} tries)")
    return again_


def _past(item: dict, items: list[dict], now_at: dt.datetime) -> None:
    """A moment whose turn is settled: a one-off leaves the list, a repeating one moves to its next turn after now."""
    if not item["repeat"]:
        if item in items:
            items.remove(item)
        return
    wall = _wall(item)
    while _at(item, wall) <= now_at:
        wall = _next(wall, item)
    item["when"] = wall.isoformat(timespec="seconds")


def again(schedule_id: str, occurrence: str = "") -> None:
    """Wake this occurrence again at the next look, not after FIRING_RETRY: talked over, a call that hung up before
    she said it, or a night routine whose turn has come (Sleep ended)."""
    with _locked("due") as inbox:
        for e in inbox:
            if e["id"] == schedule_id and (not occurrence or same(e["occurrence"], occurrence)):
                e.pop("firing_at", None)


def release(taker: str, pid: int | None = None) -> int:
    """A channel that took moments is gone (a call hung up): what it had not finished is woken again at once by
    whoever is there. How many were released."""
    count = 0
    with _locked("due") as inbox:
        for e in inbox:
            if e.get("firing_at") and e.get("taker") == taker and (pid is None or e.get("pid") == pid):
                e.pop("firing_at", None)
                count += 1
    return count


def waiting(schedule_id: str, occurrence: str, why: str = "", running: bool | None = None) -> None:
    """Why an occurrence waits (its missed line says so if its window ends), and whether its run is going now (a run
    going is never declared missed under it)."""
    with _locked("due") as inbox:
        for e in inbox:
            if e["id"] == schedule_id and same(e["occurrence"], occurrence):
                if why:
                    e["waiting"] = why
                if running is not None:
                    e["running"] = running


def done(schedule_id: str, occurrence: str, now: dt.datetime | None = None, how: str = "", result: str = "",
         kept: dict | None = None, **extra) -> None:
    """This occurrence was acted on, and how it ended (told, quiet, work, owed, failed, ...): a one-off leaves, a
    repeat moves to its next time after now (so a Mac that was off for three days is reminded once, not three
    times). result: what a night routine handed back, for its history line; extra: more of its line (why, night).
    kept: the moment as it was when its run began (a night routine): its line is written even if it was switched off
    or moved meanwhile. Once per occurrence; one write (the line first)."""
    now = local(instant(now or dt.datetime.now()))
    retire = False
    with _locked("runs", "list", "due") as (runs, items, inbox):
        entry = next((e for e in inbox if e["id"] == schedule_id and same(e["occurrence"], occurrence)), None)
        if entry is not None:
            inbox.remove(entry)
        item = next((i for i in items if i["id"] == schedule_id), None)
        if _settled(schedule_id, occurrence, runs) or (item is None and not kept):
            return
        zone = (item or kept).get("zone", "")
        if item is None or entry is None and not same(stamp(_at(item), zone), occurrence, zone):
            if not kept:
                return  # (not one of its turns that came: nothing to settle)
            line = _line({**kept, "id": schedule_id}, occurrence, how, now, by=(entry or {}).get("by", ""))
            line.update({k: v for k, v in extra.items() if v not in (None, "")})
            if result:
                line["result"] = result[:1200]
            runs.append(line)
            del runs[:-KEPT_RUNS]
            return
        if not item["repeat"]:
            items.remove(item)
            retire = True
        else:
            wall = _wall(item)
            past = max(instant(now), instant(occurrence, zone))  # (this turn is over, whatever the clocks say)
            while _at(item, wall) <= past:
                wall = _next(wall, item)
            item["when"] = wall.isoformat(timespec="seconds")
        line = _line(item, occurrence, how, now, by=(entry or {}).get("by", ""))
        line.update({k: v for k, v in extra.items() if v not in (None, "")})
        if result:
            line["result"] = result[:1200]
        if (entry or {}).get("late"):
            line.setdefault("late", entry["late"])
        runs.append(line)
        del runs[:-KEPT_RUNS]
    if retire:
        _tell_clock("retire", schedule_id)


def annotate(schedule_id: str, occurrence: str, **fields) -> bool:
    """More on one occurrence's history line, later (Dreaming's note: told, kept, or still waiting in the morning)."""
    with _locked("runs") as runs:
        for run in reversed(runs):
            if run["id"] == schedule_id and same(run.get("due_at") or run["due"], occurrence):
                run.update(fields)
                return True
    return False


def inbox(schedule_id: str | None = None) -> list[dict]:
    """What is waiting in the inbox now (one moment's, or all)."""
    return [e for e in _load("due") if schedule_id is None or e["id"] == schedule_id]


def runs(schedule_id: str | None = None, limit: int = 20) -> list[dict]:
    """What happened to each moment that came, newest first: one moment's, or (None) those of moments that are gone
    (a one-off leaves when it has come; its line stays here)."""
    live = {i["id"] for i in _load()}
    kept = [r for r in _load("runs") if (r["id"] == schedule_id if schedule_id else r["id"] not in live and not r.get("routine"))]
    return list(reversed(kept))[:limit]


if __name__ == "__main__":  # python -m core.schedules: what is set, and what xPerfect has for it
    print(json.dumps({"set": upcoming(True), "clock": "xperfect" if _clock() else "light"}, indent=1))
    if os.environ.get("XPERFECT_API") and _clock():
        from core import xclock
        print(json.dumps(xclock.sync(upcoming(True)), indent=1))
