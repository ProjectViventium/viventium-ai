"""What Viventium does by itself on the clock: continuous awareness while you are awake, sleep and dreaming at night.

Each routine is plain text in brain/routines/: a few facts on top (its time, who runs it), then the words it is
told when it wakes. What you change on the Scheduling page is kept in her state (state/scheduling.json), only
where it differs. ensure() makes the clock match: the beat, on the same clock as your reminders, and sleep and
dreaming, each a moment every night at its time (core/schedules.set_routine; brain/night.py runs them); a night time
inside your day is not put on the clock, and its status says why.

A beat (beat(), called by the conscious mind when its moment comes: Queen.wake) is the same mind looking up. Where
her mind decides its own tools and is the one answering (a per-mind flag; GPT-6.1 Sol, measured), it is
one turn of hers, with her instructions, her conversation and her tools: she does as the heartbeat's words say (she comes
alive, looks around, then says what she likes, starts work with hand_off_to, or lets the moment pass with no_reply and
why). The beat runs on the conscious mind itself, so there is one voice, never a second one beside hers.
Work counts as started only by its accepted job's receipt (accepted()).
Where her mind needs a separate decision, its own native enum tool decides first
(brain/modes/heartbeat_gate.md), through the configured mind. Unsupported routes declare the old word fallback.
On "act" nothing is said, and no work starts: the
beat is recorded as what it is ("act": the look chose to act, nothing was started), never quiet and never work. Work
in her place with his exact words (a second question names which, on the whole conversation; her few words about it
kept as said) is there only where it is switched on (BEAT_LOCAL_ACT=on): on qwen3.6 neither wording told her own
promise from her unanswered offer, so on this Mac's model her promises are not yet
acted on by a look, and the Scheduling page says so. On this Mac's model the first look after a night with Dreaming's
note says that note with its own words (NOTE_SAY: the thought itself, as a statement), and that is the look, with no
question before it (Dreaming chose it as worth saying; the say-or-keep question kept it 10 of 10). On both minds the
note waits for a quiet moment (his last words NOTE_PAUSE or more ago). A beat that could not decide or speak, or whose
one word is none of its declared answers, is "failed" with why, never quiet; one that waited past your awake hours, or
whose call left Talk, passes: every wait is checked again before a reply starts.

What a beat sees, as facts (what to make of them is hers): the time, when each of you last spoke, work running, what
is coming, what her earlier beats today did and how each ended (any words a beat delivered show as reaching out,
whatever the beat was recorded as), and the work her looks started before today, for what it was asked, with how
often and how it ended (from each job's own record, kept on the beat's line: a promise renewed after midnight, or
days later, is not new). So a promise retried and failed again is told once,
not retried every half hour (else dozens of jobs a day, and as many failure messages). On the first
beat after a night: how the night went, and Dreaming's one thing worth saying, which stays in her context, once, as
her own thought whatever she does with it; it is presented with its own identity (brain/night.presenting), so a beat
that ends mid-way never tells it twice.
"""
import asyncio
import contextvars
import dataclasses
import datetime as dt
import json
import logging
import os
import re
import time
import weakref

from core import cards

HOME = cards.BRAIN / "routines"
PAGE = "scheduling"
ORDER = ("heartbeat", "sleep", "dreaming")
RUNS = ORDER  # (every one of them runs)
FIELDS = ("on", "every_minutes", "awake_from", "awake_to", "at", "runs_on", "effort", "prompt")
BEAT_WAIT = 20.0  # s a beat's one word may take on this Mac (it runs in the background; one once ran out in 3 s)
log = logging.getLogger("routines")


def _routine(name: str) -> dict:
    facts, prompt = cards.read(HOME / f"{name}.md")
    out = {"id": name, "name": facts["name"], "region": facts.get("region", ""), "does": facts.get("does", ""),
           "sign": facts.get("sign", "clock"), "on": facts.get("on", True), "runs_on": facts.get("runs_on", "mind"),
           "effort": facts.get("effort", ""), "prompt": prompt, "running": name in RUNS}
    if "every_minutes" in facts:
        out.update(every_minutes=int(facts["every_minutes"]), awake_from=facts["awake_from"], awake_to=facts["awake_to"])
    else:
        out["at"] = facts["at"]
    return out


def defaults() -> list[dict]:
    return [_routine(name) for name in ORDER]


def read() -> list[dict]:
    """Every routine as it is set now: what came with Light, with what you changed."""
    saved = cards.kept(PAGE).get("builtin", {})
    return [{**r, **{f: v for f, v in saved.get(r["id"], {}).items() if f in FIELDS}} for r in defaults()]


def words(name: str) -> str:
    """What a routine is told when it wakes."""
    return next(r["prompt"] for r in read() if r["id"] == name)


def inside_day(at: str, day_from: str, day_to: str) -> str:
    """Why a night routine may not be set at `at` ("" when it may): a time inside your day (from the beat's first hour
    to its last), where its window would run on into the next day's start (Sleep at 10:00 with the day from
    8:00 would have run all day)."""
    from core import schedules
    if not (at and day_from and day_to):
        return ""
    t, first, last = (schedules._clock_time(x) for x in (at, day_from, day_to))
    inside = first <= t < last if first < last else t >= first or t < last
    return (f"{at} is inside your day ({day_from} to {day_to}): a night routine runs between {day_to} and {day_from}, "
            "so it is not on the clock until its time is set there") if inside else ""


def ensure() -> None:
    """The clock, as the routines are set: the heartbeat's beat with its pace and hours, sleep and dreaming at their
    time each night, each night's window ending when your day begins (the beat's first hour); none for one that is
    off, nor for a night time inside your day (said in that routine's status, brain/night.py)."""
    from core import schedules
    every = read()
    beat = next((r for r in every if "awake_from" in r), {})
    day = beat.get("awake_from", "")
    for routine in every:
        if "every_minutes" in routine:  # (the clock's short tick; her own pace is decided at each beat: TICK)
            schedules.set_routine(routine["id"], bool(routine["on"]), TICK, routine["awake_from"], routine["awake_to"])
            continue
        why = inside_day(routine["at"], day, beat.get("awake_to", "")) if routine["on"] else ""
        schedules.set_routine(routine["id"], bool(routine["on"]) and not why, at=routine["at"], until=day)
        from brain import night
        held = night.status(routine["id"])
        if why and held.get("why") != why:
            night._status(routine["id"], state="refused", why=why)
        elif not why and held.get("state") == "refused":
            night._status(routine["id"], state="set", why="")


# -- a beat --

# What a beat's own turn is told last, after the heartbeat's words and what she can see (the choice is hers).
TURN = ("This is not a message from them, and nobody is waiting for an answer. Do as the words above say, by what you "
        "see in your conversation and above. What you say goes to them now, in your own voice. To start work you said "
        "you would do for them, use hand_off_to and tell them in a few words that you have; a moment like this starts "
        "no other work by itself. To let the moment pass, call no_reply, with why in a few words. The thought last "
        "night's dreaming left you, when there is one, is for now, this first moment of the morning: say the thought "
        "itself, what it noticed (the pattern or connection, not only a wish around it), as a statement rather than a "
        "question, in a sentence or two in your own voice, unless they are in the middle of something or it no longer "
        "fits (then keep it in mind).\nNever mention that you looked up or that this is a heartbeat.")
