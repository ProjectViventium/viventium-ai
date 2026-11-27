"""The menu bar reads and changes open conversations here.

Typed state only, never words of his:
- each room's own status (state/core/conversations/<room>.json), written by her agent in that room: its ears (his
  microphone on), whether she is talking in it (call: her hearing and voice on; at most a few rooms at once, take_call)
  and how she is on it (Talk, Wing, Listen only), refreshed every 20 s while the room is open and removed when that room
  ends. A page closed removes only its own; a stale one (an agent gone without a word) reads as no conversation.
- the call mode and how she is shown are her settings (state/settings.json): every open room follows them, and a call
  mode chosen there is the next call's too.
- an ask for her ears is not a setting but one ask (state/core/asks/ears.json, with an id), for one page: on, the latest
  open conversation, or, with none open, the first page to open after it (the menu bar opened it); off, the latest one
  whose microphone is on. Exactly one room's agent claims it (under a lock), and then it is gone: never acted on twice,
  never replayed on a reconnect or a page opened later, and dropped once it is too old.

Her agent tells the page on the room's own text stream (topic "viv.live"): the page turns its microphone on or off (her
agent then follows the microphone, as always), shows the mode, or looks again at how she is shown.
"""
import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import time
import uuid
from typing import Literal, get_args

from core import state

ROOMS = state.STATE_ROOT / "core" / "conversations"
ASKS = state.STATE_ROOT / "core" / "asks"
EARS = ASKS / "ears.json"
CONTROL = ASKS / "control.json"
Control = Literal["ears", "wing", "listen", "eyes", "place:local", "place:hybrid", "place:cloud",
                  "place:small-8", "place:small-16", "place:small-24", "page", "telegram", "life", "settings", "quit"]
FRESH = 60  # s: a conversation not refreshed for this long is gone (her agent refreshes it every 20 s)
EARS_WAIT = 300  # s: an ask for her ears is claimed this soon or never (a start from rest included: the menu bar's Ears
# starts her when she rests, and her page opens once she is ready)


def _room_file(room: str):
    return ROOMS / (hashlib.sha256(room.encode()).hexdigest()[:16] + ".json")  # (a room's name never becomes a path)


_ENDED: set[str] = set()  # (the rooms whose agents, in this process, have ended: nothing of theirs is written again)


def _write(room: str, ears: bool, mode: str, call: bool) -> None:  # (under _locked, by write and take_call)
    """Its own room's status, whole or not at all: a reader never sees it half written (written beside it, then put in
    its place). With its agent's process, so a room whose agent died frees its place at once (_alive)."""
    if room in _ENDED:
        return
    state.closed_dir(ROOMS)
    file = _room_file(room)
    fresh = file.with_name(f"{file.name}.{os.getpid()}.tmp")  # (never *.json: no reader takes it for a room)
    with state.closed_file(fresh) as f:
        f.write(json.dumps({"room": room, "ears": bool(ears), "call": bool(call), "mode": mode, "pid": os.getpid(),
                            "t": round(time.time(), 3)}))
    os.replace(fresh, file)


def write(room: str, ears: bool, mode: str, call: bool | None = None) -> None:
    """Her agent: its own room's conversation as it is now (never again once its room ended: gone). Whether it holds a
    call's place changes only when `call` says so (her agent's decision, or take_call's grant); a status written
    without it keeps the place as it is, so it never gives back a place just given nor claims one never given."""
    with _locked():
        if call is None:
            try:
                said = json.loads(_room_file(room).read_text())
                call = bool(said.get("call")) and said.get("room") == room
            except (OSError, ValueError, AttributeError):
                call = False
        _write(room, ears, mode, call)


def take_call(room: str, mode: str, most: int) -> bool:
    """Her agent, as his microphone turns a call on in `room`: whether she may talk there now, with at most `most` rooms
    talking at once on this Mac (call/agent.py MOST_CALLS); yes marks it so, under the same lock as every room's status
    and the menu bar's asks, so two microphones turned on at the same moment never both make the one too many. A room
    that stopped talking, or ended, frees its place (write, gone); one whose agent died, at once (_alive); one whose
    status cannot be read while it is fresh counts as talking (never a place taken from a call that is on)."""
    with _locked():
        if room in _ENDED:
            return False
        mine = _room_file(room)
        talking = 0
        for file in ROOMS.glob("*.json") if ROOMS.is_dir() else []:
            if file == mine:
                continue
            try:
                if time.time() - file.stat().st_mtime > FRESH:
                    continue
            except OSError:
                continue  # (gone meanwhile)
            try:
                said = json.loads(file.read_text())
                talking += bool(said.get("call")) and _alive(said)
            except (OSError, ValueError, AttributeError):
                talking += 1
        if talking >= most:
            return False
        _write(room, True, mode, call=True)
        return True


def _alive(said: dict) -> bool:
    """Whether the agent that wrote this room's status is still running (an older status names none)."""
    pid = said.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # (another user's, or not ours to ask: still there)
    return True


def touch(room: str) -> None:
    """Her agent, every 20 s while its room is open: still open."""
    with contextlib.suppress(OSError):
        if room not in _ENDED and (file := _room_file(room)).exists():
            file.touch()


def gone(room: str) -> None:
    """Her agent, when its room ends: its own status only, and none written for it again (a microphone change still on
    its way then would make it again, holding a call's place)."""
    with _locked():
        _ENDED.add(room)
        _room_file(room).unlink(missing_ok=True)


