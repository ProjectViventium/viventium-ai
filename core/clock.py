"""The clock: every channel wakes the same mind with what came due, through one path.

    .venv/bin/python -m core.clock        (./vx up starts it when Telegram is not connected)

wake_due(queen, taker) is what every channel runs every 20 s: Telegram's clock (chat/telegram.py), a call or the
typed chat while the person is in it (call/agent.py). core/schedules.due decides who takes what: the person's moments
go to the channel they are on (a call with them in it, the typed chat around their turns, else Telegram), or to the
one a moment names; her beat is the always-on channel's; the night any always-on process starts (brain/night.py).
The same Queen decides what a moment needs (woken): she tells it, starts the work it asks for, or says nothing.

Execution apart from delivery (work started for a moment ran again when her "started" was not sent):
work her reply starts for a moment settles that moment at once, as work, by its accepted job's receipt, whatever
happens to the message that says so; a hand-off that started nothing is tried again, at most three times; only a
message that was not sent is tried again, at the next pause when she was talked over. A telling is marked as under way
before anything is sent: after a crash it is settled from what is known (its job), else "unknown", and a message
whose delivery is unknown is never sent again by itself. During a call the call takes a moment exactly when the
channel rule (core/jobs.present) names it: in Wing or Listen it is the channel he is on otherwise.

With no bot and no call this process is the clock (main below): nobody can be told at that minute, so this Mac shows
the moment's own words at once, and the moment waits, within its window, for the next call or chat, which wakes her
with it (before, it became an owed "result" whose words said "start nothing": scheduled work never started
without a bot). If both clocks ever ran together nothing would fire twice: a moment is taken under a file lock, once.

Never during a test run (./vx test swaps her agent onto a synthetic state; yours stays as it is).
What every always-on process also looks after is here too (Upkeep), for Telegram's clock and this one.
"""
import asyncio
import datetime as dt
import functools
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from core import life, schedules, shared
from core.state import call_live

ROOT = Path(__file__).resolve().parents[1]

TICK = 20  # s (as Telegram's clock)
LOCK = ROOT / "logs" / "tests.lock"  # held by a live ./vx test run (vx: tests_running)
log = logging.getLogger("clock")