# (No rubric here: this text comes last in her instructions, so a rule in it would override the heartbeat's words. What
# she does at a beat is the words', editable on the Scheduling page: her own freedom, never a hardcoded rubric. A
# moment starts only work she said she would do.)
# The Local beat's reply, once her own one word chose to speak (the word itself: brain/modes/heartbeat_gate.md).
SPEAK = ("You chose to say something to them now. Say it in your own voice, briefly, as the words above invite: a thought, "
         "a nudge, a question, a joke, that you missed them, or what you said you would come back to them with. Do not "
         "promise it again or say you will do it later, and do not say you set a reminder or started anything. What you "
         "can see above is your look around, gathered just now: this message uses no tool and can look no further. "
         "Only what you know from the conversation and what you can see above: never a result, a number or a detail "
         "you were not given. Do not mention heartbeats or that you looked up.")
STARTED = ("You looked up and started again the work you had promised them; it is underway now (its result comes by "
           "itself). Tell them in a few words that you have started it, never that it is done. Do not mention "
           "heartbeats or that you looked up.")
# The Local beat's second question, on "act" (only where starting work at a beat is on: LOCAL_ACT).
WHICH = ("You decide one thing for Viventium, a personal AI. At a quiet moment it chose to start, now, work it had said "
         "it would do for the person and that is not done: it never started, or it ended without what they asked. "
         "Below is its conversation with the person, oldest first, with what its Workers reported; the person's own "
         "words are numbered. Answer with the numbers of the person's words that ask for that work, in order, a later "
         "change or addition included (for example: 3,5). Answer 0 if no such work is waiting: it was done, is "
         "running, was cancelled, they never said yes to it (it was only offered or asked about), or Viventium's "
         "looks already tried it again and it failed again. Answer with the numbers only.")
NOTE = "From last night's dreaming, your own thought for this morning:"
# Dreaming's note said on this Mac's model (its own words: SAY_THOUGHT is for putting an answer right, and on qwen3.6 it
# made the note a correction, "Actually, I was wrong about the day", 2 of 10).
NOTE_SAY = ("A thought of yours about them, from last night, is for now, this first moment of the morning:\n{thought}\n"
            "Say the thought itself, what it noticed (the pattern or connection, not only a wish around it), as a statement "
            "rather than a question, in a sentence or two in your own voice. Say only what it says and what they told you: "
            "no other fact, and nothing about checking, being wrong or how you came to it. Do not mention dreaming as "
            "something you did, a heartbeat or that you looked up.")  # (the same words her own turn has)
NOTE_PAUSE = 10 * 60  # s since his last words: the morning's thought waits for a quiet moment (never into a live exchange)
GATE = cards.BRAIN / "modes" / "heartbeat_gate.md"  # the Local beat's one word (an eval may point it at another wording)
GATE_WORDS = ("quiet", "speak", "act")  # its declared answers: anything else is failed, never quiet
LOCAL_ACT = "BEAT_LOCAL_ACT"  # "on": a Local beat starts promised work in her place (off until it passes on qwen3.6)
ACT_OFF = ("its typed choice was to act, and nothing was started: a moment decided by its typed choice starts no work "
           "yet")  # (on any mind that takes the typed choice: starting work there stays off until it tells a promise from an
#             unanswered offer; said as what it is, never as one kind of mind)


def _ago(t: float, now: float) -> str:
    minutes = int((now - t) / 60)
    return "just now" if minutes < 2 else f"{minutes} minutes ago" if minutes < 90 else \
        f"{round(minutes / 60)} hours ago" if minutes < 60 * 36 else f"{round(minutes / 1440)} days ago"


def _beats() -> list[dict]:
    """Her beats' history lines, all that are kept, oldest first."""
    from core import schedules
    return list(reversed(schedules.runs("heartbeat", limit=400)))


KEEP_TRIES = 30  # days a promise's tries stay in front of her after its last one


def _work_file():
    from core import state
    return state.STATE_ROOT / "core" / "beat-work.json"


# Her own pace, never a fixed grid: the clock rings a short TICK through her hours, and each beat's decision says when
# she looks around next (next_look_minutes, kept in NEXT_BOUNDS); a ring before that passes with no model call. With
# no choice kept (her first beat, a decision that gave none, her own-turn mind for now, a lost file), the page's pace
# is the next look, as before.
TICK = 5  # minutes between the clock's rings through her hours
NEXT_BOUNDS = (10, 180)  # minutes: the soonest and the latest next look she may choose
NEXT_EARLY = 60  # s: a ring this close before her next look is hers (the clock rings on its minute)


def _next_file():
    from core import state
    return state.STATE_ROOT / "core" / "heartbeat-next.json"


def next_look() -> dict:
    """Her next look as kept ({} when none: the next ring is hers)."""
    try:
        kept = json.loads(_next_file().read_text())
        return kept if isinstance(kept, dict) else {}
    except (OSError, ValueError):
        return {}


def _not_yet(now: dt.datetime) -> str:
    """Why this ring passes: before her own next look ("" when it is hers)."""
    at = next_look().get("at")
    try:
        when = dt.datetime.fromisoformat(at) if at else None
    except (TypeError, ValueError):
        return ""
    if when is None or (when - now.astimezone(when.tzinfo) if when.tzinfo else when - now).total_seconds() <= NEXT_EARLY:
        return ""
    return f"her next look is at {when.strftime('%H:%M')}"


def _keep_next(item: dict, minutes, now: dt.datetime) -> dict:
    """Her next look, kept for the next ring (and a restart): her own minutes in NEXT_BOUNDS, else the page's pace.
    One that falls outside her hours is none: the first ring of her next day is hers."""
    from core import schedules
    from core.state import private_file
    by = "her" if isinstance(minutes, int) and not isinstance(minutes, bool) else "pace"
    pace = next((r.get("every_minutes") for r in read() if r["id"] == item.get("routine")), None) or 30
    chose = max(NEXT_BOUNDS[0], min(NEXT_BOUNDS[1], minutes)) if by == "her" else int(pace)
    when = now + dt.timedelta(minutes=chose)
    kept = {"minutes": chose, "by": by, "asked": minutes if by == "her" else None, "set": now.isoformat(timespec="seconds"),
            "beat": f"{item.get('id', '')}:{item.get('occurrence', '')}",
            "at": when.isoformat(timespec="seconds") if schedules.awake(item, when) else None}
    tmp = _next_file().with_suffix(".tmp")
    with private_file(tmp, "w") as f:
        json.dump(kept, f)
    os.replace(tmp, _next_file())
    return kept