def conversations() -> list[dict]:
    """The open conversations, latest change first ({"room", "ears", "mode", "t"})."""
    found = []
    for file in ROOMS.glob("*.json") if ROOMS.is_dir() else []:
        try:
            if time.time() - file.stat().st_mtime > FRESH:
                continue
            said = json.loads(file.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(said, dict) and said.get("room") and _alive(said):
            found.append(said)
    return sorted(found, key=lambda c: c.get("t", 0), reverse=True)


def conversation() -> dict:
    """The open conversations as one, for the menu bar: {} when none is open; else whether a microphone is on in any of
    them, and the latest one's mode."""
    talks = conversations()
    if not talks:
        return {}
    return {"ears": any(c.get("ears") for c in talks), "mode": talks[0].get("mode", "talk"), "rooms": len(talks)}


@contextlib.contextmanager
def _locked():
    state.closed_dir(ASKS)
    with state.closed_file(ASKS / ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def first_conversation(*, claim: bool = True) -> dict | None:
    """Claim the native setup's first conversation once, across rooms and app restarts. claim=False only looks: her
    first hello may wait for the page's sound (call/agent.py), and a page closed while it waits has taken nothing, so
    the next room still gets her whole first greeting."""
    from core import relationship

    activation = state.logs() / ".first-ready"
    claimed = ASKS / "first-conversation"
    if not activation.is_file() or claimed.exists():
        return None
    with _locked():
        try:
            setup = json.loads(activation.read_text())
            if not isinstance(setup, dict) or setup.get("first_conversation") is not True:
                return None  # older installs used an empty file
            if claim:
                with state.closed_file(claimed, "x"):
                    pass
            if relationship.LOG.is_file() and relationship.LOG.stat().st_size:
                return None
        except (OSError, ValueError):
            return None
    return setup


def show_control(name: Control) -> None:
    """Ask the native panel to point to a control. The ask cannot change its value."""
    if name not in get_args(Control):
        raise ValueError("Unknown menu-bar control")
    draft = CONTROL.with_suffix(".tmp")
    with _locked():
        with state.closed_file(draft) as file:
            json.dump({"id": uuid.uuid4().hex, "control": name, "at": time.time()}, file)
        os.replace(draft, CONTROL)


def clear_control() -> None:
    with _locked():
        CONTROL.unlink(missing_ok=True)


def ask_ears(on: bool) -> str:
    """The menu bar asks for her ears, on or off: one ask, for one page (the module's docstring). Its id, or "" when there
    is nothing to ask (off, with no microphone on anywhere). A newer ask replaces one no page has claimed."""
    talks = conversations()
    if on:
        room = talks[0]["room"] if talks else ""
    else:
        room = next((c["room"] for c in talks if c.get("ears")), "")
        if not room:
            return ""
    ask = {"id": uuid.uuid4().hex, "on": bool(on), "at": round(time.time(), 3), "room": room}
    with _locked():
        with state.closed_file(EARS.with_suffix(".tmp")) as f:
            f.write(json.dumps(ask))
        os.replace(EARS.with_suffix(".tmp"), EARS)
    return ask["id"]


def claim(room: str, opened: float) -> dict | None:
    """Her agent in `room` (opened at `opened`): the ask for her ears, if it is this room's, taken so no other room and no
    later look ever has it. Its own room's, or, asked for the next page to open, a room opened after it. Too old: dropped."""
    if not EARS.exists():  # (the common case, once a second: no lock, no read)
        return None
    with _locked():
        try:
            ask = json.loads(EARS.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(ask, dict) or time.time() - float(ask.get("at") or 0) > EARS_WAIT:
            EARS.unlink(missing_ok=True)  # (too old: nobody's)
            return None
        mine = ask.get("room") == room if ask.get("room") else opened >= float(ask["at"]) - 1
        if not mine:
            return None
        EARS.unlink(missing_ok=True)
        return ask


def asks(saved: dict) -> dict:
    """What every open room follows of her settings: the call mode, and how she is shown."""
    return {"call_mode": saved.get("call_mode", "talk"), "mode_at": saved.get("call_mode_at", 0),
            "presence": saved.get("presence", "dots")}


def changes(before: dict, now: dict) -> dict:
    """What to tell the page when her settings move ({"mode", "presence"}, only what changed): a room opens the way the
    page and Settings already say, so nothing is told at its first look."""
    told: dict = {}
    if now["call_mode"] != before["call_mode"] or now["mode_at"] != before["mode_at"]:  # (chosen again counts: a call
        told["mode"] = now["call_mode"]                                                 # may have switched on its page)
    if now["presence"] != before["presence"]:
        told["presence"] = now["presence"]
    return told


def _stamp():
    try:
        st = (state.STATE_ROOT / "settings.json").stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


async def follow(tell, room: str, opened: float, every: float = 1.0) -> None:
    """Her agent, while its room is open: `await tell(changes)` whenever the menu bar (or Settings) changed what an open
    conversation follows, and when an ask for her ears is this room's. Looks once a second: her settings' file (its time
    and size; read only when they move), and whether an ask is waiting."""
    before = asks(await asyncio.to_thread(state.setting_all))
    last = await asyncio.to_thread(_stamp)
    while True:
        if ask := await asyncio.to_thread(claim, room, opened):
            await tell({"ears": bool(ask["on"])})
        stamp = await asyncio.to_thread(_stamp)
        if stamp != last:
            last = stamp
            now = asks(await asyncio.to_thread(state.setting_all))
            if told := changes(before, now):
                await tell(told)
            before = now
        await asyncio.sleep(every)