class Upkeep:
    """What an always-on process looks after every tick, whatever the channel: the Codex and Claude CLIs main
    Viventium shares keep their permissions (core/shared.py), and her Life core view is rebuilt when it is
    stale. Heavy model work waits while a call is on (one GPU on local: it slowed her voice)."""

    def __init__(self) -> None:
        self.core_job = None  # the Life core rebuild, when one is running

    def __call__(self) -> None:
        try:  # (never in the way of what the clock is for: a reminder still comes due if this fails)
            shared.check()
            from core import attachments
            attachments.upkeep(background=True)  # (what he sent more than 30 days ago goes, at most once an hour)
            if life.core_is_stale() and not call_live() and (self.core_job is None or self.core_job.poll() is not None):
                self.core_job = subprocess.Popen([sys.executable, "-m", "core.life", "core"], cwd=ROOT,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            log.exception("upkeep")


@functools.cache
def _boot() -> float:
    """When this Mac last started (a lock or pid from before it is stale)."""
    try:
        said = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
        return float(said.split("sec = ")[1].split(",")[0])
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def tests_running() -> bool:
    """A live test run holds the lock (vx's own rule: not a lock from before the last restart, not a dead pid)."""
    try:
        made = LOCK.stat().st_mtime
    except OSError:
        return False
    if made < _boot():
        return False
    try:
        os.kill(int((LOCK / "pid").read_text()), 0)
        return True
    except (OSError, ValueError):
        return not (LOCK / "pid").exists() and time.time() - made < 60  # (a run that is just starting)


def show(text: str) -> bool:
    """macOS's own notification, with the reminder's own words and nothing else. The words travel as an
    argument, never inside the script, so nothing in them can be run."""
    try:
        return subprocess.run(["osascript", "-e", "on run argv", "-e",
                        'display notification (item 1 of argv) with title "Viventium AI" subtitle "Reminder"',
                        "-e", "end run", text[:240]], stdin=subprocess.DEVNULL, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def wake(queen, item: dict):
    """A moment has come, in this channel's Queen (Queen.wake is this): a night routine starts in a process of its own
    (brain/night.py), her beat looks up (core/routines.beat), a moment of theirs wakes her (woken)."""
    if item.get("routine") in schedules.NIGHT:
        from brain import night
        night.start(item)
        return None
    if item.get("routine"):
        from core import routines
        return routines.beat(queen, item)
    return woken(queen, item)


def _nights() -> None:
    """A night run whose process ended before its run or its finishing was over is taken up again (brain/night.resume):
    on every look, never only when its own moment comes (a settled Sleep held Dreaming until the next night)."""
    try:
        from brain import night
        night.resume()
    except Exception:  # noqa: BLE001 (never in the way of what the clock is for)
        log.exception("night resume")


def wake_due(queen, taker: str, now: dt.datetime | None = None) -> list[dict]:
    """What came due for this channel, each woken in this channel's Queen (Queen.wake: a night routine starts, a beat
    looks up, a moment of theirs is woken). Run every 20 s by every channel."""
    _nights()
    fired = schedules.due(now or dt.datetime.now(), taker)
    for item in fired:
        if not item.get("notify_only"):
            queen.wake(item)
    return fired


async def wake_due_async(queen, taker: str, now: dt.datetime | None = None) -> list[dict]:
    """The call's clock: file work off its audio loop; Queen.wake still runs on that loop."""
    def due():
        _nights()
        return schedules.due(now or dt.datetime.now(), taker)

    fired = await asyncio.to_thread(due)
    for item in fired:
        if not item.get("notify_only"):
            queen.wake(item)
    return fired


def _now_text() -> str:
    return dt.datetime.now().astimezone().strftime("%A %Y-%m-%d %H:%M:%S %Z")


def woken(queen, item: dict) -> asyncio.Task:
    """A moment they asked her to keep has come: the same Queen, with her full context, decides (tell them, start the
    work it asks for, or say nothing). Its telling is marked as under way before anything is sent (a crash in between
    is never a second telling: core/schedules.presenting). Work settles it only by its accepted job's receipt; a
    hand-off that started nothing is tried again only while nothing was said about it (core/schedules.retry): once
    she told them, or may have, it ends failed with why, never another message; a message settles it once delivered; a
    message cut short is tried again at the next pause; one whose delivery is unknown (a reply that broke after it
    began too) is never sent again by itself. A call no longer in Talk (Wing, Listen), before or after the telling is
    marked, gives it back to the channel he is on."""
    from brain.queen import _words

    from core import chatgpt_authorization as auth

    @auth.unattended
    async def run() -> None:
        from core import jobs
        from core.routines import _delivery, accepted
        occurrence = item["occurrence"]
        if any(j.get("schedule") == item["id"] and schedules.same(str(j.get("occurrence", "")), occurrence)
               for j in jobs.open_jobs()):  # (its work was accepted before a restart: settled as work, never run twice)
            await asyncio.to_thread(schedules.done, item["id"], occurrence, None, "work")
            return
        await queen._quiet()
        if schedules._settled(item["id"], occurrence):
            return
        if getattr(queen, "mode", "") == "call" and getattr(queen, "call_mode", "talk") != "talk":
            schedules.again(item["id"], occurrence)  # (Wing or Listen: the channel he is on takes it, core/schedules.where)
            return
        if not await asyncio.to_thread(schedules.presenting, item["id"], occurrence):
            return  # (another process is telling it, or it was settled meanwhile)
        if getattr(queen, "mode", "") == "call" and getattr(queen, "call_mode", "talk") != "talk":
            schedules.presenting(item["id"], occurrence, on=False)  # (it went to Wing or Listen meanwhile)
            schedules.again(item["id"], occurrence)
            return
        queen.record("woken", schedule={k: item.get(k) for k in ("id", "what", "when", "repeat", "occurrence")})
        queen._woken_for = (item["id"], occurrence)  # (the hand-off keeps it with the job: never run twice)
        at = schedules.instant(occurrence)
        behind = (schedules.instant(dt.datetime.now()) - at).total_seconds()
        late = (f" It came due at {schedules.local(at).strftime('%H:%M')}" + (f" ({item['late']})" if item.get("late") else "")
                + ".") if behind > 120 else ""
        speech = None
        try:
            speech = queen._reply(instructions=(
                f"It is {_now_text()}. A moment you scheduled has come: \"{item['what']}\" (set for {item['when']}).{late} "
                "Act on it now: tell the user, start a Worker if it needs work, or call no_reply."))
            await speech  # (a failed model reply also ends here: it produced nothing)
        except Exception:  # noqa: BLE001
            log.exception("woken")
            if speech is None:  # (no reply was made: nothing went out, woken again)
                schedules.presenting(item["id"], occurrence, on=False)
                return
            try:  # (a reply that began and broke may have gone out: its receipt decides, else unknown, never resent)
                got = await _delivery(queen, speech)
            except Exception:  # noqa: BLE001
                got = "unknown"
            if got == "refused":
                schedules.presenting(item["id"], occurrence, on=False)
                return
            await asyncio.to_thread(schedules.done, item["id"], occurrence, None, "unknown", why="the reply broke after it began")
            return
        finally:
            queen._woken_for = None
        calls = {getattr(i, "name", "") for i in speech.chat_items if i.type == "function_call"}
        started = accepted(speech)
        if started:  # its work is accepted (its receipt): settled now, whatever becomes of the message
            await asyncio.to_thread(schedules.done, item["id"], occurrence, None, "work", jobs=started)
            return
        said = any(i.type == "message" and _words(i.text_content) for i in speech.chat_items)
        if speech.interrupted:  # talked over: tried again at the next pause, on this path
            schedules.presenting(item["id"], occurrence, on=False)
            schedules.again(item["id"], occurrence)
            return
        if "hand_off_to" in calls:  # (no receipt: the work could not start)
            got = await _delivery(queen, speech) if said else ""
            if got in ("delivered", "unknown"):  # (she told them, or may have: never another message about it)
                await asyncio.to_thread(schedules.done, item["id"], occurrence, None, "failed",
                                        why="the work could not start; " + ("you were told" if got == "delivered" else
                                                                             "whether you were told is not known"))
                return
            await asyncio.to_thread(schedules.retry, item["id"], occurrence, "the work could not start")  # (nothing was said)
            return
        if said:
            got = await _delivery(queen, speech)
            if got == "refused":
                schedules.presenting(item["id"], occurrence, on=False)
                return  # (stays, firing: woken again; nothing was sent)
            await asyncio.to_thread(schedules.done, item["id"], occurrence, None, "told" if got == "delivered" else "unknown")
            return
        if calls:  # (no_reply, or another tool: nothing to tell)
            await asyncio.to_thread(schedules.done, item["id"], occurrence, None, "quiet")
            return
        schedules.presenting(item["id"], occurrence, on=False)  # (nothing came out: woken again)
    return asyncio.create_task(run())


def tick(now: dt.datetime, notify=None) -> list[dict]:
    """The clock with no bot: every moment that has come for it. A night routine starts (it needs no channel); her
    beat has no conscious mind awake to look up, and says so; a moment of yours is shown on this Mac, once, and waits
    for the next call or chat (notify: what shows it; this Mac's own notification unless a test says otherwise)."""
    notify = notify or show
    _nights()
    fired = schedules.due(now, "clock")
    for item in fired:
        if item.get("routine") in schedules.NIGHT:  # the night needs no channel: a Worker does it (brain/night.py)
            from brain import night
            night.start(item)
            continue
        if item.get("routine"):  # her own beat: with no bot there is no conscious mind awake to look up, and no channel
            schedules.done(item["id"], item["occurrence"], now, "nochannel")
            continue
        if item.get("notify_only"):
            notify(item["what"])
    return fired


def once(now: dt.datetime, upkeep=None, notify=None) -> list[dict]:
    """One round of the clock; nothing at all while a test run holds the lock."""
    if tests_running():
        return []
    if upkeep:
        upkeep()
    return tick(now, notify)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    upkeep = Upkeep()
    log.info("ready (no Telegram bot: what comes due is shown on this Mac and waits for the next call or chat)")
    while True:
        try:
            for item in once(dt.datetime.now(), upkeep):
                log.info("due: %s (%s)", item["id"], item["repeat"] or "once")  # (never its words)
        except Exception:
            log.exception("clock")
        time.sleep(TICK)


if __name__ == "__main__":
    main()