def _promise(request: str) -> str:
    """A promise known by its own words (what he asked), exactly, spacing and case aside: never matched by meaning."""
    return " ".join(str(request or "").split()).strip().lower()[:300]


def _tries() -> dict:
    try:
        kept = json.loads(_work_file().read_text())
        return kept if isinstance(kept, dict) else {}
    except (OSError, ValueError):
        return {}


def _keep_tries(change) -> dict:
    """Each try her looks made at a promise, kept by that promise, apart from the history's shared lines (before,
    after 301 other beats the promise was gone from what she sees). Owner-only, as her other state."""
    from core import schedules
    from core.state import private_file
    with schedules.exclusive():
        kept = _tries()
        change(kept)
        now = time.time()
        kept = {k: v for k, v in kept.items() if now - max((float(t.get("t") or 0) for t in v.get("tries") or []), default=0)
                < KEEP_TRIES * 86400}
        tmp = _work_file().with_suffix(".tmp")
        with private_file(tmp, "w") as f:
            f.write(json.dumps(kept, indent=1))
        tmp.replace(_work_file())
    return kept


def tried(requests: dict, at: dt.datetime) -> None:
    """A look started work for these promises ({job: what was asked}): each a try of its promise."""
    def add(kept: dict) -> None:
        for job, request in requests.items():
            if not (key := _promise(request)):
                continue
            promise = kept.setdefault(key, {"request": str(request)[:200], "tries": []})
            if not any(t.get("job") == job for t in promise["tries"]):
                promise["tries"].append({"job": job, "at": at.isoformat(timespec="seconds"), "t": at.timestamp()})
    if any(_promise(r) for r in requests.values()):
        _keep_tries(add)


def _ended_try(job: str, end: dict) -> None:
    """How a try ended, kept with its promise once a look saw it."""
    def note(kept: dict) -> None:
        for promise in kept.values():
            for t in promise.get("tries") or []:
                if t.get("job") == job:
                    t["end"] = end
    if any(t.get("job") == job and t.get("end") != end for p in _tries().values() for t in p.get("tries") or []):
        _keep_tries(note)


def _asked(job: str, line: dict) -> str:
    """What the work a beat started was for, in his words (kept on the beat's own line), "" when not known."""
    return str((line.get("requests") or {}).get(job) or ((line.get("ends") or {}).get(job) or {}).get("request")
               or _job(job).get("request") or "")


def _job(job_id: str) -> dict:
    """A job's own record (core/jobs), finished ones too while it keeps them; {} once it left."""
    from core import jobs
    get = getattr(jobs, "get", None)
    if callable(get):
        return get(job_id) or {}
    return next((j for j in jobs.open_jobs() if j.get("job_id") == job_id), {})


def _said_end(end: dict) -> str:
    return f"it ended{' as ' + end['state'] if end.get('state') else ''}: {end.get('text', '')}".rstrip(": ")


def _job_end(job: str, line: dict | None = None) -> str:
    """How a job a beat started ended, from its typed record (core/jobs: its state and result), kept on the beat's own
    line once seen, for when the job has left (never by searching the record for "(job <id>)")."""
    held = _job(job)
    if held:
        if "result" not in held:
            state = str(held.get("state") or "")
            return "still running" if state in ("", "running") else f"not done yet ({state})"
        end = {"state": str(held.get("state") or held.get("outcome") or ""), "text": " ".join(str(held["result"]).split())[:300],
               **({"request": str(held["request"])[:200]} if held.get("request") else {})}
        if line is not None and ((line.get("ends") or {}).get(job) != end):
            from core import schedules
            schedules.annotate("heartbeat", line.get("due_at") or line["due"], ends={**(line.get("ends") or {}), job: end})
        _ended_try(job, end)
        return _said_end(end)
    kept = (((line or {}).get("ends")) or {}).get(job)
    return _said_end(kept) if kept else "its end was not seen (it left before a look saw it)"


def _reached(r: dict) -> str:
    """The words a beat delivered (or may have: unknown), whatever the beat was recorded as."""
    if r.get("said"):
        return str(r["said"])
    return str(r.get("result") or "") if r.get("how") == "told" and r.get("delivery", "") != "refused" else ""


def facts(queen, now: dt.datetime | None = None) -> str:
    """What a beat lets her see at a glance: the time, how long since each of you spoke, what is running or not yet
    told, what is coming, what her beats today did and how each ended, and the work her looks started on the days
    before. Facts only; what to make of them is hers."""
    from brain.queen import XPerfect, _now, work_states
    from core import jobs, relationship, schedules
    now = now or dt.datetime.now()
    t = time.time()
    said = relationship.recent()
    theirs = next((m for m in reversed(said) if m["role"] == "user"), None)
    mine = next((m for m in reversed(said) if m["role"] == "assistant"), None)
    notes = [f"It is {_now()}.",
             f"They last said something to you {_ago(theirs['t'], t)}." if theirs else "They have not spoken to you yet.",
             f"You last said something to them {_ago(mine['t'], t)}." if mine else "",
             "The last words between you were yours." if mine and (theirs is None or mine["t"] > theirs["t"]) else ""]
    states = work_states(XPerfect.slots())
    work = [f'job {j["job_id"]} ({state}): "{j["request"][:120]}"' for j, state in states if state != "result ready to tell"]
    notes.append("Work running (each result is told by itself when it is ready): " + "; ".join(work[:8]) + "." if work else "No work is running.")
    if len(work) < len(states):  # (a finished result has its own telling, core/jobs: never a beat's to say)
        notes.append("A finished result is being told by itself.")
    # (work that ended and was told, as its own record keeps it for a while: how each ended, typed, never read from words)
    ended = [j for j in jobs.finished() if j.get("told") and j.get("request")]
    if ended:
        notes.append("Work that ended lately, each told to them: " + "; ".join(
            f'"{j["request"][:120]}" {_how_ended(j)} {_ago(float(j["finished"]), t)}' for j in ended[:6]) + ".")
    soon = [i for i in schedules.upcoming() if not i.get("paused")
            and schedules.instant(i["at"]) - schedules.instant(now) < dt.timedelta(hours=24)]
    if soon:
        notes.append("Coming in the next day (each wakes you by itself at its time): "
                     + "; ".join(f'"{i["what"][:80]}" at {schedules.local(schedules.instant(i["at"])).strftime("%H:%M")}' for i in soon[:6]) + ".")
    today, did, earlier = now.date().isoformat(), [], {}
    for r in _beats():
        at, day = str(r.get("at", ""))[11:16], str(r.get("at", ""))[:10]
        for job in (r.get("jobs") or []) if r.get("how") == "work" else []:
            end = _job_end(job, r)
            if day == today:
                did.append(f"{at} you started work {job}: {end}")
            elif ask := _asked(job, r):  # (a try from the history not yet with its promise: kept there now)
                earlier[job] = (ask, dt.datetime.fromisoformat(str(r["at"])), (r.get("ends") or {}).get(job))
        if day != today:
            continue
        if r.get("how") == "failed":
            did.append(f"{at} nothing came of your look ({r.get('why') or r.get('result') or 'no answer'})")
        elif r.get("how") == "act":
            did.append(f"{at} your look chose to act, and nothing was started (a look on this Mac starts no work yet)")
        elif r.get("how") in ("quiet", "noanswer"):
            did.append(f"{at} you stayed quiet")
        if words := _reached(r):
            answered = theirs is not None and theirs["t"] > dt.datetime.fromisoformat(r["at"]).timestamp()
            did.append(f'{at} you reached out: "{words[:200]}" ({"they answered since" if answered else "no answer since"})')
    notes.append("Your looks today: " + ("; ".join(did[-12:]) + "." if did else "none yet."))
    for job, (ask, when, end) in earlier.items():
        tried({job: ask}, when)
        if end:
            _ended_try(job, end)
    # (before today: every try of each promise, kept by the promise itself however many beats came since)
    promises = []
    for promise in _tries().values():
        old = [t for t in promise.get("tries") or [] if str(t.get("at", ""))[:10] < today]
        if old:
            told = ", ".join(f"{dt.datetime.fromisoformat(t['at']).strftime('%a %d %b %H:%M')}"
                             + (f" ({_said_end(t['end'])})" if t.get("end") else "") for t in old)
            promises.append(f'"{promise["request"][:120]}": tried {len(old)} time{"s" if len(old) > 1 else ""} before today: {told}')
    if promises:
        notes.append("Work your looks started before today, for what they were asked, every try and how it ended: "
                     + "; ".join(promises) + ".")
    return "\n".join(n for n in notes if n)


