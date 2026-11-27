"""The Subconscious at work: one round after every turn you take part in.

A round starts once the answer is out, so nothing in it can delay a word of it, and the cortices see what was really
answered. What runs, and how, is what the Subconscious page keeps (settings/subconscious.show), read again for every
round: a change on the page counts from the next turn, with nothing restarted.

  1. Cards with an empty "When" start at once: Emotional reaction (it moves Feelings) and Deep memory, as they come.
  2. If a card that is on has a "When", the coordinator reads the one merged prompt (settings/subconscious.merged) with
     the conversation, and names the cortices to run. It is a second copy of the Worker manager: the manager's own
     Worker type unless the page chose another, at its own thinking effort (low, as it comes).
  3. Each chosen cortex runs on its card's Worker type and effort, with the whole conversation: a run of its own on
     xPerfect (the Workers' own foundation, in a project of its own: never mixed with your jobs), or on this Mac's model.
     On this Mac one at a time, after her answer; when she begins to speak, or work of yours starts there, it stops, and
     starts again once she is quiet and your work is done.
  4. An unlinked cortex's thought goes to the conscious mind as soon as it has one, even while the coordinator is still
     choosing. Linked ones go together, once the coordinator has answered and all of them are done, or the wait limit
     ends; one that comes after that goes by itself. An answer of "nothing" is no thought, and a thought with the very
     words of one she already has in this conversation is not handed to her again.
  5. The conscious mind is told (the page's surfacing words) and decides whether to continue its thought or keep it in
     mind (brain/queen.py, Queen._surface, with the turn the thought was for; what her one word is asked: gate_words);
     how it ended comes back here (decided), so later parts see which of her thoughts were said and which kept.

What a part reads (no word of theirs cut without saying so): the turn that just ended, his words first and whole,
her answer whole when there is room and else its excerpt (its beginning, its end, and where all of it is); the thoughts
Viventium already had in this conversation, each marked said or kept; and the conversation before it for background,
every line at least as its excerpt, the newest whole, with where the rest is kept. A part with no tools is told plainly
that words not shown are out of its view. The Worker results she was given are in the conversation where she has them,
each as its own line ("Worker result: ..."), the same words her context holds (without them Confirmation bias
doubted a plan a Worker's result had already reported ready, and her one word let it reach him).

Where a part runs (`place`): a Worker type the card chose (claude, codex, grok-build: a run on that harness and its
sign-in, at that effort; on its route's limit, the next route once, as a job would, and the record names the one that
ran and the effort xPerfect accepted), this Mac's model (qwen-local; and on the Local profile every card, since Local is
everything on this Mac and nothing local moves online by itself; the card's place says so), or her quick helpers as the
profile sets them (core/helpers.py: this Mac on Local, asked as a part on this Mac; on Hybrid and Cloud Claude, then
OpenAI, then this Mac: the required order).

Your work comes first, and the Subconscious still thinks while it runs: a cortex run takes only a place on a harness that
is free (xPerfect's places for that harness, less the ones your work holds or is waiting for), never one your work is
waiting for, and it gives its place up as soon as your work needs it: when a job is handed off while the places are
full (Lane.make_room), and whenever xPerfect holds work of yours on that harness for room (Lane.wanted: the newest cortex
run there stops). Before, a cortex never took a harness's last free place: with two jobs on three places no part of
the Subconscious could run at all (its coordinator waited 120 s for room and had none). On this Mac's model a part waits
while work of yours runs there (running or queued), and stops when it starts (yours_here).
"""
import asyncio
import datetime as dt
import fcntl
import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from contextvars import Context, copy_context
from dataclasses import dataclass, field

from core import chatgpt_authorization as plan_auth
from settings import catalog
from settings import subconscious as page

log = logging.getLogger("rounds")

MAC = "qwen-local"  # the Worker type on this Mac
HELPERS = "helpers"  # her quick helpers, as the profile sets them
MANAGER = "manager"  # the coordinator follows the Worker manager
MAC_EFFORTS = ("none", "low", "medium", "high")
QUICK = ("", "none", "minimal")  # the efforts at which a helper answers without thinking first
THINK_ROOM = 6000  # tokens of thinking this Mac's model may use before its answer, when it thinks at all
HELPER_ROOM = 8000  # (the room core/helpers gives this Mac's helper when it thinks)
# What a cortex has in its run, told as it is (the host passes capabilities, it never invents them), and told last:
# Reality check on this Mac (no tools) once wrote "Verified:" and cited reviews it had never opened,
# with this said in the conversation part; said last in its own instructions, 0 of 2 runs claimed a check (2 of 2 before).
NO_TOOLS = ("In this run you have no tools: you cannot search, open a page or run anything. So nothing you hand back is "
            "verified: never write that you verified or checked something, and name no source you did not open. Say what "
            "you know and how sure you are, and say plainly that it is unchecked.")
CAN = {
    "worker": "In this run you have your harness's own tools on this Mac: you can search the web, open pages, read files "
              "and run code. Change nothing: no file, no message, no work. Name only sources you opened in this run.",
    "mac": NO_TOOLS,
    "helpers": NO_TOOLS,
}
# Said to a part with no tools when part of what it reads is an excerpt: the file named holds every word, but it cannot
# open it in this run (a path alone gives a tool-less model nothing).
UNSEEN = ("Where words above are marked as not shown here, they are out of your view in this run: if they could matter, "
          "say that part is not in view; never guess what it says.")
SEARCHED = ("The memory search was run for you: its finds are below, each with where it comes from, and you may name "
            "those. ")  # (said first, for a cortex whose card searches memory: it is the one tool its run had)


def can(where: "Place", searched: bool = False, unseen: bool = False) -> str:
    """What a cortex is told it has in this run, as it is."""
    told = CAN.get(where.kind, NO_TOOLS)
    return (SEARCHED if searched else "") + told + (" " + UNSEEN if unseen and where.kind != "worker" else "")


# What a part is given of the conversation. The turn that just ended is given whole up to its place's room: about a
# third of the smallest window it may run in (this Mac's model, 65,536 tokens: TURN_CHARS), so its own words, the memory
# finds, its thinking and its answer still fit; her quick helpers online only have the windows of online models
# (ONLINE_TURN_CHARS). Before, everything shared 16,000 characters kept from the newest line back, and a longer
# message from them was dropped whole: a 19,050-character message ending in a constraint reached the cortices as 68
# characters, the constraint gone.
TURN_CHARS = 100000
ONLINE_TURN_CHARS = 300000
BACKGROUND_CHARS = 16000  # the conversation before the turn, at most: every line at least as its excerpt
THOUGHT_CHARS = 2400  # a thought handed to her, at most (longer: its excerpt, with where all of it is)
HAD_CHARS = 8000  # her earlier thoughts a part is shown, the newest whole within this (and how many more there are)
WAIT = {"mac": 240.0, "helpers": 90.0, "worker": 900.0}  # one cortex's run, at most
CHOOSE_WAIT = {"mac": 90.0, "helpers": 30.0, "worker": 300.0}  # the coordinator's answer, at most
RESTARTS = 3  # a run on this Mac starts again at most this often when she begins to speak
ROOM_WAIT = 120.0  # how long a cortex waits for a free place on a harness your work is using
WORKER_GRACE = 30.0  # seconds past its own wait a run on a harness may take in all, its Worker's making included
WORK_LOOK = 1.0  # seconds between two looks at whether work of yours runs on this Mac's model
_mac_turns = asyncio.Lock()  # this Mac's model takes one part at a time


@dataclass
class Place:
    """Where one part runs: "mac" (this Mac's model), "helpers" (her quick helpers), "worker" (a run on a harness), or
    "none" (a Worker type that does not exist: it does not run)."""
    kind: str
    chose: str  # what was chosen for it: a Worker type id, or "helpers"
    effort: str  # the thinking effort it runs at (the one chosen, as that place takes it)
    harness: str = ""
    name: str = ""  # in plain words, for the record: "GPT-6.1 Sol", "this Mac", "quick helpers"
    note: str = ""  # why what runs is not exactly what was chosen (said where the choice is), "" when it is
    asks: str = ""  # the effort it is asked with when `effort` cannot say it (her quick helpers' own levels), else ""

    def word(self) -> dict:
        return {"kind": self.kind, "chose": self.chose, "effort": self.effort, "harness": self.harness, "name": self.name}


@dataclass
class Thought:
    cortex: str
    name: str
    text: str
    linked: bool
    ms: int
    where: str
    turn: int = 0  # the turn it was thought about (0: now); her side keeps it, so "they moved on" holds when it is late
    id: str = ""  # given when it is handed to her
    how: str = ""  # how it ended with her: "said", "kept", "rode" or "no answer"; "" until she decides
    refs: list = field(default_factory=list)  # the record's rows its round read ({"row", "digest"}): a thought made from
    # what he later asks to forget is not shown again (Subconscious.current)
    turn_id: str = ""  # the native message id; unlike the counter, it stays unique across a channel restart


@dataclass
class Turn:
    words: str  # what they said
    reply: str  # what she answered
    talk: list[tuple[str, str]]  # the conversation, oldest first: (role, words), role "user", "assistant" or RESULT (a
    # Worker result she was given, in its place); its last lines are this turn
    number: int  # her turn counter, to know later whether they spoke again since
    covers: list[int] = field(default_factory=list)  # earlier turns whose round this one is too (they came in a burst)
    count: int = 0  # how many of talk's last lines of theirs and hers are the turns that just ended (0: this turn's own);
    # the Worker results among them come with them
    refs: list = field(default_factory=list)  # each talk line's row in the record ({"row", "digest"}, None: not one of
    # the record): what he asks to forget meanwhile is taken out when each part is asked (Subconscious.standing)


