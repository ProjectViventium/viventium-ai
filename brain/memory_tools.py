"""Her memory tools, the same on every channel (a call, the typed chat, Telegram): recall what she keeps, correct it,
forget it, and undo a change. The work is core/memory.py's; the memory page (settings/memory.py) makes the same
changes on screen, so a change made either way is the same change, listed once.

A change writes one line to her private change list and nothing else: his own notes are never edited by it (deleting
from them is a separate request, an ordinary hand-off to a Worker). A change is made only in a reply to a turn of his:
the tools themselves refuse in any reply she starts herself (a result, a beat, a woken reminder, a clock or a routine
reply), asked of the Queen once here (turn_words), never by a list of replies kept elsewhere (the clock's
and routines' replies, and the in-place and late replies, had no such list).
"""
import asyncio
import logging
import os

from livekit.agents import RunContext, function_tool

from core import memory

log = logging.getLogger("viventium.memory")
# Nothing on her reply path waits unbounded (a reply hung past the lane's 240 s): a memory call
# gives way after these seconds, and she answers without it (it may still finish in its own thread).
RECALL_WAIT = float(os.environ.get("MEMORY_RECALL_WAIT", "6"))
RECALL_ROOM = 0.5  # s of RECALL_WAIT left for her search to put its halves' results together and return
CHANGE_WAIT = float(os.environ.get("MEMORY_CHANGE_WAIT", "12"))
RECALL_LATE = ("Their memory did not answer in time just now, so nothing from it is here: answer from this "
               "conversation, and if it matters tell them you could not look in their memory just now; never guess "
               "what it holds.")
WRITE_WAIT = float(os.environ.get("MEMORY_WRITE_WAIT", "10"))  # s more, for a change whose write has begun
NOT_MADE = ("Their memory was too slow just now, so nothing was changed: tell them you could not make the change just now "
            "and to ask again in a moment; never say it was done.")
MAYBE_MADE = ("Their memory was slow writing it, so it may have been kept: tell them it may be done, and that the Memory "
              "page shows whether it is; never say it was not done, and never make it again now.")
STILL_WRITING = ("Their memory is still writing the change before this one, so nothing was changed now: tell them to ask "
                 "again in a moment; never say it was done.")
_pending: asyncio.Future | None = None  # (a change whose write was slow: the next change or undo waits for it first)
_pending_ask: tuple | None = None  # (what that slow change was asked: the tool's function and its first argument)