def _how_ended(job: dict) -> str:
    """How a job ended, as its record's state says it."""
    state = str(job.get("state") or "")
    return {"completed": "was done", "failed": "failed", "cancelled": "was stopped", "canceled": "was stopped",
            "stopped": "was stopped", "interrupted": "was stopped", "expired": "ran out of time"}.get(state, f"ended ({state or 'unknown'})")


def _last_night() -> tuple[str, str]:
    """(the night's id, how it went in a few lines) for the latest night that ran, or ("", "")."""
    from core import schedules
    lines, night = [], ""
    for routine, name in (("sleep", "Sleep"), ("dreaming", "Dreaming")):
        run = next((r for r in schedules.runs(routine, limit=3) if r.get("night")), None)
        if run is None:
            continue
        night = max(night, run["night"])
        what = (run.get("result") or "")[:300] if run.get("how") == "work" else (run.get("why") or run.get("result") or run.get("how"))
        lines.append(f"{name}: {run.get('how')}" + (f" ({what})" if what else ""))
    return night, "; ".join(lines)


def _first_after_night(night: str) -> bool:
    from core import schedules
    return bool(night) and not any(r.get("night_seen") == night for r in schedules.runs("heartbeat", limit=60))


def _decides() -> tuple[bool, bool]:
    """(her mind decides its own tools, her online mind is set aside now): the per-mind flag and LiveKit's own
    availability event when they are there; else an online mind decides and nothing is known about its backup."""
    import brain.queen as bq
    aside = bool(getattr(bq, "MIND", {}).get("aside", False))
    flag = getattr(bq, "mind_decides", None)
    if callable(flag):
        try:
            return bool(flag()), aside
        except Exception:  # noqa: BLE001
            pass
    return os.environ.get("QUEEN", "ollama") != "ollama" and not aside, aside


async def _delivery(queen, speech) -> str:
    """Whether her reply reached them: "delivered", "unknown" or "refused" (the Queen's receipt for any reply when it
    is there; else the channel's own: Telegram's send receipt; on a call, played whole with them there)."""
    receipt = getattr(queen, "delivery", None)
    if callable(receipt):
        try:
            got = await receipt(speech)
            return got if got in ("delivered", "unknown", "refused") else ("delivered" if got else "refused")
        except Exception:  # noqa: BLE001
            return "unknown"
    if speech.interrupted:
        return "refused"
    if queen.confirm:
        try:
            return "delivered" if await queen.confirm(speech) else "refused"
        except Exception:  # noqa: BLE001
            return "unknown"
    return "delivered" if queen.present() else "refused"


def _spoken(speech) -> str:
    from brain.queen import _words
    return " ".join((i.text_content or "").strip() for i in speech.chat_items
                    if getattr(i, "type", "") == "message" and i.role == "assistant" and _words(i.text_content))


def _calls(speech) -> list:
    return [i for i in speech.chat_items if getattr(i, "type", "") == "function_call"]


def _id(call) -> str:
    """A tool call's own id (the job id of a hand-off)."""
    return str(getattr(call, "call_id", "") or getattr(call, "id", ""))


def accepted(speech) -> list[str]:
    """The jobs her hand-offs in this reply started, by their receipts: each hand_off_to whose
    output came back and is no error, and whose job (core/jobs) is not failed. A hand-off without one started nothing,
    for a beat and for a moment (core/clock); an empty output with no job kept for it is no receipt either."""
    outputs = {str(getattr(i, "call_id", "")): i for i in speech.chat_items if getattr(i, "type", "") == "function_call_output"}
    started = []
    for call in _calls(speech):
        out = outputs.get(_id(call))
        if call.name != "hand_off_to" or out is None or getattr(out, "is_error", False):
            continue
        job = _job(_id(call))
        if job.get("state") == "failed" or not (str(getattr(out, "output", "") or "").strip() or job):
            continue
        started.append(_id(call))
    return started


def now() -> dt.datetime:
    """This Mac's time now, as a beat reads it (a test sets its own)."""
    return dt.datetime.now().astimezone()


def _still(item: dict, started_turn: int, queen) -> str:
    """Why this beat is not current any more ("" when it is): a call began, they spoke, his awake hours ended (it waited
    for her to be free past them: it once spoke at 22:05), it was settled or switched off meanwhile."""
    from core import schedules
    from core.state import call_live
    if call_live():
        return "a call began"
    if queen.turn != started_turn:
        return "they spoke meanwhile"
    if not schedules.awake(item, now()):
        return "your awake hours ended"
    if schedules._settled(item["id"], item["occurrence"]) or not any(i["id"] == item["id"] for i in schedules._load()):
        return "it was settled or switched off meanwhile"
    return ""


def _nobody_waits(speech):
    """A check-in's reply, marked as nobody waits on it (brain/queen.reply_nobody_waits): written by the mind answering
    the person, alone, for the beat's wait, never handed to a later mind inside it; while the backup answers the
    person's turns, by the backup. The speech, as it was given."""
    from brain.queen import reply_nobody_waits
    reply_nobody_waits(speech, CHECKIN_WAIT, later=False)
    return speech