def local(env=None) -> bool:
    """The Local profile: everything on this Mac, the cortices too. env: a profile's settings (the page's own read of
    them), else this process's."""
    return (env if env is not None else os.environ).get("WORKERS", "local") == "local"


def mac_effort(effort: str) -> str:
    """A thinking effort as this Mac's model takes it (none, low, medium, high)."""
    if effort in MAC_EFFORTS:
        return effort
    return "high" if effort in ("xhigh", "max") else "low" if effort == "minimal" else "none"


def _level(effort: str) -> str:
    return catalog.EFFORT.get(effort, effort or "its own usual one")


def exact_helpers() -> bool:
    """Whether her quick helpers take a card's exact effort (core/helpers.ask(effort=)). Until they do, each
    helper thinks on or off at its own level, and the record says that, never the card's word."""
    from core import helpers
    return "effort" in inspect.signature(helpers.ask_async).parameters


def place(runs_on: str, effort: str = "", env=None) -> Place:
    """Where a card's choice runs on this profile, and at what effort, said as it is."""
    if runs_on == HELPERS:
        if exact_helpers() or effort in QUICK:
            return Place("helpers", HELPERS, effort, name="quick helpers")
        return Place("helpers", HELPERS, "", name="quick helpers", asks=effort,
                     note="Thinking on, at each helper's own level (OpenAI medium, this Mac high).")
    option = catalog.option("hands", runs_on)
    if option is None:  # (never quietly somewhere else: configured is not executed)
        return Place("none", runs_on, "", name=runs_on or "nothing", note="That Worker type does not exist.")
    if option["where"] == "mac" or local(env):
        mac, notes = mac_effort(effort), []
        if option["where"] != "mac":
            notes.append("On Local every cortex thinks on this Mac.")
        if effort and effort != mac:
            notes.append(f"This Mac has no {_level(effort)}: " + ("thinking is off." if mac == "none" else f"it thinks at {_level(mac)}."))
        return Place("mac", runs_on, mac, name="this Mac", note=" ".join(notes))
    efforts = option.get("efforts", [])
    exact = effort if effort in efforts else option.get("effort", "")
    note = f"{option['model']} has no {_level(effort)}: it thinks at {_level(exact)}." if effort and exact != effort else ""
    return Place("worker", runs_on, exact, harness=option["harness"], name=option["model"], note=note)


def coordinator_place(coordinator: dict, env=None) -> Place:
    """The coordinator: the Worker manager's own Worker type unless the page chose another, at its own effort."""
    env = env if env is not None else os.environ
    chose = coordinator.get("runs_on") or MANAGER
    if chose == MANAGER:
        harness = env.get("MANAGER_PROFILE") or env.get("WORKER_PROFILE", "")
        chose = next((o["id"] for o in catalog.PARTS["hands"]["options"]
                      if o["where"] == "plan" and o["harness"] == harness), MAC)
    return place(chose, coordinator.get("effort") or "low", env)


def _local_recall(cortex: dict, env=None) -> bool:
    env = os.environ if env is None else env
    return cortex.get("searches") == "memory" and env.get("MEMORY_CORTEX") == "mac"


def cortex_place(cortex: dict, env=None) -> Place:
    runs_on = MAC if _local_recall(cortex, env) else cortex["runs_on"]
    return place(runs_on, cortex["effort"], env)


def turn_room(where: Place) -> int:
    """How much of the turn that just ended a part on this place is given whole: this Mac's window bounds it unless the
    part runs only online (her quick helpers with no fallback on this Mac)."""
    if where.kind == "helpers":
        from core import helpers
        return ONLINE_TURN_CHARS if "mac" not in {kind for kind, _ in helpers.routes()} else TURN_CHARS
    return TURN_CHARS


# -- What a part reads --

RESULT = "worker"  # a Worker result she was given (the record's own role for it, core/relationship)
LABEL = {"assistant": "Viventium", "user": "They", RESULT: "Worker result"}  # (as her context says it: brain/queen.py)


def _line(role: str, words: str) -> str:
    return f"{LABEL.get(role, 'They')}: {words}"


