"""The Scheduling page's two calls: show() what is set for a time, and apply() one change.

Yours: the reminders and repeating moments you asked for. They are real: core/schedules.py keeps the list,
xPerfect's clock keeps the time and rings Light's doorbell. The page lists them, adds one, pauses one, removes one,
and shows what happened each time one came: told, kept quiet, started work, kept for your next call, or missed.

Built in: what Viventium does by itself on the same clock: a heartbeat while you are awake, sleep and dreaming at
night (core/routines.py). What comes with Light is in brain/routines/; what you changed is in state/scheduling.json.
All three run: the heartbeat's beat is on the clock, and sleep and dreaming come every night at their time
(brain/night.py); the page shows each one's next time and what each run did, with what a night run handed back.
"""
import datetime as dt
import json
import re
import time

from core import cards, routines
from core.state import STATE_ROOT
from settings import catalog

PAGE = routines.PAGE
EVERY = (20, 30, 60, 120)  # minutes
FIELDS = routines.FIELDS
REPEATS = [{"id": "", "name": "Once"}, {"id": "daily", "name": "Every day"}, {"id": "weekdays", "name": "Weekdays"},
           {"id": "weekly", "name": "Every week"}]
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
NIGHT = STATE_ROOT / "core" / "night"  # each night routine's own folder (brain/night.py): status.json is where it stands
STATUS_FRESH = 12 * 3600  # s: a "waiting" or "running" older than this is no longer what is happening
LINE = ("due_at", "why", "late", "night", "route", "commit", "morning", "morning_at", "result", "unread", "limited", "note",
        "said")  # (said as written)


def defaults() -> list[dict]:
    return routines.defaults()


def _yours() -> list[dict]:
    from core import schedules
    return [{"id": i["id"], "what": i["what"], "when": i["when"], "repeat": i.get("repeat", ""), "paused": bool(i.get("paused")),
             "zone": str(i.get("zone") or ""),  # (a moment kept in a named zone, e.g. Europe/Paris; "" follows this Mac)
             "history": [_run(r) for r in schedules.runs(i["id"])]} for i in schedules.upcoming()]


def _run(run: dict) -> dict:
    """One line of history, as core/schedules, core/routines and brain/night.py wrote it: when it was due (as this Mac read
    it, and `due_at`, the instant it is known by), when it was acted on, how it ended and why, who rang it, and "late"
    when this Mac was asleep; for a night, where it ran, what it wrote in your Life (the files it named, and how many
    others changed meanwhile), the step that can take it back, and what became of Dreaming's note in the morning."""
    out = {"what": run.get("what", ""), "due": run["due"], "at": run["at"], "how": run.get("how", ""), "by": run.get("by", "")}
    out.update({key: str(run[key])[:1200] for key in LINE if run.get(key)})
    if isinstance(run.get("span"), list) and len(run["span"]) == 2 and all(run["span"]):  # (the part of the day a night went through)
        out["span"] = [str(x) for x in run["span"]]
    if isinstance(run.get("tokens"), dict):  # (what a beat read and wrote, as its model counted it)
        out["tokens"] = {k: int(v) for k, v in run["tokens"].items() if k in ("in", "out", "cached") and isinstance(v, (int, float))}
    life = run.get("life") if isinstance(run.get("life"), dict) else {}
    wrote = [str(p) for p in [*(life.get("committable") or []), *(life.get("was_changed") or [])]]
    outside = [str(p) for p in life.get("named_outside") or []]
    if wrote or life.get("not_named") or outside or life.get("why_no_commit"):
        out["life"] = {"wrote": wrote[:12], "count": len(wrote), "others": len(life.get("not_named") or []),
                       **({"outside": outside[:12]} if outside else {}),
                       **({"no_commit": str(life["why_no_commit"])[:300]} if life.get("why_no_commit") else {})}
    return out


def _now(routine_id: str) -> dict:
    """Where a night routine stands this minute (brain/night.py and core/routines.py write it): waiting and why, or running
    and on which route (while fresh), or refused, and why (its time is inside your day: until that is put right); {} for
    anything else (done, set, never started, or too old to be what is happening now)."""
    try:
        status = json.loads((NIGHT / routine_id / "status.json").read_text())
        since = dt.datetime.fromisoformat(str(status.get("since"))).timestamp()
    except (OSError, ValueError, TypeError):
        return {}
    fresh = time.time() - since <= STATUS_FRESH
    if not (status.get("state") in ("waiting", "running") and fresh or status.get("state") == "refused" and status.get("why")):
        return {}
    out = {key: str(status[key])[:300] for key in ("state", "why", "route", "since") if status.get(key)}
    if status.get("state") == "waiting" and status.get("worker"):  # (held by a run Light cannot confirm: Clear, below)
        out["held"] = True
    return out