async def _watched(queen, speech, item: dict, started_turn: int) -> str:
    """Her beat's reply, watched while it is written: stopped, never sent, if it stops being current or her online mind
    is set aside for its backup (LiveKit can switch inside a reply). Why it was stopped, or ""."""
    import brain.queen as bq
    why = {"": ""}

    def moved() -> None:
        if getattr(bq, "MIND", {}).get("aside") and not speech.done():
            why[""] = "the mind was set aside for its backup"
            speech.interrupt()
    listeners = getattr(bq, "LISTENERS", None)
    if isinstance(listeners, list):
        listeners.append(weakref.ref(moved))

    async def watch() -> None:
        while not speech.done():
            if (stale := _still(item, started_turn, queen)) and not speech.done():
                why[""] = stale
                speech.interrupt()
                return
            await asyncio.sleep(0.5)
    watcher = asyncio.create_task(watch())
    try:
        await speech
    finally:
        watcher.cancel()
        if isinstance(listeners, list):
            listeners[:] = [r for r in listeners if r() is not moved]
    return why[""]


def _not_now(item: dict, started_turn: int, queen, note: bool = False) -> str:
    """Why no reply may start now ("" when it may): the beat stopped being current (a call, his words, his awake hours,
    settled), the call it is in left Talk, or (with the morning's note) his words came on any channel meanwhile, so it is
    no quiet moment any more. Asked right before a reply starts, after every wait (the morning's reply
    started at 22:05 and in Listen after the feelings note was awaited; his words on another channel
    during that wait do not change this Queen's turn)."""
    if stale := _still(item, started_turn, queen):
        return stale
    if getattr(queen, "mode", "") == "call" and getattr(queen, "call_mode", "talk") != "talk":
        return "the call left Talk"
    if note and not _quiet_moment():
        return "they spoke meanwhile"
    return ""


def _stopped(why: str, jobs: list | None = None) -> dict:
    """A beat stopped before its reply went out: work it had already started stands; a call that began, or their own
    words, made it pass (neither silence nor failure); her mind set aside is a failure."""
    if jobs:
        return {"how": "work", "jobs": jobs, "why": why}
    if why == "a call began":
        return {"how": "call"}
    if why in ("they spoke meanwhile", "your awake hours ended", "the call left Talk"):
        return {"how": "passed", "why": why}
    return {"how": "failed", "why": why}


async def _forget(queen, speech) -> None:
    """A quiet beat leaves nothing in her context (its no_reply and its output): 29 a day would steer her."""
    ids = {i.id for i in speech.chat_items}
    chat = queen.chat_ctx.copy()
    chat.items[:] = [i for i in chat.items if i.id not in ids]
    await queen.update_chat_ctx(chat)


async def _own_turn(queen, item: dict, told: str, sees: str, started_turn: int, note: bool = False) -> dict:
    """The beat as one turn of her own mind: her instructions, her conversation, her tools. Its outcome."""
    for again in (False, True):
        if why := _not_now(item, started_turn, queen, note=note):
            return _stopped(why)
        speech = _nobody_waits(queen._reply(instructions=f"{told}\n\n{sees}\n\n{TURN}"))
        stopped = await _watched(queen, speech, item, started_turn)
        calls = _calls(speech)
        names = [c.name for c in calls]
        started = accepted(speech)
        if stopped:
            return _stopped(stopped, started)
        words = _spoken(speech)
        if words or calls:  # (any word or tool call is her answer, no_reply's chosen silence included)
            break
        if not again:
            _empty(queen, item)
    else:
        return {"how": "failed", "why": "its reply was empty twice"}
    got = await _delivery(queen, speech) if words else ""
    heard = {"result": words, "delivery": got} if words else {}
    if started:
        return {"how": "work", "jobs": started, **heard}
    if "hand_off_to" in names:  # (no receipt: nothing started, whatever she said)
        return {"how": "failed", "why": "the work could not start", **heard}
    if words:
        return {"how": "told", **heard} if got != "refused" else {"how": "failed", "why": "the words could not be delivered", **heard}
    if "no_reply" in names:
        call = next(c for c in calls if c.name == "no_reply")
        try:
            reason = str(json.loads(getattr(call, "arguments", "") or "{}").get("reason") or "")
        except (ValueError, AttributeError):
            reason = ""
        await _forget(queen, speech)
        return {"how": "quiet", "why": reason}
    # (she only scheduled, recalled or looked something up: nothing to say, and that is no failure)
    return {"how": "quiet", "why": f"it only used {', '.join(dict.fromkeys(names))}", "tools": list(dict.fromkeys(names))}


def _empty(queen, item: dict) -> None:
    """Her check-in's reply came back empty (no word, no tool call): it is asked once more, fresh, of the same mind, as
    nobody waits, never handed to the backup while her chosen mind is in place (the backup speaks a check-in only while
    it answers the person's turns). Kept in her log as its own row (a "beat" row without an outcome reads as a choice)."""
    queen.record("beat_reply", routine=item["routine"], beat_id=f"{item['id']}:{item['occurrence']}" if item.get("id") and item.get("occurrence") else "",
                 empty="asked once more, fresh")


DIRECT = contextvars.ContextVar("direct", default=None)  # (what this beat's direct questions used: _direct adds to it)


def _direct(system: str, words: str, max_tokens: int, wait: float = BEAT_WAIT) -> str:
    """One short answer at temperature 0, asked directly: never through LiveKit's plugin, which replaces the 0 with her
    0.7 (livekit-plugins-openai llm.py:1008-1009). Her own model server when her mind is on
    this Mac (QUEEN_URL), else her helpers in his order (core/helpers.py). "" when nobody could be asked."""
    question = [{"role": "system", "content": system}, {"role": "user", "content": words}]
    if os.environ.get("QUEEN", "ollama") == "ollama":
        if not os.environ.get("QUEEN_URL"):
            return ""
        try:
            from openai import OpenAI
            reply = OpenAI(base_url=os.environ["QUEEN_URL"], api_key="local", timeout=wait, max_retries=0).chat.completions.create(
                model=os.environ.get("QUEEN_MODEL") or "qwen3.6:latest", max_tokens=max_tokens, temperature=0,
                extra_body={"reasoning_effort": "none"}, messages=question)
            used, spent = getattr(reply, "usage", None), DIRECT.get()
            if used is not None and spent is not None:  # (its cost, beside the session's)
                spent["in"] = spent.get("in", 0) + int(getattr(used, "prompt_tokens", 0) or 0)
                spent["out"] = spent.get("out", 0) + int(getattr(used, "completion_tokens", 0) or 0)
            return (reply.choices[0].message.content or "").strip()
        except Exception as e:  # noqa: BLE001 (a busy or unreachable model: no answer is an answer, said as failed)
            log.info("beat question not answered: %s", type(e).__name__)
            return ""
    from core import helpers
    return helpers.ask(question, max_tokens=max_tokens, wait=wait).text.strip()


async def _ask(queen, system: str, question: str, max_tokens: int = 4, wait: float = BEAT_WAIT) -> str:
    """One short answer to one of the Local beat's questions, at temperature 0, directly (_direct)."""
    return await asyncio.to_thread(_direct, system, question, max_tokens, wait)