def said(talk: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Only their words and hers: the conversation without the Worker results among it."""
    return [(role, words) for role, words in talk if role != RESULT]


def _start(talk: list[tuple[str, str]], lines: int) -> int:
    """Where the last `lines` lines of theirs and hers begin in talk: the Worker results among them are inside, one
    just before them is not."""
    i, seen = len(talk), 0
    while i > 0 and seen < lines:
        i -= 1
        seen += talk[i][0] != RESULT
    return i


def last_lines(talk: list[tuple[str, str]], lines: int) -> list[tuple[str, str]]:
    """The last `lines` lines of theirs and hers, with the Worker results among them (a window that results never
    shorten)."""
    return talk[_start(talk, lines):]


def _shown(talk: list[tuple[str, str]], room: int, theirs_first: bool = False, seen: list | None = None,
           at: int = 0) -> tuple[str, bool]:
    """The lines a part is given, oldest first, and whether that is all of them, whole (core/relationship.fit): every
    line keeps at least its excerpt (its beginning, its end, and where all of it is); the room left goes to their words
    first when `theirs_first` (the turn that just ended: his words come first and whole, her long answer is the one
    shortened), then from the newest back. When even that does not fit, the oldest lines go, never one from the
    middle. seen: filled with the index in talk (plus `at`) of every line shown, whole or as its excerpt."""
    from core import relationship
    kept = [(i, role, words.strip()) for i, (role, words) in enumerate(talk) if words.strip()]
    lines = [(role, words) for _, role, words in kept]
    room -= sum(len(_line(role, "")) + 1 for role, _ in lines)
    first = [i for i in reversed(range(len(lines))) if lines[i][0] == "user"] if theirs_first else []
    fitted = relationship.fit([words for _, words in lines], max(room, 0), first)
    shown = [_line(role, text) for (role, _), text in zip(lines, fitted) if text is not None]
    if seen is not None:
        seen.extend(at + i for (i, _, _), text in zip(kept, fitted) if text is not None)
    return "\n".join(shown), all(text == words for (_, words), text in zip(lines, fitted))


def transcript(talk: list[tuple[str, str]], room: int = BACKGROUND_CHARS, theirs_first: bool = False,
               seen: list | None = None, at: int = 0) -> str:
    """The conversation as a part reads it, oldest first, within `room` (see _shown)."""
    return _shown(talk, room, theirs_first, seen, at)[0]


def split(talk: list[tuple[str, str]], count: int = 0) -> tuple[list, list]:
    """The conversation before the turn that just ended, and that turn (their words, one message or several, and her
    answer). count: how many of the last lines of theirs and hers are the turns that just ended (several, after a
    burst). A Worker result told while they spoke is in the turn, in its place; one she had before their words is
    background (it is never the start of the turn, and never pushes their words out of it)."""
    if not count:
        lines = said(talk)
        count = 1 if lines and lines[-1][0] == "assistant" else 0
        while count < len(lines) and lines[-1 - count][0] == "user":
            count += 1
    i = _start(talk, count)
    return talk[:i], talk[i:]


def ended(talk: list[tuple[str, str]]) -> int:
    """How many lines of theirs and hers the turn that just ended has (split's own count)."""
    return len(said(split(talk)[1]))


def _marked(thought: Thought) -> str:
    return "said" if thought.how == "said" else "kept in mind, not said"


def _had_lines(had: list | tuple, room: int = HAD_CHARS, prefix: str = "- ", seen: list | None = None) -> str:
    """Her earlier thoughts, oldest first, each marked said or kept: the newest whole within `room`, and how many older
    ones there are besides. seen: filled with each thought shown."""
    lines, size = [], 0
    for t in reversed(list(had)):
        line = f"{prefix}{t.name} ({_marked(t)}): {t.text}"
        if lines and size + len(line) > room:
            break
        lines.append(line)
        size += len(line) + 1
        if seen is not None:
            seen.append(t)
    more = len(had) - len(lines)
    return "\n".join(([f"({more} older ones are not listed.)"] if more else []) + list(reversed(lines)))


def conversation(talk: list[tuple[str, str]], subject: str, had: list | tuple = (), room: int = TURN_CHARS,
                 count: int = 0, seen: list | None = None, seen_had: list | None = None) -> str:
    """The conversation as a part is given it: what came before, for background, the thoughts Viventium already had in
    it, then the turn that just ended, on its own, his words first and whole. In one block, with "the last two lines are
    the turn that just ended", Qwen 3.6 drifted to older turns: the coordinator missed a wrong
    number (3 of 4 caught) and Reality check, asked about a plan, corrected an older answer; given the turn on its own,
    4 of 4 and 3 of 3 (tests/subconscious_eval.py). seen, seen_had: filled with the index in talk of every line it shows
    and with every earlier thought it shows (what a thought made from it depends on)."""
    from core import life
    before, turn = split(talk, count)
    parts = []
    if before:
        text, complete = _shown(before, BACKGROUND_CHARS, seen=seen)
        parts.append("The conversation before it, for background" + (
            "" if complete else f" (every message is kept, word for word, as it stands now, in {life.record_where()})")
            + f":\n{text}")
    if had:
        parts.append("Viventium's own earlier thoughts in this conversation, each marked said or kept in mind:\n"
                     + _had_lines(had, seen=seen_had))
    return "\n\n".join(parts + [f"The turn that just ended, {subject}:\n"
                                 f"{transcript(turn, room, theirs_first=True, seen=seen, at=len(before))}"])


def _unseen(text: str) -> bool:
    from core import relationship
    return relationship.EXCERPT_MARK in text


def picked(text: str, asked: list[dict]) -> list[str]:
    """The cortices the coordinator named, by the name in square brackets its prompt asks for (its id, or its name):
    each in its own brackets ("[numbers] [red-team]", as Qwen writes it) or one bracketed list ("[numbers, red-team]",
    as GPT-6.1 Sol does: read as one name, every such turn ran nothing)."""
    ids = {c["id"] for c in asked}
    names = {c["name"].strip().lower(): c["id"] for c in asked}
    out = []
    for token in re.findall(r"\[([^\[\]\n]{1,400})\]", text or ""):
        for part in token.split(","):
            key = part.strip().strip("'\"` ").lower()
            chosen = key if key in ids else names.get(key)
            if chosen and chosen not in out:
                out.append(chosen)
    return out


def thought_of(text: str) -> str:
    """A cortex's answer as a thought: "" when it handed back nothing (an empty answer, or the one word "nothing"). A
    long one is handed over as its excerpt, with where all of it is (never cut without saying so)."""
    from core import relationship
    words = (text or "").strip()
    bare = words.strip(" \n\t.!*_`\"'()[]").lower()
    return "" if not bare or bare == "nothing" else relationship.excerpt(words, THOUGHT_CHARS)


def _context(where: Place, talk: list[tuple[str, str]], found: list[dict] | None, had: list | tuple = (),
             count: int = 0, seen: list | None = None, seen_had: list | None = None) -> str:
    from core import life
    parts = []
    if found is not None:  # (a summary by its date and short id, never its file's name: core/life.name_of)
        parts.append(("What the memory search found in the person's Life, closest in meaning first, each with where it "
                      "comes from:\n\n" + "\n\n".join(f"[{n}] {life.name_of(f['path'])} (line {f['line']}):\n{f['text']}"
                                                     for n, f in enumerate(found, 1)))
                     if found else "The memory search found nothing new.")
    parts.append(f"It is now {dt.datetime.now().strftime('%A %d %B %Y, %H:%M')}.")
    try:
        # (what he corrected, in words: it holds over what is found. His forgets only for a part run on a Worker: it can
        # read his files on this Mac as they are, and the list is its only guard (it is told never to hint at it). A
        # part on this Mac or her helpers reads only what is shown here, which leaves them out: never told, since
        # nothing of a forget reaches her, not even that there was one.)
        if note := life.changes_note(forgets=where.kind == "worker"):
            parts.append(note)
    except life.Unreadable as e:
        parts.append(f"(What the user changed in their memory cannot be read: {e}.)")
    parts.append(conversation(talk, "your subject", had, turn_room(where), count, seen, seen_had))
    return "\n\n".join(parts)


def gate_words(told: str, talk: list[tuple[str, str]], thoughts: list, earlier: list | tuple = ()) -> str:
    """What her one-word question is asked when thoughts reach her (Queen._continue, brain/modes/surfacing_gate.md):
    what she is told about them, the recent conversation (before, each line was cut at 400 characters, so a caution
    she had already given further on looked new), the thoughts she already had in this conversation, each marked said
    or kept (one she said is no news; one she kept may matter now), and the thoughts now."""
    parts = [f"What Viventium is told about its own background thoughts:\n{told}",
             f"Its recent conversation:\n{transcript(talk) or '(none yet)'}"]
    if earlier:
        parts.append("Its earlier background thoughts in this conversation, each marked said or kept in mind:\n"
                     + _had_lines(earlier, prefix=""))
    parts.append("Its background thoughts now:\n" + "\n\n".join(f"{t.name}: {t.text}" for t in thoughts))
    return "\n\n".join(parts) + "\n\nOne word (say or keep):"


# -- Asking a part, where it runs --

def _said_now(user) -> str:
    """A part's words to read: made now when given as a callable (a round's parts: as the conversation stands by his
    change list at the moment it is asked, after any wait for a place or for her), else as given."""
    return user() if callable(user) else user


async def ask(where: Place, system: str, user, *, name: str, max_tokens: int, wait: float, json_out: bool = False,
              busy=None, quiet=None, ran: dict | None = None, beside: bool = False, still=None) -> tuple[str, str]:
    """One answer from where a part runs: (its text, how it went: "ok", or why not). `user`: its words, or a callable
    that makes them when it is really asked (_said_now); still(): whether what those words showed still stands (on
    a Worker it is asked again right after the dispatch: no, its run stops there). `ran`, when given, is filled with
    where it really ran and at what effort: the route a backup took, the helper that answered, the effort xPerfect
    accepted (the record says what ran, never only what was chosen). beside: one of a round's cortices, which run
    side by side (on a Worker: a run a goal of its own owns, so xPerfect's one-at-a-time fence holds none of them)."""
    ran = ran if ran is not None else {}
    ran.clear()
    ran.update(name=where.name, effort=where.effort)
    if where.kind == "none":
        return "", "no_such_worker"
    if where.kind == "mac":
        ran.update(route="mac", model=os.environ.get("MEMORY_MODEL") or "qwen3.6:latest")
        return await _mac(where, system, user, max_tokens, wait, json_out, busy, quiet)
    if where.kind == "helpers":
        if _helpers_here():  # her helpers are this Mac's model alone (Local): asked as a part on this Mac, so it waits
            # for her and for your work and stops when either begins, as every other part there does
            return await _mac_helper(where, system, user, max_tokens, wait, json_out, busy, quiet, ran)
        return await _helpers(where, system, user, max_tokens, wait, json_out, busy, ran, quiet)
    return await _worker(where, system, user, name, wait, busy, quiet, ran, beside, still)


def gives_way(where: "Place") -> bool:
    """Whether a part asked here waits for her and stops when a turn of his begins: only one on this Mac's own model
    server, which her reply shares (this Mac's model, or her helpers when they are this Mac's alone, Local). Her online
    helpers never do; a run on a Worker keeps its own rule (_worker)."""
    return where.kind == "mac" or (where.kind == "helpers" and _helpers_here())


def _helpers_here() -> bool:
    from core import helpers
    return {kind for kind, _ in helpers.routes()} == {"mac"}


async def _mac_helper(where: Place, system: str, user, max_tokens: int, wait: float, json_out: bool, busy, quiet,
                      ran: dict) -> tuple[str, str]:
    """This Mac's helper asked as a part on this Mac, as core/helpers asks it (its room, temperature 0): at the card's
    exact effort once the helpers take one, else thinking on at high, or off."""
    card = where.asks or where.effort
    effort = card if exact_helpers() else ("none" if card in QUICK else "high")
    ran.update(name="this Mac", effort=effort or "none", route="mac",
               model=os.environ.get("MEMORY_MODEL") or "qwen3.6:latest")
    return await _mac(Place("mac", HELPERS, effort or "none", name="this Mac"), system, user, max_tokens, wait, json_out,
                      busy, quiet, room=HELPER_ROOM, temperature=0.0)


async def _until(held) -> None:
    while not held():
        await asyncio.sleep(0.2)


_work_seen = [0.0, False]  # (when it was last looked at, what was seen)


def yours_here() -> bool:
    """Whether work of yours runs on this Mac's model now (running or queued): every such job on the Local profile, or
    the job on this Mac's place beside online ones (one GPU, and an optional thought had queued a job's model calls
    for tens of seconds). A part there waits for it, and stops when it starts. Looked at once a second at most."""
    now = time.monotonic()
    if now - _work_seen[0] >= WORK_LOOK:
        _work_seen[:] = [now, _work_on_this_mac()]
    return _work_seen[1]


def _working(job: dict) -> bool:
    """Running or queued: core/jobs.working where it is there, else the same test here. A
    question waiting for his answer, a job whose xPerfect is unreachable and a result are not work running."""
    from core import jobs
    if hasattr(jobs, "working"):
        return jobs.working(job)
    return "result" not in job and not job.get("unreachable_since")


def _work_on_this_mac() -> bool:
    from brain import xperfect
    from core import jobs
    try:  # (read only: jobs.peek when there is one; open_jobs() writes the file back under its lock)
        held = list(jobs.peek().values()) if hasattr(jobs, "peek") else list(json.loads(jobs.FILE.read_text()).values())
    except (OSError, ValueError, AttributeError):
        return False
    return any(_working(j) and (local() or xperfect.on_this_mac(j)) for j in held)


async def _held_off(held, deadline: float) -> bool:
    """Wait while she is busy or your work runs on this Mac; False when the wait limit came first."""
    while held():
        if time.monotonic() > deadline - 1:
            return False
        await asyncio.sleep(0.25)
    return True


async def _mac(where: Place, system: str, user, max_tokens: int, wait: float, json_out: bool, busy,
               quiet, room: int = THINK_ROOM, temperature: float = 0.3) -> tuple[str, str]:
    """This Mac's model (the Workers' own server), one part at a time, never while she speaks or your work runs there.
    However it ends (an answer, she begins to speak, your work starts, the wait runs out, or this part is stopped), its
    request and its watcher are stopped and awaited, and its client closed."""
    url = os.environ.get("MEMORY_URL")
    if not url:
        return "", "no_place"
    import openai
    body = {"model": os.environ.get("MEMORY_MODEL") or "qwen3.6:latest",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": ""}],
            "max_tokens": max_tokens + (room if where.effort != "none" else 0), "temperature": temperature,
            "extra_body": {"reasoning_effort": where.effort or "none", "keep_alive": -1},
            **({"response_format": {"type": "json_object"}} if json_out else {})}
    deadline = time.monotonic() + wait

    def held() -> bool:  # she is thinking or speaking, a turn of theirs came in, or your work runs on this Mac
        return (busy is not None and busy()) or yours_here()

    async with _mac_turns:
        for _ in range(RESTARTS + 1):
            if quiet is not None:
                await quiet()  # after her answer, never during it
            if not await _held_off(held, deadline):  # (a turn of theirs just came in, or your work: they go first; it
                return "", "your_work" if yours_here() else "foreground_turn"  # gave way to them the whole wait)
            left = deadline - time.monotonic()
            if left <= 1:
                return "", "timeout"
            client = openai.AsyncOpenAI(base_url=url, api_key="local", max_retries=0, timeout=left)
            body["messages"][1]["content"] = _said_now(user)  # (as it stands now: after her answer and his work)
            call = asyncio.ensure_future(client.chat.completions.create(**body))
            watch = asyncio.ensure_future(_until(held))
            try:
                done, _ = await asyncio.wait({call, watch}, timeout=left, return_when=asyncio.FIRST_COMPLETED)
                if call in done:
                    try:
                        reply = call.result()
                    except Exception as e:  # noqa: BLE001 (a model that cannot be asked: no thought)
                        return "", type(e).__name__
                    return (reply.choices[0].message.content or "") if reply.choices else "", "ok"
                if watch not in done:
                    return "", "timeout"
            finally:  # (she began to speak, your work began, too long, or stopped: its words stop with the connection)
                for task in (call, watch):
                    task.cancel()
                await asyncio.gather(call, watch, return_exceptions=True)
                await client.close()
        return "", "your_work" if yours_here() else "she_kept_talking"


def _own_level(route: str, think: bool) -> str:
    """The level a helper thinks at on its own (core/helpers without an exact effort), said as it is."""
    if not think:
        return "none" if route == "mac" else os.environ.get("HELPERS_OPENAI_EFFORT", "low") if route == "openai" else "none"
    return {"openai": "medium", "mac": "high", "claude": "thinking on (its own budget)"}.get(route, "thinking on")


@plan_auth.unattended
async def _helpers(where: Place, system: str, user, max_tokens: int, wait: float, json_out: bool, busy,
                   ran: dict, quiet=None) -> tuple[str, str]:
    """Her quick helpers, in the profile's order: the online ones first (core/helpers, only those), and when none of
    them answered, this Mac's as a part on this Mac (_mac_helper: it waits for her and for your work, and stops when
    either begins), never through core/helpers, where its fallback could not be stopped. The online ones are asked at
    once and finish what they started, their answer counted: they share nothing with her reply on this Mac, so they
    never give way to her (before, the next words cancelled them, Feelings' appraisal and Deep memory among them,
    and they were never asked again: on a flowing call about one reaction in six to ten completed). Giving way
    is this Mac's own model's (_mac), whose server her reply shares."""
    from core import helpers
    deadline = time.monotonic() + wait  # (one limit for the whole part: its wait for her, then the helpers' answer)
    chain = helpers.routes()
    online = [route for route in chain if route[0] != "mac"]
    card = where.asks or where.effort
    if online:
        think = card not in QUICK
        exact = exact_helpers()
        kwargs = {"effort": card} if exact and card else {}
        call = asyncio.create_task(helpers.ask_async([{"role": "system", "content": system},
                                                      {"role": "user", "content": _said_now(user)}],
                                    max_tokens=max_tokens, wait=max(1.0, deadline - time.monotonic()),
                                    json_out=json_out, think=think, only=online, **kwargs))
        try:  # (his turn, or work of his on this Mac, never stops it: it finishes within its own wait)
            done, _ = await asyncio.wait({call}, timeout=max(0, deadline - time.monotonic()))
            if not done:
                return "", "timeout"
            answer = call.result()
        finally:
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
        # (the helper that answered and those passed over before it, as they were: a receipt tells what ran)
        ran.update(route=answer.route, model=answer.model, tried=[list(step) for step in answer.tried])
        if answer.route:
            effort = (card or "none") if exact else _own_level(answer.route, think)
            if answer.route == "claude" and answer.model == helpers.CLAUDE_OPUS:
                effort = helpers.claude_effort(think, kwargs.get("effort", ""))
            elif answer.route == "openai":
                effort = helpers.openai_effort(answer.model, think, kwargs.get("effort", ""))
            ran.update(name="quick helpers: " + {"claude": "Claude", "openai": "OpenAI", "xai_plan": "Grok"}.get(answer.route, answer.route)
                       + (f" ({answer.model})" if answer.model else ""), effort=effort)
            return answer.text, "ok"
    if any(kind == "mac" for kind, _ in chain) and os.environ.get("MEMORY_URL"):
        if online:  # (his online helpers gave nothing: this Mac's answers as their backup, and the receipt says so)
            ran.update(route="mac", model=os.environ.get("MEMORY_MODEL") or "qwen3.6:latest")
        return await _mac_helper(where, system, user, max_tokens, max(1.0, deadline - time.monotonic()), json_out, busy,
                                 quiet, ran)
    return "", "unavailable"


_thinking = None  # this process's client for the Subconscious' own xPerfect project


def _xp():
    global _thinking
    if _thinking is None:
        from brain.xperfect import THINKING_TITLE, XPerfect
        _thinking = XPerfect(title=THINKING_TITLE)
    return _thinking


def _plan_option(harness: str) -> dict | None:
    return next((o for o in catalog.PARTS["hands"]["options"] if o.get("harness") == harness and o["where"] == "plan"), None)


def _effort_on(harness: str, effort: str) -> str:
    """The effort as another harness takes it (a backup route): the same level when it has it, else its own usual one."""
    option = _plan_option(harness)
    if option is None:
        return ""
    return effort if effort in option.get("efforts", []) else option.get("effort", "")


async def _worker(where: Place, system: str, user, name: str, wait: float, busy, quiet,
                  ran: dict, beside: bool = False, still=None) -> tuple[str, str]:
    """A run of its own on a harness (and its sign-in), at the card's effort; on its route's limit, the next route once.
    The whole run, from making its Worker to its answer, keeps to `wait`; a run that outlives it is interrupted before
    this returns (it never runs on, on his sign-in, holding a place his next job needs). No room within its time
    (xPerfect's typed answer, PlaceBusy): no thought, recorded with what was full. beside (a round's cortices): each a
    run a goal of its own owns (XPerfect.think(owned=True)), so the cards the coordinator named run side
    by side, as designed, instead of in turn at xPerfect's one-at-a-time fence (a second waited up to 120 s, then
    had no room). Its cost on Hybrid: xPerfect wakes the coordinator once when each such run ends, one short report."""
    from brain import xperfect
    try:
        xp = _xp()
        order = await xp.routes([where.harness, *xperfect.backups(where.harness)])
    except Exception as e:  # noqa: BLE001 (no xPerfect here: no thought)
        return "", f"no_xperfect:{type(e).__name__}"
    busy_place = getattr(xperfect, "PlaceBusy", None)  # (xPerfect's typed answer, where it is there)
    why = "no_route"
    deadline = time.monotonic() + wait
    for token in order[:2]:
        if not await _held_off(lambda: busy is not None and busy(), deadline):
            return "", "timeout"
        if token == xperfect.LOCAL:  # the Worker on this Mac stands by last: this Mac's model
            ran.update(name="this Mac", effort=mac_effort(where.effort))
            text, how = await _mac(Place("mac", MAC, mac_effort(where.effort), name="this Mac"), system, user, 900,
                                   WAIT["mac"], False, busy, quiet)
            if how == "ok":  # (a route is named as the one that ran only once it answered)
                ran.update(route="mac", model=os.environ.get("MEMORY_MODEL") or "qwen3.6:latest")
            else:
                ran.setdefault("tried", []).append(["mac", how])
                ran["route"] = ""
            return text, how
        harness, account = xperfect.parts(token)
        looked = time.monotonic()
        claim = await LANE.wait_for_room(harness)  # (its place, taken under the lane's lock)
        ran["room_ms"] = ran.get("room_ms", 0) + round((time.monotonic() - looked) * 1000)  # (apart from its run's time)
        if not claim:
            return "", "no_room"
        effort = _effort_on(harness, where.effort)
        ran.update(name=(_plan_option(harness) or {}).get("model", harness), effort=effort, route="")

        def failed(why: str) -> tuple[str, str]:  # (tried, never named as the one that answered)
            ran.setdefault("tried", []).append([token, why])
            ran["route"] = ""
            return "", why
        owned = {"owned": True} if beside and "owned" in inspect.signature(xp.think).parameters else {}
        if owned:
            ran["owned"] = True
        worker: list[str] = []
        gave_way: list[str] = []
        forgotten: list[bool] = []

        def began(w: str, h=harness, c=claim) -> bool:  # (its Worker exists: False, its place was taken back meanwhile)
            worker.append(w)
            if not LANE.started(h, w, c):
                gave_way.append(w)
                return False
            return True

        def dispatched(w: str, run: str = "", h=harness) -> bool:  # (the one rule: right after the dispatch, its line
            if not LANE.dispatched(h, w, run):                         # looked at again, its run id kept on it)
                gave_way.append(w)
                return False
            if still is not None and not still():  # (what its words showed was forgotten while it was being set up)
                forgotten.append(True)
                return False
            return True

        async def give_way(harness=harness) -> None:  # (xPerfect holds work of yours there for room: the newest goes,
            while not (worker and LANE.gives_way(harness, worker[0])):  # its line marked taken back first, so a stop
                await asyncio.sleep(WORK_LOOK)                           # that fails is sent again by the sweep)
            gave_way.append(worker[0])
            LANE.revoke(harness, worker[0])
            await xp.interrupt(worker[0])
        watch = asyncio.ensure_future(give_way())
        outcome: dict = {}
        try:
            outcome = await asyncio.wait_for(
                xp.think(name, lambda: f"{system}\n\n{_said_now(user)}", harness, effort, account, wait=wait,
                         started=began, **owned, **({"dispatched": dispatched} if "dispatched" in
                                                    inspect.signature(xp.think).parameters else {})), wait + WORKER_GRACE)
            if worker and LANE.revoked(harness, worker[0]):  # (taken back for a job while it ran: make_room stopped it)
                gave_way.append(worker[0])
        except (asyncio.TimeoutError, TimeoutError):
            if worker:
                await xp.interrupt(worker[0])
            return failed("your_work" if gave_way else "timeout")
        except Exception as e:  # noqa: BLE001
            if gave_way:
                return failed("your_work")
            if busy_place is not None and isinstance(e, busy_place):
                return failed(f"place_busy:{getattr(e, 'capacity_class', '') or 'full'}")
            return failed(type(e).__name__)
        finally:
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)
            # (over by its run's own state in xPerfect, never by the outcome alone: a route cooling down returns
            # "failed" while its run still waits there, and it would start once the cooldown lifts)
            over = (outcome.get("run_state") or outcome.get("state")) in ("completed", "failed", "cancelled",
                                                                          "interrupted", "none")
            if not worker:
                LANE.ended(harness, claim)  # (no Worker was made: its claim goes)
            elif outcome.get("closed") is True or (over and outcome.get("closed") is not False):
                LANE.ended(harness, worker[0])  # (xPerfect says its run is over and its Worker closed)
            else:  # (its run over but its close refused: no place held, the close tried again; or its stop not
                LANE.ended(harness, worker[0], confirmed=False, over=over)  # confirmed: the line holds its place)
                try:
                    await LANE.sweep(only=worker[0])
                except Exception as e:  # noqa: BLE001
                    log.debug("lane: %s left for the sweep: %s", worker[0], type(e).__name__)
        if forgotten:  # (what it read was forgotten before it started: stopped, no thought)
            return failed("forgotten")
        if gave_way:  # (its place went to your work: no thought this turn, and the record says why)
            return failed("your_work")
        if outcome.get("effort"):  # (the effort xPerfect accepted the run at, when it says)
            ran["effort"] = outcome["effort"]
        if outcome.get("usage"):
            ran["usage"] = outcome["usage"]
        if outcome["state"] == "completed" and outcome.get("unframed"):  # (its model's own markup in its answer, on this
            # Mac: its turn broke off, so what came back is no thought of hers)
            ran["unframed"] = outcome["unframed"]
            return failed("unframed")
        if outcome["state"] == "completed":
            ran.update(route=token, model=outcome.get("model") or (_plan_option(harness) or {}).get("model", harness))
            return outcome["output_text"], "ok"
        why = outcome["failure_class"] or outcome["state"]
        failed(why)  # no route answered yet; failure alone is not fallback use
        if outcome["failure_class"] not in xperfect.ROUTE_DOWN:
            break
    return "", why


CLAIM = "claim-"  # a place taken under the lane's lock for a run whose Worker is still being made (Lane.claim)
OWN_WORKER = {"host_worker_busy"}  # xPerfect's class for a run waiting for its own Worker (not for a place)
SWEEP_EVERY = 30.0  # seconds between two sweeps of runs a gone process left (Lane.keep_swept)


class Lane:
    """Your work comes first, and the Subconscious still thinks beside it. A cortex run takes a place on a harness only
    when one is free: xPerfect's places for that harness (xperfect.slots), less the cortex runs there and the work of
    yours that holds one or is in line for one; never while xPerfect holds work of yours there for room (wanted).
    Counted for every process at once (a call and Telegram share one Mac's places): the runs are kept in one small file,
    each line with the process that runs it, and every count and change is made under its one lock.

    One rule takes a place back for your work: make_room marks the newest runs' lines taken back (revoked) and stops
    their runs; and every run, right after xPerfect's dispatch returns, looks again at its own line under the lock
    (dispatched): taken back, it stops its run there. So a place taken back at any moment, before or after its Worker
    exists, before or after the dispatch, is given up: before the dispatch nothing runs, after it one of the two stops
    lands on a run that exists. A line goes only once xPerfect has confirmed its run stopped (its Worker closed, or no
    longer known): until then it holds its place, and a process that is gone (a crash, a restart) leaves it for the
    sweep, which runs on a timer (keep_swept) and before every claim and hand-off. Its newest run also gives way, one at
    a time, while xPerfect holds work of yours on that harness for room (gives_way).
    Before, a cortex run never took a harness's last free place: with two jobs on three places nothing of the
    Subconscious could run (the coordinator waited ROOM_WAIT and had no room, while a place stood free)."""

    @staticmethod
    def file():
        from core.state import STATE_ROOT
        return STATE_ROOT / "core" / "subconscious-lane.json"

    def _edit(self, change=None) -> list[dict]:
        """The runs going on now, under the file's lock; `change` may edit the list (it is saved, his alone)."""
        from core.state import private_file
        path = self.file()
        with private_file(path.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                runs = json.loads(path.read_text())
            except (OSError, ValueError):
                runs = []
            runs = _orphans_marked(runs)
            if change is not None:
                change(runs)
            tmp = path.with_suffix(".tmp")
            with private_file(tmp, "w") as f:
                f.write(json.dumps(runs))
            tmp.replace(path)
            return list(runs)

    def _runs(self) -> list[dict]:
        """The runs going on now, read only (nothing written, no lock: the file is replaced whole), for a look each
        second."""
        try:
            runs = json.loads(self.file().read_text())
        except (OSError, ValueError):
            return []
        return _orphans_marked(runs)

    async def sweep(self, only: str = "") -> list[str]:
        """Every line still owed a stop or a close, whoever owns it (only: that one Worker):
          - taken back (revoked) or left by a gone process (orphan): its stop is sent again, every sweep, until xPerfect
            says its run is over (its run's own state, by the run id the line keeps); then it holds no place (ended);
          - its run over (ended), or a gone process's with no run known: its Worker's close is tried again, and the line
            goes once it is closed (or xPerfect no longer knows it).
        A line whose run is over frees its place even while its close is refused. Returns the lines that went. xPerfect
        away: everything stays as it is, for the next sweep."""
        gone = []
        for r in [r for r in self._runs() if (r.get("orphan") or r.get("revoked") or r.get("ended"))
                  and not str(r.get("worker", "")).startswith(CLAIM) and (not only or r.get("worker") == only)]:
            try:
                xp = _xp()
                over = bool(r.get("ended"))
                if not over:
                    await xp.interrupt(r["worker"])  # (again, whoever owns it: a stop that failed is never left)
                    over = bool(r.get("run")) and await _run_over(xp, r["run"])
                    if over:
                        self._mark(r["worker"], ended=True)
                if (over or (r.get("orphan") and not r.get("run"))) and (
                        await xp.close(r["worker"]) or await _unknown(xp, r["worker"])):
                    self.ended(r["harness"], r["worker"])
                    gone.append(r["worker"])
            except Exception as e:  # noqa: BLE001 (xPerfect away: it keeps its line, for the next sweep)
                log.debug("lane: %s not swept: %s", r.get("worker"), type(e).__name__)
        return gone

    def owed(self) -> bool:
        """Whether any line is owed a stop or a close (what the sweep looks at)."""
        return any((r.get("orphan") or r.get("revoked") or r.get("ended")) and not str(r.get("worker", "")).startswith(CLAIM)
                   for r in self._runs())

    def _mark(self, worker: str, **fields) -> None:
        def mark(runs: list[dict]) -> None:
            for r in runs:
                if r["worker"] == worker:
                    r.update(fields)
        self._edit(mark)

    def keep_swept(self) -> None:
        """The sweep on a timer, one per process: started by the process's main thread's own loop, which owns it, and
        never started or replaced from another thread's loop (her Feelings ask a part on a thread of their own, in a loop
        of their own); every SWEEP_EVERY seconds while a line is owed a stop or a close (owed)."""
        global _sweeper
        if threading.current_thread() is not threading.main_thread():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        with _sweeper_lock:
            if _sweeper is not None and not _sweeper.done() and not _sweeper.get_loop().is_closed():
                return

            async def every() -> None:
                while True:
                    await asyncio.sleep(SWEEP_EVERY)
                    try:
                        if self.owed():
                            await self.sweep()
                    except Exception as e:  # noqa: BLE001 (never in anyone's way: the next period sweeps again)
                        log.debug("lane: sweep failed: %s", type(e).__name__)
            _sweeper = loop.create_task(every(), name="lane-sweep")

    def running(self, harness: str) -> list[str]:
        """Every line on this harness (its Worker id or its claim)."""
        return [r["worker"] for r in self._edit() if r["harness"] == harness]

    def holding(self, harness: str) -> int:
        """How many places the lines on this harness hold: every one whose run is not over (taken back or not)."""
        return sum(1 for r in self._edit() if r["harness"] == harness and not r.get("ended"))

    @staticmethod
    def _yours(harness: str) -> list[dict]:
        """Work of yours on this harness online that holds a place or is in line for one (core/jobs.working: a question
        waiting for his answer, an unreachable job and a result hold none). A job on this Mac's own place of a mix has
        its own places (yours_here)."""
        from brain import xperfect
        from core import jobs
        return [j for j in jobs.peek().values() if isinstance(j, dict) and not j.get("finished") and _working(j)
                and not xperfect.on_this_mac(j) and runs_on(j) == harness]

    @classmethod
    def _jobs(cls, harness: str) -> int:
        return len(cls._yours(harness))

    @classmethod
    def wanted(cls, harness: str) -> bool:
        """Whether xPerfect holds work of yours on this harness for room now: its own typed wait, kept with the job as
        `waiting` (Queen._waiting, from settle), with the harness it was said for. No cortex run starts there then, and
        those running give way. A wait said on another harness (the one a job fell back from) or for its own Worker
        (xPerfect's class host_worker_busy: a follow-up behind that Worker's run) is not a wait for a place here."""
        def here(job: dict) -> bool:
            wait = job.get("waiting")
            if not wait:
                return False
            if not isinstance(wait, dict):
                return True
            return wait.get("class") not in OWN_WORKER and wait.get("on", harness) == harness
        return any(here(j) for j in cls._yours(harness))

    def free(self, harness: str) -> int:
        """How many of the harness's places are free for a cortex run now: none while your work waits for one. A line
        taken back still holds its place until its run is confirmed stopped."""
        from brain import xperfect
        if self.wanted(harness):
            return 0
        return max(0, xperfect.slots() - self.holding(harness) - self._jobs(harness))

    def room(self, harness: str) -> bool:
        return self.free(harness) > 0

    def claim(self, harness: str) -> str:
        """One free place on this harness taken now, under the lane's lock, for a run about to start: its claim, or ""
        when none is free (the cortices of one round start together: two that saw one free place never both take it,
        the second to bounce off xPerfect). started() turns it into the run's own line; ended() gives it back."""
        from brain import xperfect
        token = f"{CLAIM}{uuid.uuid4().hex[:12]}"

        def take(runs: list[dict]) -> None:  # (his work counted under the lock too: a hand-off's make_room is either
            # before it, and its job is in the jobs file already, or after it, and sees this claim to take back)
            if not self.wanted(harness) and xperfect.slots() - self._jobs(harness) - sum(
                    1 for r in runs if r["harness"] == harness and not r.get("ended")) > 0:
                runs.append({"harness": harness, "worker": token, "pid": os.getpid(), "at": time.time()})
        return token if any(r["worker"] == token for r in self._edit(take)) else ""

    async def wait_for_room(self, harness: str, wait: float | None = None) -> str:
        """A place claimed on this harness within `wait` (ROOM_WAIT): its claim, or "" when none came free. Anything to
        sweep is swept first, and again at each look."""
        self.keep_swept()
        deadline = time.monotonic() + (ROOM_WAIT if wait is None else wait)
        while True:
            if self.owed():
                await self.sweep()
            if claim := self.claim(harness):
                return claim
            if time.monotonic() > deadline:
                return ""
            await asyncio.sleep(2.0)

    def gives_way(self, harness: str, worker: str) -> bool:
        """Whether this cortex run gives its place up now: xPerfect holds work of yours on its harness for room, and it
        is the newest cortex run there (one at a time, newest first, until your work has its place)."""
        if not self.wanted(harness):
            return False
        mine = [r for r in self._runs() if r.get("harness") == harness and not r.get("orphan") and not r.get("revoked")
                and not r.get("ended") and not str(r.get("worker", "")).startswith(CLAIM)]  # (a claim has no run yet; an
        # orphan's, one taken back and one over are the sweep's)
        return bool(mine) and max(mine, key=lambda r: r.get("at", 0)).get("worker") == worker

    def started(self, harness: str, worker: str, claim: str = "") -> bool:
        """The run's Worker exists: its line takes the place of its claim (taken back, the line keeps that mark). False
        when the claim was taken back meanwhile: then nothing is dispatched (XPerfect.think)."""
        kept: list[bool] = []

        def swap(runs: list[dict]) -> None:
            was = next((r for r in runs if claim and r["worker"] == claim), None)
            kept.append(not claim or (was is not None and not was.get("revoked")))
            runs[:] = [r for r in runs if r["worker"] != claim] + [
                {"harness": harness, "worker": worker, "pid": os.getpid(), "at": time.time(),
                 **({} if kept[0] else {"revoked": True})}]
        self._edit(swap)
        return kept[0]

    def dispatched(self, harness: str, worker: str, run: str = "") -> bool:
        """The one rule's second half: right after xPerfect's dispatch returns, whether this run's line is still its own
        (looked at under the lock), its run id kept on it (the sweep asks xPerfect by it whether a run taken back is
        over). False: it was taken back meanwhile, and the run stops there (XPerfect.think)."""
        mine: list[bool] = []

        def look(runs: list[dict]) -> None:
            for r in runs:
                if r["harness"] == harness and r["worker"] == worker:
                    if run:
                        r["run"] = run
                    mine.append(not r.get("revoked"))
        self._edit(look)
        return bool(mine) and mine[0]

    def revoke(self, harness: str, worker: str) -> None:
        """Its line taken back (marked under the lock): its stop is sent now by whoever took it, and again by the sweep
        until xPerfect says its run is over."""
        self._mark(worker, revoked=True)

    def revoked(self, harness: str, worker: str) -> bool:
        return any(r["harness"] == harness and r["worker"] == worker and r.get("revoked") for r in self._edit())

    def ended(self, harness: str, worker: str, confirmed: bool = True, over: bool = False) -> None:
        """confirmed: its run is over and its Worker closed: the line goes. over: xPerfect says its run is over but its
        Worker's close was refused: the line holds no place, and the sweep tries the close again. Neither: its stop is
        not confirmed, and the line stays, holding its place: one whose run was dispatched (its run id kept) is taken
        back, so the sweep sends its stop again until xPerfect says the run is over; one with no run, for the sweep to
        close its Worker."""
        def end(runs: list[dict]) -> None:
            if confirmed:
                runs[:] = [r for r in runs if r["worker"] != worker]
                return
            for r in runs:
                if r["worker"] == worker:
                    r.update({"ended": True} if over else {"revoked": True} if r.get("run") else {"orphan": True})
        self._edit(end)

    async def make_room(self, harness: str) -> list[str]:
        """A job is being handed off to this harness (it is counted already): while the cortex runs there and your work
        need more places than it has, the newest cortex runs there are taken back (whichever process runs them), chosen
        and marked under the lane's one lock, and their runs stopped; each line goes once its stop is confirmed."""
        from brain import xperfect
        self.keep_swept()
        if self.owed():
            try:
                await self.sweep()
            except Exception as e:  # noqa: BLE001 (never in the way of his job)
                log.debug("lane: sweep before a hand-off failed: %s", type(e).__name__)
        stopped: list[str] = []

        def take_back(runs: list[dict]) -> None:
            mine = [r for r in runs if r["harness"] == harness and not r.get("revoked")  # (those taken back are going,
                    and not r.get("ended")]                                             # those over hold no place)
            over = len(mine) + self._jobs(harness) - xperfect.slots()
            # (an orphan's place is freed only by sweep: xPerfect may still run it, so the live runs go first)
            live = sorted((r for r in mine if not r.get("orphan")), key=lambda r: r.get("at", 0), reverse=True)
            for r in live[:max(0, over)]:
                r["revoked"] = True
                stopped.append(r["worker"])
        self._edit(take_back)
        for worker in stopped:
            if not worker.startswith(CLAIM):  # (a claim has no Worker yet: it learns at started())
                await _xp().interrupt(worker)
        return stopped


_sweeper: asyncio.Task | None = None
_sweeper_lock = threading.Lock()  # (one timer per process, whichever thread asks)


def _orphans_marked(runs) -> list[dict]:
    """The lane's lines as they stand: a run whose process is gone is kept, marked an orphan (xPerfect may still run
    it); a claim whose process is gone goes (it never got a Worker)."""
    out = []
    for r in runs if isinstance(runs, list) else []:
        if not isinstance(r, dict) or not r.get("worker"):
            continue
        if not _alive(r.get("pid")):
            if str(r["worker"]).startswith(CLAIM):
                continue
            r = {**r, "orphan": True}
        out.append(r)
    return out


async def _run_over(xp, run: str) -> bool:
    """Whether xPerfect says this run is over (its own state)."""
    try:
        return (await xp._call("GET", f"/v1/runs/{run}")).get("state") in ("completed", "failed", "cancelled",
                                                                           "interrupted")
    except RuntimeError as e:
        return "404" in str(e)


async def _unknown(xp, worker: str) -> bool:
    """Whether xPerfect no longer knows this Worker (closed already: its place is free)."""
    try:
        await xp._call("GET", f"/v1/workers/{worker}")
        return False
    except RuntimeError as e:
        return "404" in str(e)


def runs_on(job: dict) -> str:
    """The harness a job's work runs on now: the last route it fell back to (core/jobs "fallback", Workers._fall_back),
    else its route, else its harness, else the one you prefer."""
    from brain import xperfect
    token = (job.get("fallback") or "").split(",")[-1] or job.get("route") or job.get("harness") \
        or os.environ.get("WORKER_PROFILE", "")
    return xperfect.parts(token)[0]


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


LANE = Lane()


# -- What each part did last (the Subconscious page shows it beside each card) --

def runs_file():
    from core.state import STATE_ROOT
    return STATE_ROOT / "core" / "subconscious-runs.json"


def last_runs() -> dict:
    """{"round": {...}, "coordinator": {...}, "<cortex id>": {...}}: each one's last outcome, with its time."""
    try:
        return json.loads(runs_file().read_text())
    except (OSError, ValueError):
        return {}


def _remember(key: str, fields: dict) -> None:
    from core.state import optional_write_failed, private_file
    path = runs_file()
    try:
        with private_file(path.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            runs = last_runs()
            runs[key] = {"at": round(time.time(), 3), **fields}
            tmp = path.with_suffix(".tmp")
            with private_file(tmp, "w") as f:
                f.write(json.dumps(runs, indent=1))
            tmp.replace(path)
    except OSError:
        optional_write_failed("run_history")


# -- Her thoughts: kept for the whole conversation, across calls and chats (each handed to her once) --

def thoughts_file():
    from core.state import STATE_ROOT
    return STATE_ROOT / "core" / "subconscious-thoughts.jsonl"


THOUGHTS_READ = 256 * 1024  # bytes a call or chat start reads of her thoughts: their tail, far more than it carries
THOUGHTS_KEPT = 1024 * 1024  # the file is cut back to its latest this many bytes whenever it grows to twice that


def _keep_thought(entry: dict) -> None:
    """One line of what became of a thought: handed to her (its words), then how it ended. His alone, beside the log;
    bounded: at twice THOUGHTS_KEPT, cut back to its latest THOUGHTS_KEPT (whole lines), under one lock with every write
    (a call and Telegram both keep theirs)."""
    from core.state import optional_write_failed, private_file
    path = thoughts_file()
    try:
        with private_file(path.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with private_file(path, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            try:
                if path.stat().st_size > 2 * THOUGHTS_KEPT:
                    with open(path, "rb") as f:
                        f.seek(-THOUGHTS_KEPT, os.SEEK_END)
                        tail = f.read()
                    temp = path.with_suffix(".tmp")
                    with private_file(temp, "wb") as out:
                        out.write(tail[tail.find(b"\n") + 1:])
                    os.replace(temp, path)
            except OSError:
                optional_write_failed("thought_trim")
    except OSError:
        optional_write_failed("thought")


def earlier_thoughts(since: float) -> list[Thought]:
    """Her thoughts handed over since `since` (the oldest message a new call or chat carries), with how each ended:
    read from the file's tail (THOUGHTS_READ), never the whole of it."""
    try:
        with open(thoughts_file(), "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - THOUGHTS_READ))
            data = f.read()
    except OSError:
        return []
    if size > THOUGHTS_READ:  # (a line cut by the start of the tail is not read)
        data = data[data.find(b"\n") + 1:]
    lines = data.decode("utf-8", errors="replace").splitlines()
    found: dict[str, Thought] = {}
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if "text" in entry and float(entry.get("t", 0)) >= since:
            found[entry["id"]] = Thought(entry["cortex"], entry["name"], entry["text"], False, 0, entry.get("where", ""),
                                         entry.get("turn", 0), entry["id"], "",
                                         [r for r in entry.get("refs") or [] if isinstance(r, dict)])
        elif entry.get("id") in found and entry.get("how"):
            found[entry["id"]].how = entry["how"]
    return list(found.values())


# -- One round --

class Subconscious:
    """The background minds of one conscious mind (a call, Telegram). The mind hands it what it needs as plain callables,
    so it never reaches into the mind, and a test can hand it its own:

        record(kind, **fields)      the channel's log (logs/turns.jsonl), which the Live view reads
        surface(thoughts, linked)   (async) the conscious mind is told (raises if it could not be)
        feel(place)                 Emotional reaction: her Feelings react to their words, on that place
        quiet()                     (async) until neither of you has spoken for a moment
        busy()                      whether she is thinking or speaking, or they are speaking
        shown                       Life files already in her notes (the memory search skips them)
        earlier                     her thoughts of this conversation from before (a new call after Telegram); default:
                                    every one kept, the whole conversation (earlier_thoughts)
        current(refs)               how each row of the record a round read stands now by his change list: None as
                                    read, "" left out (he asked to forget it since), else its words now (brain/queen.py
                                    rows_now); default: as read
    """

    def __init__(self, *, record, surface, feel, quiet=None, busy=None, shown: set | None = None,
                 earlier: list[Thought] | None = None, current=None) -> None:
        self._record, self.surface, self.feel, self.quiet, self.busy = record, surface, feel, quiet, busy
        self.current = current or (lambda refs: [None] * len(refs))
        self.shown = shown if shown is not None else set()
        if earlier is None:
            try:  # (the whole conversation, not only what a new call carries: a thought she said is never said again)
                earlier = earlier_thoughts(0.0)
            except Exception:  # noqa: BLE001 (nothing kept yet: nothing earlier)
                earlier = []
        self.had: list[Thought] = list(earlier)  # her thoughts of this conversation, oldest first: each handed once
        self._own_from = len(self.had)  # (where this call's or chat's own begin: before them, earlier ones of the day)
        self._task: asyncio.Task | None = None
        self._waiting: deque[tuple[Turn, Context]] = deque()
        LANE.keep_swept()  # (in this process, on a timer: runs a crash left behind are stopped and freed)

    def record(self, kind: str, **fields) -> None:
        """Into the channel's log, and each part's last outcome kept for the page."""
        self._record(kind, **fields)
        event = fields.get("event")
        if event == "cortex":
            _remember(fields["id"], {k: v for k, v in fields.items()
                                     if k in ("state", "ms", "where", "effort", "how", "words", "why", "chose", "route")})
        elif event in ("coordinator", "round"):
            _remember(event, {k: v for k, v in fields.items()
                              if k in ("ms", "where", "effort", "how", "picked", "always", "asked", "chose", "route",
                                       "covers")})

    def earlier(self, now: list | tuple = ()) -> list[Thought]:
        """Her thoughts handed over before these (`now`), each with how it ended: what her one word sees she already has
        (never one made from what he asked to forget since: kept)."""
        first = next((i for i, t in enumerate(self.had) if any(t is n for n in now)), len(self.had))
        return self.kept(self.had[:first])

    def standing(self, turn: Turn) -> tuple[Turn, bool]:
        """The turn as it stands now by his change list, for a part asked now (filtered at use, never only when the
        round began: a forget made while it waited for a place counts): each line he asked to forget since is taken
        out, a corrected one is in its words now. And whether anything it read was taken out (its thoughts then are
        made from what he asked to forget: never handed to her)."""
        if not any(turn.refs) or len(turn.refs) != len(turn.talk):
            return turn, False
        now = self.current(turn.refs)
        start = _start(turn.talk, turn.count) if turn.count else len(turn.talk)
        talk, refs, count, gone = [], [], 0, False
        for i, ((role, words), ref, word) in enumerate(zip(turn.talk, turn.refs, now)):
            if word == "":
                gone = True
                continue
            talk.append((role, words if word is None else word))
            refs.append(ref)
            count += i >= start and role != RESULT
        if not gone and all(word is None for word in now):
            return turn, False
        return Turn(words=turn.words, reply=turn.reply, talk=talk, number=turn.number, covers=list(turn.covers),
                    count=count if turn.count else 0, refs=refs), gone

    def stands(self, refs: list) -> bool:
        """Whether every row these were made from still stands (none he asked to forget since)."""
        return not refs or "" not in self.current(list(refs))

    def kept(self, thoughts: list | tuple) -> list[Thought]:
        """Her thoughts, without any made from what he asked to forget since it was thought."""
        return [t for t in thoughts if self.stands(getattr(t, "refs", None) or [])]

    def decided(self, thoughts: list[Thought], how: str) -> None:
        """How thoughts she was handed ended (her side, Queen._muse): said, kept, rode with their next turn, or no
        answer. Later parts see it, and so does a new call."""
        for t in thoughts:
            t.how = how
            if t.id:
                _keep_thought({"t": time.time(), "id": t.id, "how": how})

    async def hand(self, thoughts: list[Thought], linked: bool) -> None:
        """Thoughts to her, each once in the conversation: one with the very words of a thought she already has (said,
        or kept here) is not handed again, the same in other words is the model's to judge (each part, and her one word,
        see what she has). A thought counts as hers only once she has really been told (surface returned); if that
        failed it is not hers, and the same words may come again. One made from what he asked to forget since (a row
        its round read no longer stands) never reaches her."""
        forgotten = [t for t in thoughts if not self.stands(t.refs)]
        if forgotten:
            self.record("subconscious", event="forgotten", cortices=[t.cortex for t in forgotten],
                        turn=forgotten[0].turn)
            thoughts = [t for t in thoughts if t not in forgotten]
        fresh: list[Thought] = []
        own, before = self.had[self._own_from:], self.had[:self._own_from]
        for t in thoughts:
            if any(t.text == old.text for old in own + fresh) or any(t.text == old.text and old.how == "said" for old in before):
                self.record("subconscious", event="repeat", id=t.cortex, name=t.name, turn=t.turn)
            else:
                fresh.append(t)
        if not fresh:
            return
        for t in fresh:
            t.id = t.id or uuid.uuid4().hex[:12]
        try:
            await self.surface(fresh, linked)
        except Exception as e:  # noqa: BLE001 (not told: not hers, so it may come again)
            log.warning("thoughts not handed over: %s", e)
            self.record("subconscious", event="not_handed", cortices=[t.cortex for t in fresh], error=type(e).__name__)
            return
        self.had.extend(fresh)
        for t in fresh:
            _keep_thought({"t": time.time(), "id": t.id, "turn": t.turn, "cortex": t.cortex, "name": t.name,
                           "text": t.text, "where": t.where, **({"refs": t.refs} if t.refs else {})})

    def after(self, turn: Turn) -> None:
        """A turn ended with her answer out: its round starts now, or once the running one ends. When another turn ends
        while one is still waiting, the newer one's round covers both (its turns that just ended are both, his words in
        each whole), and the record says so: no turn of his goes without a round."""
        if self._task is not None and not self._task.done():
            if self._waiting:
                old, _ = self._waiting.pop()
                turn = _merged(old, turn)
                self.record("subconscious", event="superseded", turn=old.number, by=turn.number,
                            covers=turn.covers)
            self._waiting.append((turn, copy_context()))
            return
        self._task = asyncio.ensure_future(self._run(turn))

    @plan_auth.unattended
    async def _run(self, turn: Turn) -> None:
        try:
            await self.round(turn)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 (never in her way: without a round she only thinks less)
            log.warning("subconscious round failed: %s", e)
            self.record("subconscious", event="failed", error=type(e).__name__)
        finally:
            if self._waiting:
                pending, context = self._waiting.popleft()
                self._task = asyncio.create_task(self._run(pending), context=context)

    async def round(self, turn: Turn) -> None:
        state = await asyncio.to_thread(page.show)
        coordinator = state["coordinator"]
        if not coordinator["on"]:
            return  # the one switch for the whole Subconscious: nothing runs, and her Feelings do not move
        cortices = [c for c in state["cortices"] if c["on"] and (c["then"].strip() or c["hands_back"] == "feelings")]
        always = [c for c in cortices if not c["when"].strip()]
        asked = [c for c in cortices if c["when"].strip()]
        began = time.monotonic()
        self.record("subconscious", event="round", turn=turn.number, always=[c["id"] for c in always],
                    asked=[c["id"] for c in asked], **({"covers": turn.covers} if turn.covers else {}))
        had = list(self.had)  # (what she already had when this turn ended: the same for every part of this round;
        # each part is shown those of them that still stand when it is asked, Subconscious.kept)
        choosing = asyncio.ensure_future(self.choose(coordinator, state["cortices"], asked, turn, had)) if asked else None
        runs = {cortex["id"]: asyncio.ensure_future(self.think(cortex, state, turn, had)) for cortex in always}
        await self.deliver(runs, {c["id"]: c for c in cortices}, began + coordinator["wait"] * 60, choosing,
                           lambda cortex: asyncio.ensure_future(self.think(cortex, state, turn, had)))

    async def choose(self, coordinator: dict, every: list[dict], asked: list[dict], turn, had: list | tuple = ()) -> list[dict]:
        """The coordinator reads the one prompt and names the cortices to run. Failing or too slow: none of the cards
        with a "When" run this turn (the ones without still do). `turn`: the Turn (or, as before, its talk)."""
        turn = turn if isinstance(turn, Turn) else Turn(words="", reply="", talk=turn, number=0)
        where, began, ran = coordinator_place(coordinator), time.monotonic(), {}
        if where.kind == "none":  # (a Worker type that does not exist: said so, before anything is looked up for it)
            text, how = "", "no_such_worker"
        else:
            read: dict = {}

            def user() -> str:  # (made when it is asked, as the conversation stands by his change list then)
                now, seen = self.standing(turn)[0], []
                text = conversation(now.talk, "the one to judge", self.kept(had), turn_room(where), now.count, seen)
                read["refs"] = [now.refs[i] for i in seen if i < len(now.refs) and now.refs[i]]
                return text
            text, how = await ask(where, page.merged(coordinator, every), user, name="Subconscious coordinator",
                                  max_tokens=200, wait=CHOOSE_WAIT.get(where.kind, CHOOSE_WAIT["mac"]),
                                  busy=self.busy, quiet=self.quiet, ran=ran,
                                  still=lambda: self.stands(read.get("refs", [])))
        ids = picked(text, asked) if how == "ok" else []
        self.record("subconscious", event="coordinator", ms=round((time.monotonic() - began) * 1000),
                    where=ran.get("name", where.name), effort=ran.get("effort", where.effort), chose=where.chose,
                    route=ran.get("route", ""), how=how, picked=ids, said=(text or "")[:200],
                    **({"usage": ran["usage"]} if ran.get("usage") else {}),
                    **({"room_ms": ran["room_ms"]} if "room_ms" in ran else {}))  # (its wait for a place: part of ms)
        return [c for c in asked if c["id"] in ids]

    async def think(self, cortex: dict, state: dict, turn: Turn, had: list | tuple = ()) -> Thought | None:
        """One cortex: its Then (after what every cortex is told), on its own place, with the conversation and the
        thoughts she already had in it."""
        where, began = cortex_place(cortex), time.monotonic()
        fields = {"id": cortex["id"], "name": cortex["name"], "where": where.name, "effort": where.effort,
                  "chose": where.chose, "turn": turn.number}
        if cortex["hands_back"] == "feelings":  # Emotional reaction: Feelings' own prompt, on the card's place
            self.feel(where.word())
            self.record("subconscious", event="cortex", state="feelings", **fields)
            return None
        found = None
        if cortex.get("searches") == "memory":  # the memory search first, and its finds with the conversation
            from core import memory
            try:
                # (searched by their words and hers, as before: a Worker result is what she was given, not what
                # the turn is about)
                found = await asyncio.to_thread(memory.deep, said(self.standing(turn)[0].talk), tuple(self.shown))
            except Exception:  # noqa: BLE001 (no index, no embedding server: nothing found)
                found = []
            if not found and cortex.get("needs_finds"):
                self.record("subconscious", event="cortex", state="nothing", why="the memory search found nothing new",
                            ms=round((time.monotonic() - began) * 1000), **fields)
                return None
        read: dict = {}

        def user() -> str:  # (made when it is asked, as the conversation stands by his change list then)
            now, seen, seen_had = self.standing(turn)[0], [], []
            text = _context(where, now.talk, found, self.kept(had), now.count, seen, seen_had)
            # (what its thought is made from: the rows its words showed, whole or as their excerpt, and those of the
            # earlier thoughts they showed; never the lines the room left out)
            refs = [now.refs[i] for i in seen if i < len(now.refs) and now.refs[i]]
            read["refs"] = list({(r["row"], r.get("digest")): r for r in refs + [r for t in seen_had for r in t.refs]
                                 if isinstance(r, dict)}.values())
            return text
        local_recall = _local_recall(cortex)
        recall_rule = "Return relevant facts in your own words. Do not quote retrieved passages." if local_recall else ""
        system = "\n\n".join(part for part in (state["every_cortex"].strip(), cortex["then"].strip(), recall_rule,
                                                 can(where, found is not None, _unseen(user()))) if part)
        ran: dict = {}
        text, how = await ask(where, system, user, name=f"Cortex: {cortex['name']}", max_tokens=900,
                              wait=WAIT.get(where.kind, WAIT["mac"]), busy=self.busy, quiet=self.quiet, ran=ran, beside=True,
                              still=lambda: self.stands(read.get("refs", [])))
        words, ms = thought_of(text) if how == "ok" else "", round((time.monotonic() - began) * 1000)
        fields.update(where=ran.get("name", where.name), effort=ran.get("effort", where.effort), route=ran.get("route", ""),
                      **({"owned": True} if ran.get("owned") else {}), **({"unframed": ran["unframed"]} if ran.get("unframed") else {}),
                      **({"room_ms": ran["room_ms"]} if "room_ms" in ran else {}))
        self.record("subconscious", event="cortex", state="thought" if words else "nothing" if how == "ok" else "failed",
                    how=how, ms=ms, words=words[:300], **fields, **({"usage": ran["usage"]} if ran.get("usage") else {}))
        if words and local_recall and found:
            # A model can echo its input. Keep that result in the local record instead of forwarding it.
            answer = " ".join(words.casefold().split())
            for passage in found:
                body = passage["text"].removeprefix(f"({passage.get('source')}) ").strip()
                if body and " ".join(body.casefold().split()) in answer:
                    return None
        if words and found:
            self.shown.update(f["path"] for f in found)
        from core import brain_trace
        return Thought(cortex["id"], cortex["name"], words, bool(cortex["linked"]), ms, fields["where"], turn.number,
                       refs=read.get("refs", []), turn_id=brain_trace.current.get()) if words else None

    async def deliver(self, runs: dict[str, asyncio.Future], cortices: dict[str, dict], deadline: float,
                      choosing: asyncio.Future | None = None, start=None) -> None:
        """Unlinked thoughts as each arrives, while the coordinator may still be choosing (before, every
        thought of a round waited for it: 34 to 65 s on this Mac's model); linked ones together once the coordinator has answered
        and all of them are done, or when the wait limit ends; one that comes later by itself. `choosing`: the
        coordinator's answer, the cortices it names started by `start`."""
        def links(cid: str) -> bool:
            return bool(cortices[cid]["linked"]) and cortices[cid]["hands_back"] != "feelings"

        names = {future: cid for cid, future in runs.items()}
        waiting = {cid for cid in runs if links(cid)}
        pending = set(runs.values()) | ({choosing} if choosing is not None else set())
        group, gone = [], False
        while pending:
            done, pending = await asyncio.wait(pending, timeout=None if gone else max(0.0, deadline - time.monotonic()),
                                               return_when=asyncio.FIRST_COMPLETED)
            for future in done:
                if future is choosing:  # the coordinator answered: the cortices it named start now
                    choosing = None
                    named = [] if future.cancelled() or future.exception() is not None else future.result()
                    for cortex in named:
                        if cortex["id"] in runs or start is None:
                            continue
                        run = start(cortex)
                        runs[cortex["id"]], names[run] = run, cortex["id"]
                        pending.add(run)
                        if links(cortex["id"]) and not gone:
                            waiting.add(cortex["id"])
                    continue
                waiting.discard(names[future])
                failed = None if future.cancelled() else future.exception()
                if failed is not None:
                    log.warning("cortex %s failed: %s", names[future], failed)
                thought = None if future.cancelled() or failed is not None else future.result()
                if thought is None:
                    continue
                if thought.linked and not gone:
                    group.append(thought)
                else:
                    await self.hand([thought], False)
            if not gone and ((not waiting and choosing is None) or time.monotonic() >= deadline):
                gone = True
                if waiting or choosing is not None:
                    self.record("subconscious", event="late", cortices=sorted(waiting),
                                **({"coordinator": "still choosing"} if choosing is not None else {}))
                if group:
                    await self.hand(group, True)
                group = []
        if group:
            await self.hand(group, True)


def _merged(old: Turn, new: Turn) -> Turn:
    """A turn that ended while an earlier one still waited for its round: one round reads both as the turns that just
    ended (the earlier one's messages come right before the newer one's in its conversation)."""
    own = new.count or ended(new.talk)
    count = min(len(said(new.talk)), own + (old.count or ended(old.talk)))
    return Turn(words=new.words, reply=new.reply, talk=new.talk, number=new.number, covers=[*old.covers, old.number],
                count=count, refs=list(new.refs))