async def _within(wait: float, fn, *args):
    """A memory call in its own thread, given way after `wait` seconds: None when it did not answer by then."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), wait)
    except asyncio.TimeoutError:
        log.warning("memory %s gave way after %.1f s: her reply goes on without it", getattr(fn, "__name__", "call"), wait)
        return None


async def _change(fn, *args) -> dict | str:
    """A change made for her: made and said so, or not made (a forget she called "not made" was kept a
    second later). Its write begins before CHANGE_WAIT runs out, or never (core/life.Turn, asked under the change list's
    lock); once it has begun she waits for its receipt, WRITE_WAIT more at most, then says it may have been kept (the
    next change or undo waits for it under that lock, never acts on another)."""
    global _pending, _pending_ask
    from core import life
    if _pending is not None:
        if not _pending.done():  # (never acts on another while that one may still be kept)
            try:
                await asyncio.wait_for(asyncio.shield(_pending), WRITE_WAIT)
            except asyncio.TimeoutError:
                return STILL_WRITING
            except Exception:  # noqa: BLE001  (it ended, whatever its end: its own receipt was said already)
                pass
        done, ask = _pending, _pending_ask
        _pending = _pending_ask = None
        # The same ask again once that slow one has ended ("put it back", said twice while it wrote): that one's
        # receipt, never a second change (before, a repeated "put it back" took the change before it).
        if ask == (fn, args[:1]) and not done.cancelled() and done.exception() is None:
            return done.result()
    turn = life.Turn(CHANGE_WAIT)
    task = asyncio.ensure_future(asyncio.to_thread(memory.within_turn, turn, fn, *args))
    try:
        return await asyncio.wait_for(asyncio.shield(task), CHANGE_WAIT)
    except asyncio.TimeoutError:
        if turn.give_up() != "writing":
            log.warning("memory %s gave way before its write: nothing was changed", getattr(fn, "__name__", "change"))
            return NOT_MADE
    try:
        return await asyncio.wait_for(asyncio.shield(task), WRITE_WAIT)
    except asyncio.TimeoutError:
        log.warning("memory %s: its write is slow; it may have been kept", getattr(fn, "__name__", "change"))
        _pending, _pending_ask = task, (fn, args[:1])
        return MAYBE_MADE

CHANGING = {"memory_correct", "memory_forget", "memory_undo"}  # (never in a reply she starts herself)
NOT_HIS_TURN = ("Nothing was changed: her memory changes only when the user asks for it in their own turn, and this "
                "reply answers none.")


def his_turn(ctx: RunContext) -> bool:
    """Whether the reply this tool runs in answers a turn of his (the Queen's turn_words of it). No conversation at all
    (a direct call, as the memory page's own changes are) is his; a Queen that cannot tell is not."""
    queen = getattr(getattr(ctx, "session", None), "current_agent", None)
    if queen is None:
        return True
    words = getattr(queen, "turn_words", None)
    if not callable(words):
        return False
    try:
        return bool(words(getattr(ctx, "speech_handle", None)))
    except Exception:  # noqa: BLE001  (unknown: not his)
        return False


def _note(ctx: RunContext, action: str, receipt: dict) -> None:
    """What the turn log keeps of a change: which, and how many places (never the words themselves)."""
    queen = getattr(getattr(ctx, "session", None), "current_agent", None)
    record = getattr(queen, "record", None)
    if callable(record):
        record("memory", action=action, ok=bool(receipt.get("ok")), id=receipt.get("id", ""),
               places=len(receipt.get("passages", [])))


def _call(ctx: RunContext) -> str:
    """The conversation a change is made in."""
    return str(getattr(getattr(getattr(ctx, "session", None), "current_agent", None), "call_id", "") or "")


def _now(ctx: RunContext) -> set[int]:
    """The rows of his own words in this turn (his messages after her last reply, as the channel kept them): a look
    offers them last, after every earlier place, never leaves them out ("My card PIN is 4411. Actually,
    forget that I told you my PIN." is held only there), and never offers them alone while an earlier message holds
    the words (GPT-6.1 Sol: "forget what I said about the bakery's opening date" had found only that very
    request)."""
    chat = getattr(getattr(getattr(ctx, "session", None), "current_agent", None), "chat_ctx", None)
    rows: set[int] = set()
    for item in reversed(list(getattr(chat, "items", ()))):
        if getattr(item, "type", "") != "message":
            continue
        if item.role == "assistant":
            break
        if item.role == "user" and (row := (getattr(item, "extra", None) or {}).get("memory_row")):
            rows.add(int(row))
    return rows


def _list(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in (text or "").split(",") if part.strip())


@function_tool()
async def recall(ctx: RunContext, keywords: str, only: str = "") -> str:
    """Search the user's own Life memory: past conversations, people, plans, identity and
    preferences. The messages shown now are not their full history: this tool retrieves facts from
    older saved records. Before answering a personal-history question or saying you don't remember
    or have no record, search here; a fact absent from this chat may be saved in Life.
    General ideas, drafts or advice need no search just to be more personal. Use supplied context
    directly; look up older personal facts when the request actually needs them.

    Args:
        keywords: 2-6 distinctive words, e.g. "Biscuit dog vet".
        only: Only when they say where to look ("only in my plans"): those Life folders, comma-separated,
            e.g. "Plans". Usually empty.
    """
    # (each half inside the wait, so what one found is given when the other is slow: core/memory._search)
    found = await _within(RECALL_WAIT, memory.search, keywords, _list(only), max(0.5, RECALL_WAIT - RECALL_ROOM))
    return RECALL_LATE if found is None else found


@function_tool()
async def memory_correct(ctx: RunContext, correction: str, passages: str = "", old: str = "", replaces: str = "") -> str:
    """When the user says something you remember is wrong ("no, my sister lives in Porto now"): from
    now on you go by their correction. Their own notes are not changed. Then tell them in a few words.

    Args:
        correction: What is true now, in their words, e.g. "Ilse lives in Porto now".
        passages: Where the old version is, as recall or a look showed it: the file and line, e.g.
            "People/Ilse.md:3" or "conversation-2026-10-02-3f9a2b:7" (a past conversation, by the name recall
            gives it), or the full row:<n>:<digest> from a look for a conversation message, comma-separated.
            Without them a look comes back first, for you to name them.
        old: The old words there, e.g. "lives in Lisbon". Optional.
        replaces: When they correct an earlier correction again: its change id. Usually empty.
    """
    if not his_turn(ctx):
        return NOT_HIS_TURN
    receipt = await _change(memory.correct, old, correction, _list(passages), "voice", _call(ctx),
                            replaces.strip(), None, _now(ctx))
    if isinstance(receipt, str):
        return receipt
    _note(ctx, "correct", receipt)
    return memory.told(receipt)


@function_tool()
async def memory_forget(ctx: RunContext, what: str, passages: str = "") -> str:
    """When the user asks you to forget something: leave it out of the places you name. Their own notes are
    not changed (deleting it from their notes is a separate request, for a Worker). Then tell them in a
    few words.

    Args:
        what: The words of what to forget, as they are written, e.g. "the surprise party".
        passages: Where it is, as recall or a look showed it: the file and line, e.g.
            "Plans/Party.md:4" or "conversation-2026-10-02-3f9a2b:7" (a past conversation, by the name recall
            gives it), or the full row:<n>:<digest> from a look for a conversation message, comma-separated;
            for a whole past conversation, its name (an older one first gives back its messages, with one
            all:<mark> that names them all). Without them nothing is kept yet: a look comes back,
            for you to name them.
    """
    if not his_turn(ctx):
        return NOT_HIS_TURN
    receipt = await _change(memory.forget, what, _list(passages), "voice", _call(ctx), None, _now(ctx))
    if isinstance(receipt, str):
        return receipt
    _note(ctx, "forget", receipt)
    return memory.told(receipt)


@function_tool()
async def memory_undo(ctx: RunContext, change: str = "") -> str:
    """Undo a change to your memory when the user asks ("no, put that back"): the last one, or the one
    whose change id an earlier answer gave.

    Args:
        change: The change id, or empty for the last change.
    """
    if not his_turn(ctx):
        return NOT_HIS_TURN
    receipt = await _change(memory.undo, change, "voice", _call(ctx))
    if isinstance(receipt, str):
        return receipt
    _note(ctx, "undo", receipt)
    return memory.told(receipt)


TOOLS = [recall, memory_correct, memory_forget, memory_undo]