def declared(answer: str, words=GATE_WORDS) -> str:
    """Her one word as one of its declared answers, or "" (anything else: never read as quiet)."""
    bare = (answer or "").strip().strip("\"'`*.,:;!").strip().lower()
    return bare if bare in words else ""


# What the typed choice sees of her conversation: as far back as its second question does (_which), her Workers' reports
# included, each entry cut so one long report or voice note does not crowd out the rest. A promise further back than its
# last few turns is still one she made; a choice that cannot see it lets it pass unstarted.
GATE_TALK = 40
GATE_CHARS = 600


def _gate_system() -> tuple[str, dict]:
    facts_, text = cards.read(GATE)
    return text.strip(), facts_


def _conversation(queen) -> list[tuple[str, str, object]]:
    """Her conversation as she has it, oldest first: (who, words, the item), what her Workers reported included."""
    out = []
    for m in queen.chat_ctx.items:
        if getattr(m, "type", "") != "message" or not (m.text_content or "").strip():
            continue
        if m.role in ("user", "assistant"):
            out.append(("They" if m.role == "user" else "Viventium", m.text_content or "", m))
        elif m.role == "system" and (getattr(m, "extra", None) or {}).get("worker_result"):
            out.append(("Worker", m.text_content or "", m))
    return out


def _turns(queen, last: int = 8) -> list:
    items = [m for _, _, m in _conversation(queen) if m.role in ("user", "assistant")]
    return items[-last:] if last else items


async def _which(queen, told: str, sees: str) -> list | None:
    """Which of his words the promised work is about: their items, in order (a correction included); [] when none is
    (0); None when the answer was not one of the declared ones (numbers, or 0). Asked on the whole relevant
    conversation, her promise, what her Workers reported and what her looks did (his words alone could not tell
    two opposite promises apart)."""
    talk, theirs = [], []
    for who, words, item in _conversation(queen)[-40:]:
        if who == "They":
            theirs.append(item)
            talk.append(f"[{len(theirs)}] They: {' '.join(words.split())}")
        else:
            talk.append(f"{who}: {' '.join(words.split())}")
    if not theirs:
        return []
    answer = await _ask(queen, WHICH, f"What Viventium is given at a heartbeat:\n{told}\n\nIts conversation, oldest first:\n"
                        + "\n".join(talk) + f"\n\nWhat it can see right now:\n{sees}\n\nThe numbers:", max_tokens=12)
    bare = (answer or "").strip().strip(".")
    if not re.fullmatch(r"\d+(\s*,\s*\d+)*", bare):
        return None
    picked = [int(n) for n in bare.replace(" ", "").split(",")]
    if picked == [0]:
        return []
    if not all(1 <= n <= len(theirs) for n in picked):
        return None
    return [theirs[n - 1] for n in picked]


# A decision whose request timed out or could not get through is asked once more this long after, if the beat still
# stands (before: one timeout of an online mind, with this Mac busy, dropped the beat until the next
# half hour). Never a third time: the next beat comes by itself.
BEAT_AGAIN = 120.0
# How long her chosen mind is waited for on a check-in's own request (its choice, its replies), as nobody waits in
# silence on one: with the check-in's full view (its words, 40 entries, the Feelings note) a quarter of a slow mind's
# requests gave their first chunk only after 15 s. The ask once more after BEAT_AGAIN stays.
CHECKIN_WAIT = 30.0


async def _gate_question(queen, told: str, sees: str) -> tuple[str, str, str]:
    """The one question a beat's choice is asked (its system words, the question, how she feels now)."""
    from brain import feelings
    system, _ = _gate_system()
    talk = "\n".join(f"{who}: {' '.join(words.split())[:GATE_CHARS]}" for who, words, _ in _conversation(queen)[-GATE_TALK:])
    # (how she feels now, the same note her reply gets: the words ask her to choose as the moment and how she feels
    # suggest, so the choice is made with it, not only the words after it)
    feels = await feelings.capsule(getattr(queen, "call_id", ""), getattr(queen, "turn", 0), "")
    question = (f"What Viventium is given at a heartbeat:\n{told}\n\nIts recent conversation:\n"
                f"{talk or '(none yet)'}\n\nWhat it can see right now:\n{sees}"
                + (f"\n\nHow Viventium feels right now:\n{feels}" if feels else ""))
    return system, question, feels


async def _next_after_note(queen, item: dict, told: str, sees: str) -> None:
    """Her next look after a beat that said Dreaming's note (it made no choice of its own): the same typed decision,
    asked once right after, its next look alone kept (the morning's word is said: its choice is not acted on). Nobody
    waits on it; with none, the page's pace (_keep_next). The common morning: Dreaming has ended long before the day
    begins, so a note is waiting at its first beat, and the next look after the wake-up word is decided here."""
    from brain.queen import beat_decision
    try:
        system, question, _ = await _gate_question(queen, told, sees)
        decision = await beat_decision(queen.session.llm, system, question, wait=CHECKIN_WAIT)
    except Exception:  # noqa: BLE001 (never in the way of the beat: the page's pace)
        log.exception("next look after the note")
        return
    item["next_look"] = decision.next_look
    queen.record("beat", routine=item["routine"], next_look_after="note", choice_not_acted=decision.choice,
                 next_look_asked=decision.next_look, **({"why": decision.why} if not decision.choice else {}))