def _earlier() -> list[dict]:
    """Moments that came once and are gone: their one line each, newest first."""
    from core import schedules
    return [_run(r) for r in schedules.runs(None, limit=10)]


def _clock() -> str:
    """Who keeps the time now: xPerfect ("xperfect"), or Light itself because xPerfect's side is off or away."""
    from core import xclock
    if not xclock.on():
        return "light"
    try:
        with xclock._api() as api:
            xclock.destination(api)
        return "xperfect"
    except Exception:
        return "light"


def show() -> dict:
    from core import schedules
    routines.ensure()  # (the clock as the routines are set, also on a first look at the page)
    beats = {i["id"]: i for i in schedules.upcoming(True) if i.get("routine")}
    return {
        "yours": _yours(), "earlier": _earlier(), "clock": _clock(),
        "builtin": [{**r, "next": beats.get(r["id"], {}).get("when", ""), "now": _now(r["id"]),
                     "history": [_run(x) for x in schedules.runs(r["id"], limit=12)] if r["running"] else []} for r in routines.read()],
        "repeats": REPEATS, "every": list(EVERY),
    }


def no(why: str) -> dict:
    return {"ok": False, "why": why}


def apply(want: dict) -> dict:
    from core import schedules
    from settings import runtime
    if runtime.tests_running():
        return no("Viventium is being tested right now. Try again when it ends.")

    if "add" in want:
        what = str(want["add"].get("what", "")).strip()[:2000]  # (a longer prompt, written under its time)
        repeat = str(want["add"].get("repeat", ""))
        if not what:
            return no("Say what it is for.")
        if repeat not in [r["id"] for r in REPEATS]:
            return no("That way of repeating does not exist.")
        try:
            when = dt.datetime.fromisoformat(str(want["add"].get("when", "")))
        except ValueError:
            return no("Choose a day and a time.")
        if not repeat and schedules.local(when) <= dt.datetime.now():
            return no("That time has passed.")
        schedules.add(when, what, repeat)
    if "remove" in want and not schedules.cancel(str(want["remove"])):
        return no("That one is already gone.")
    if "pause" in want and not schedules.pause(str(want["pause"].get("id", "")), bool(want["pause"].get("paused"))):
        return no("That one is already gone.")
    if "clear" in want:  # a night held by a run Light cannot confirm: let go only when no run of its Worker is going
        from brain import night  # (the night's own rule: brain/night.py clearing(), asking both his xPerfects, failing closed)
        if str(want["clear"]) not in night.NAMES:
            return no("Only a night can be cleared.")
        done = night.clear(str(want["clear"]))
        if not done.get("ok"):
            return no(f"Not cleared: {done.get('why') or 'it could not be checked'}.")

    if "routine" in want:
        change = dict(want["routine"])
        routine_id = change.pop("id", "")
        base = next((r for r in defaults() if r["id"] == routine_id), None)
        if base is None:
            return no("That routine does not exist.")
        if "on" in change:
            change["on"] = bool(change["on"])
        if "every_minutes" in change and ("every_minutes" not in base or change["every_minutes"] not in EVERY):
            return no("That pace does not exist.")
        for field in ("awake_from", "awake_to", "at"):
            if field in change and (field not in base or not CLOCK.match(str(change[field]))):
                return no("That is not a time of day.")
        if "prompt" in change:
            change["prompt"] = str(change["prompt"])[:6000].strip() or base["prompt"]
        if "runs_on" in change or "effort" in change:
            if base["runs_on"] == "mind":
                return no("It runs on the conscious mind itself.")
            now = next(r for r in show()["builtin"] if r["id"] == base["id"])
            option = catalog.option("hands", str(change.get("runs_on", now["runs_on"])))
            if option is None:
                return no("That Worker type does not exist.")
            effort, efforts = change.get("effort", now["effort"]), option.get("efforts", [])
            change["runs_on"] = option["id"]
            change["effort"] = effort if effort in efforts else (option.get("effort", "") if efforts else "")

        def keep_routine(s: dict) -> None:
            mine = {**s.get("builtin", {}).get(base["id"], {}), **{f: v for f, v in change.items() if f in FIELDS}}
            mine = cards.differing(base, mine, FIELDS)
            s.setdefault("builtin", {})[base["id"]] = mine
            if not mine:
                del s["builtin"][base["id"]]
            if not s["builtin"]:
                del s["builtin"]
        cards.keep(PAGE, keep_routine)
        routines.ensure()

    return {"ok": True, "state": show()}