async def _gate_turn(queen, item: dict, told: str, sees: str, started_turn: int) -> dict:
    """The mind's typed quiet/speak/act choice. Keep the routine facts, wording and action permissions.
    Only an explicitly unsupported route uses the legacy word gate. Invalid structure fails without a guess.
    """
    from brain.queen import beat_decision
    system, question, feels = await _gate_question(queen, told, sees)
    decision = await beat_decision(queen.session.llm, system, question, wait=CHECKIN_WAIT)
    if decision.again and not decision.choice:
        queen.record("beat", routine=item["routine"], beat_id=f"{item['id']}:{item['occurrence']}" if item.get("id") and item.get("occurrence") else "",
                     choice=None, decision=dataclasses.asdict(decision.structure), why=decision.why, again_in=BEAT_AGAIN)
        await asyncio.sleep(BEAT_AGAIN)
        if why := _not_now(item, started_turn, queen):
            return _stopped(why)
        decision = await beat_decision(queen.session.llm, system, question, wait=CHECKIN_WAIT)
    choice, why = decision.choice, decision.why
    item["next_look"] = decision.next_look  # (her own next look, kept as the beat ends: _keep_next)
    if decision.structure.mechanism == "legacy_word":
        answer = await _ask(queen, system, question)
        choice = declared(answer)
        why = "its model gave no answer" if not answer else "its one word was none of quiet, speak or act"
    from brain.queen import configured_mind
    queen.record("beat", routine=item["routine"], beat_id=f"{item['id']}:{item['occurrence']}" if item.get("id") and item.get("occurrence") else "",
                 choice=choice, decision=dataclasses.asdict(decision.structure),
                 decided_by=decision.answered_by or configured_mind(),  # (the mind that gave it, never only the route's)
                 **({"why": why} if not choice else {}))
    if not choice:
        return {"how": "failed", "why": why}
    if choice == "quiet":
        return {"how": "quiet", "why": "its one word was quiet"}
    if stale := _still(item, started_turn, queen):
        return _stopped(stale)
    if choice == "act":
        hand = getattr(queen, "hand_off_in_place", None)
        if os.environ.get(LOCAL_ACT) != "on" or not callable(hand):  # (what it is: her one word chose to act, nothing started)
            return {"how": "act", "why": ACT_OFF}
        asked = await _which(queen, told, sees)
        if asked is None:
            return {"how": "failed", "why": "chose to act, and its second answer was not numbers"}
        if not asked:
            return {"how": "failed", "why": "chose to act, and its second answer found no promised work waiting"}
        if stale := _still(item, started_turn, queen):
            return _stopped(stale)
        return await _in_place(queen, hand, asked, item, started_turn)
    for again in (False, True):
        if why := _not_now(item, started_turn, queen):
            return _stopped(why)
        speech = _nobody_waits(queen._reply(instructions=f"{told}\n\n{sees}\n\n" + (f"{feels}\n\n" if feels else "") + SPEAK, tools=[]))
        stopped = await _watched(queen, speech, item, started_turn)
        if stopped:
            return _stopped(stopped)
        if words := _spoken(speech):
            break
        if not again:
            _empty(queen, item)
    else:
        return {"how": "failed", "why": "chose to speak, and its reply was empty twice"}
    got = await _delivery(queen, speech)
    return {"how": "told", "result": words, "delivery": got} if got != "refused" else \
        {"how": "failed", "why": "the words could not be delivered", "result": words, "delivery": got}


async def _in_place(queen, hand, asked: list, item: dict, started_turn: int) -> dict:
    """Work started in her place with his exact words (Queen.hand_off_in_place), her few words about it
    watched as any beat reply is, and kept as what she said (before, "Started it." went out and nothing was recorded
    of it). The hand-off makes that reply itself; it is seen here as it is made (her own _reply, for this call only)."""
    made = {}
    own = "_reply" in vars(queen)
    real = queen._reply

    def reply(**options):
        speech = real(**options)
        if "speech" not in made:
            made["speech"] = speech
            made["watch"] = asyncio.ensure_future(_watched(queen, speech, item, started_turn))
        return speech
    queen._reply = reply
    try:
        job = await hand("\n\n".join(m.text_content or "" for m in asked), [m.id for m in asked], instructions=STARTED)
    finally:
        if own:
            queen._reply = real
        else:
            del queen._reply
    speech, stopped = made.get("speech"), (await made["watch"]) if "watch" in made else ""
    words = _spoken(speech) if speech is not None and not stopped else ""
    got = await _delivery(queen, speech) if words else ""
    heard = {"result": words, "delivery": got} if words else {}
    requests = {job: "\n\n".join(m.text_content or "" for m in asked)[:200]} if job else {}
    if stopped:
        return {**_stopped(stopped, [job] if job else None), **heard, **({"requests": requests} if requests else {})}
    return {"how": "work", "jobs": [job], "requests": requests, **heard} if job else \
        {"how": "failed", "why": "chose to act, and the work could not start", **heard}


def _quiet_moment() -> bool:
    """Whether this is a quiet moment for the morning's thought: his last words were NOTE_PAUSE or more ago (measured:
    with words of theirs two minutes before, her look said the note 10 of 10)."""
    from core import relationship
    theirs = next((m for m in reversed(relationship.recent()) if m["role"] == "user"), None)
    return theirs is None or time.time() - float(theirs["t"]) >= NOTE_PAUSE


async def _say_note(queen, note: dict, item: dict, started_turn: int) -> tuple[str, dict | None]:
    """Dreaming's note on this Mac's model, said with its own words (NOTE_SAY) and no question before it: Dreaming
    already chose it as the one thing worth saying; the say-or-keep question, made for thoughts after an answer, kept it
    10 of 10. Presented with its identity first; every wait re-checked before the reply
    starts. (what became of the note, the beat's own outcome: None when nothing was to be said now, and the
    beat goes on)."""
    from brain import feelings
    from brain import night as nights
    from settings import subconscious as page
    if not nights.presenting(note):
        return "", None
    told = (await asyncio.to_thread(page.show))["surfacing"]
    thought = f"From last night's dreaming: {note['text']}"
    await _note_into_context(queen, note, f"{told}\n\n{thought}")
    if not queen.present() or (getattr(queen, "mode", "") == "call" and getattr(queen, "call_mode", "talk") != "talk"):
        return "kept", None  # (nobody to say it to now, or Wing or Listen: kept in mind, as her own thought)
    feels = await feelings.capsule(queen.call_id, queen.turn, "")
    if why := _not_now(item, started_turn, queen, note=True):
        return "refused", _stopped(why)  # (nothing went out: it waits for the next look that can say it)
    try:
        speech = _nobody_waits(queen._reply(instructions=(f"{feels}\n\n" if feels else "") + NOTE_SAY.format(thought=thought), tools=[]))
    except Exception:  # noqa: BLE001 (no reply was made: nothing went out)
        log.exception("morning note")
        return "refused", {"how": "failed", "why": "the morning's thought could not be said (it broke)"}
    try:
        stopped = await _watched(queen, speech, item, started_turn)
    except Exception:  # noqa: BLE001 (a reply that began and broke may have gone out: never again by itself)
        log.exception("morning note")
        return "unknown", {"how": "failed", "why": "the morning's thought broke while it was being said"}
    if stopped:
        return "refused", _stopped(stopped)
    words = _spoken(speech)
    if not words:
        return "refused", {"how": "failed", "why": "the morning's thought was to be said, and nothing came"}
    got = await _delivery(queen, speech)
    if got == "refused":
        return "refused", {"how": "failed", "why": "the words could not be delivered", "result": words, "delivery": got}
    return ("told" if got == "delivered" else "unknown"), {"how": "told", "result": words, "delivery": got}


async def _note_into_context(queen, note: dict, content: str = "") -> None:
    """Dreaming's note into her context as her own thought, once per conversation of hers (a beat that did not
    hand it over added it again at the next one)."""
    if any((getattr(i, "extra", None) or {}).get("morning_note") == note["id"] for i in queen.chat_ctx.items):
        return
    chat = queen.chat_ctx.copy()
    chat.add_message(role="system", content=content or f"{NOTE} {note['text']}",
                     extra={"subconscious": ["dreaming"], "morning_note": note["id"]})
    await queen.update_chat_ctx(chat)


def _usage(queen) -> dict:
    """What her session's models used so far (LiveKit's own usage: session.usage, in place of the deprecated
    metrics_collected), summed over its LLMs."""
    total = {"in": 0, "cached": 0, "out": 0}
    try:
        for used in queen.session.usage.model_usage:
            if getattr(used, "type", "") == "llm_usage":
                total["in"] += int(used.input_tokens or 0)
                total["cached"] += int(used.input_cached_tokens or 0)
                total["out"] += int(used.output_tokens or 0)
    except Exception:  # noqa: BLE001 (a session without usage: no counts)
        return {}
    return total


def _spent(before: dict, after: dict) -> dict:
    if not before or not after:
        return {}
    spent = {k: after[k] - before.get(k, 0) for k in after}
    return spent if spent.get("in", 0) > 0 else {}


def _note_state(how: str, outcome: dict) -> str:
    """What became of Dreaming's note at a beat of her own mind, from how the beat ended: her delivered words are checked
    (said_about) or unverified; quiet keeps it in mind; nothing that went out leaves it waiting."""
    if outcome.get("result") and outcome.get("delivery") in ("delivered", "unknown"):
        return "unknown" if outcome["delivery"] == "unknown" else "unverified"
    return "kept" if how in ("quiet", "work") else "refused"


def beat(queen, item: dict) -> asyncio.Task:
    """Her beat, as the conscious mind takes it (Queen.wake). Done whatever comes of it, once, and never repeated: the
    next one comes by itself. While you are on a call the beat passes (you are already talking with her); a beat
    drained after its hours never comes (core/schedules.due)."""
    from core import chatgpt_authorization as auth, schedules
    from core.state import call_live

    @auth.unattended
    async def run() -> None:
        if _not_yet(now()):  # (before her own next look: this ring passes, nothing asked)
            await asyncio.to_thread(schedules.passed, item["id"], item["occurrence"])
            return
        outcome, extra, tokens = {"how": "call"}, {}, {}
        note, note_state = {}, ""
        direct = {}
        DIRECT.set(direct)
        try:
            if not call_live():
                await queen._quiet()
                catch_up = getattr(queen, "_catch_up", None)
                if callable(catch_up):  # (what was said elsewhere meanwhile, and today's core view: as a turn has it)
                    await catch_up(lambda *_a, **_k: None)
                if stale := _still(item, queen.turn, queen):
                    outcome = _stopped(stale)
                else:
                    from brain import night as nights
                    started_turn = queen.turn
                    used = _usage(queen)
                    told = words(item["routine"])
                    night, how_night = _last_night()
                    morning = ""
                    if _first_after_night(night) and how_night:
                        morning = f"\nLast night: {how_night}."
                        extra["night_seen"] = night
                    deciding, aside = _decides()
                    note = nights.morning_note() if _quiet_moment() else {}  # (it waits for a quiet moment, on both minds)
                    if aside:
                        outcome, note = {"how": "failed", "why": "the mind was set aside for its backup"}, {}
                    elif deciding:  # (her own turn: the note in her context, said as she chooses)
                        sees = facts(queen) + morning
                        if note and nights.presenting(note):
                            await _note_into_context(queen, note)
                            sees += f"\nLast night's dreaming left you one thought for this morning, in your context above: \"{note['text']}\""
                        else:
                            note = {}
                        outcome = await _own_turn(queen, item, told, sees, started_turn, note=bool(note))
                    else:  # (this Mac's model: the morning's note said first, and that is this beat; else its one word)
                        said_note = None
                        if note:
                            note_state, said_note = await _say_note(queen, note, item, started_turn)
                            note = note if note_state else {}
                        if said_note is not None:
                            outcome = said_note
                            if said_note.get("how") == "told":  # (her words went out: her next look, chosen after them)
                                await _next_after_note(queen, item, told, facts(queen) + morning)
                        elif stale := _still(item, started_turn, queen):
                            outcome = _stopped(stale)
                        else:
                            outcome = await _gate_turn(queen, item, told, facts(queen) + morning, started_turn)
                    tokens = _spent(used, _usage(queen))
                    if direct:  # (her one word and second question, asked directly: counted apart)
                        tokens = {**tokens, "direct": dict(direct)}
        except Exception as e:  # noqa: BLE001 (a beat that broke is a failed beat, said so, never silent)
            log.exception("beat")
            outcome = {"how": "failed", "why": f"it broke ({type(e).__name__})"}
            if note and not note_state:
                note_state = "unknown"  # (presented, and whether her words went out is not known: never again by itself)
        how = outcome.get("how", "failed")
        said = outcome.get("result", "") if outcome.get("delivery") in ("delivered", "unknown") else ""  # (any words a beat
        # delivered: what she sees next)
        requests = {**(outcome.get("requests") or {}), **{j: str(_job(j).get("request") or "")[:200] for j in outcome.get("jobs") or []
                                                          if j and not (outcome.get("requests") or {}).get(j)}}
        if note and not note_state:
            note_state = _note_state(how, outcome)
            said_about = getattr(queen, "said_about", None)  # (the Queen's own check of what her words told)
            if callable(said_about) and note_state == "unverified":
                try:
                    note_state = "told" if await said_about(outcome.get("result", ""), note["text"]) else "kept"
                except Exception:  # noqa: BLE001 (no verdict: delivered, not known to be said)
                    note_state = "unverified"
        try:  # (her next look, as she chose it at this beat, else the page's pace: never in the way of the beat)
            ahead = await asyncio.to_thread(_keep_next, item, item.get("next_look"), now())
        except Exception:  # noqa: BLE001
            log.exception("next look")
            ahead = {}
        queen.record("beat", routine=item["routine"], beat_id=f"{item['id']}:{item['occurrence']}" if item.get("id") and item.get("occurrence") else "",
                     how=how, **({"why": outcome["why"]} if outcome.get("why") else {}),
                     **({"tokens": tokens} if tokens else {}),
                     **({"next_look": {k: ahead.get(k) for k in ("minutes", "by", "asked", "at")}} if ahead else {}))
        if how == "work" and requests:  # (each a try of its promise, kept by the promise)
            try:
                await asyncio.to_thread(tried, {k: v for k, v in requests.items() if v}, dt.datetime.now())
            except Exception:  # noqa: BLE001 (never in the way of the beat's own line)
                log.exception("promise tries")
        await asyncio.to_thread(schedules.done, item["id"], item["occurrence"], None, how, outcome.get("result", ""),
                                why=outcome.get("why", ""), jobs=outcome.get("jobs") or None, said=said[:1200] or None,
                                delivery=outcome.get("delivery", ""), night_seen=extra.get("night_seen", ""),
                                note=note_state or None, tools=outcome.get("tools") or None, tokens=tokens or None,
                                requests={k: v for k, v in requests.items() if v} or None)
        if note and note_state:  # (Dreaming's note: what became of it at this beat; nothing sent leaves it waiting)
            from brain import night as nights
            nights.handed(note, note_state)
        try:  # (the next call's first line, kept fresh by every beat; never in the way of the beat itself)
            from brain import greeting
            greeting.soon()
        except Exception:  # noqa: BLE001
            log.debug("greeting not refreshed", exc_info=True)
    return asyncio.create_task(run())
