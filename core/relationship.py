"""One continuous relationship: every channel appends to the same local conversation.

Roles: user, assistant, and worker (a Worker result, as the Queen received it).

Stored on this Mac only (state/core/, untracked). A new call or chat starts from the recent
conversation, so the Queen continues where you left off. Long-term memory lives in Life (stage 3).

No word is cut without saying so (a person's words stay exact). recent() carries each of the last messages at least as
its excerpt: its beginning and its end, around one line that says how much is not shown and where all of it is, word for
word (whole(): a file of its own, made from the text the first time it is needed); the room left goes to the newest,
whole. What is older than that is named by one note: how many messages, and the log that keeps every one of them. The
log itself always keeps every message whole; the page is sent the whole text (full()).
"""
import fcntl
import hashlib
import json
import os
import time

from core.state import STATE_ROOT, closed_file

STATE = STATE_ROOT / "core"
LOG = STATE / "conversation.jsonl"
RECENT_MESSAGES = 16       # carried into the next call
# What a new call or chat carries, at most: an eighth of the smallest window a mind of hers has (this Mac's model,
# 65,536 tokens: vx, OLLAMA_CONTEXT_LENGTH), at about four characters a token. Before, it was 4,000 characters
# with every message cut at 1,000: a 19,091-character message reached a new chat as 1,002.
RECENT_CHARS = 65536 // 8 * 4
SHOWN_AT_LEAST = 2000      # what a message too long for its room still shows of itself, around the line, at least
EXCERPT_MARK = "not shown here; all of it, word for word:"  # (in every excerpt's line, before the file's path)
WHOLE_KEPT = 2 * 86400     # a whole-text file no carried message names is removed after this long (seconds)


def append(role: str, text: str, channel: str, call_id: str = "", files: list[dict] | None = None,
           heard: bool = False, item: str = "", file_offer: str = "", once: bool = False, at: float | None = None,
           notice: bool = False) -> int:
    """One message into the log. Her replies are kept exactly as she wrote them, their outer spaces and line breaks too
    (literal text); his words and Worker results as they came, trimmed at their ends. The log is
    only ever appended to, so the row a message lands on is its one identity for her memory (every
    reader carries it, a change names it): returned, 0 when nothing was kept. heard: words only heard (Wing,
    Listen only), maybe not said to her, maybe someone else's: a summary says so. item: the live conversation's own id
    of the message (its row is found by it). file_offer links a delivery receipt to an existing offer.
    at: the event's time when a call queues the write off its audio loop. notice: a notice of Light's shown to the
    person (who answers for her mind, and why), kept with its line and read back to her mind as a fact, not her words."""
    if not text or not text.strip() or role not in ("user", "assistant", "worker"):
        return 0
    line = (json.dumps({"t": time.time() if at is None else at, "role": role, "text": text if role == "assistant" else text.strip(),
                        # (exact: a rounded time could fall before a channel's last look and never reach it)
                        "channel": channel, "call_id": call_id,
                        **({"files": files} if files else {}), **({"heard": True} if heard else {}),
                        **({"item": item} if item else {}), **({"file_offer": file_offer} if file_offer else {}),
                        **({"notice": True} if notice else {})}) + "\n").encode()
    with closed_file(LOG, "ab") as f:  # (his words: his alone from the start, its folder too; core/state.py)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # (one append at a time: each one's row counted exactly)
        if once and item:
            from core.life import row_of_item
            if row := row_of_item(item):
                return row
        lines, whole = _rows_in()
        # (a line left half-written, by a crash, is closed first: it keeps a row of its own, unreadable, and this
        # message its own; written onto it, the two would share one row and no reader could read either)
        torn = b"" if whole else b"\n"
        f.write(torn + line)
        f.flush()
        row = lines + len(torn) + 1
        _COUNTED.update(size=_COUNTED["size"] + len(torn) + len(line), count=row,
                        key=_record_key(os.fstat(f.fileno())), tail=(torn + line)[-64:])
    return row


_COUNTED: dict = {}  # (the log's lines counted so far, up to where, and the bytes it ended with there)


def _record_key(st) -> tuple:
    return st.st_dev, st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size


def _rows_in() -> tuple[int, bool]:
    """How many whole lines the log holds (under append's lock), and whether it ends with a whole one: counted once,
    then only what was appended since (the bytes it ended with checked first: a log written anew is counted again)."""
    st = LOG.stat()
    with LOG.open("rb") as r:
        size, tail = _COUNTED.get("size", 0), _COUNTED.get("tail", b"")
        if not (_COUNTED.get("path") == str(LOG) and _COUNTED.get("key") == _record_key(st)):
            _COUNTED.update(path=str(LOG), ino=st.st_ino, size=0, count=0, tail=b"")
        r.seek(_COUNTED["size"])
        added = sum(chunk.count(b"\n") for chunk in iter(lambda: r.read(1 << 20), b""))
        r.seek(max(st.st_size - 64, 0))
        tail = r.read(64)
    _COUNTED.update(size=st.st_size, key=_record_key(st), count=_COUNTED["count"] + added, tail=tail)
    return _COUNTED["count"], not tail or tail.endswith(b"\n")


def whole(text: str):
    """A file that holds exactly `text` (made once, his alone: core/state.private_file; its name comes from the text):
    the exact reference for words that are carried somewhere only in part."""
    from core.state import private_dir, private_file
    folder = private_dir(STATE / "whole")  # (beside the log, wherever a test puts it)
    path = folder / (hashlib.sha256(text.encode()).hexdigest()[:24] + ".txt")
    try:
        same = path.read_text() == text
    except OSError:
        same = False
    if not same:
        tmp = path.with_suffix(f".{os.getpid()}.{time.monotonic_ns()}.tmp")
        with private_file(tmp, "x") as f:
            f.write(text)
        tmp.replace(path)
    return path


def prune(named: set[str]) -> None:
    """Whole-text files no carried message names, made more than WHOLE_KEPT ago, are removed (each is only a copy of
    words the log keeps; a run that was handed one has long finished)."""
    folder = STATE / "whole"
    if not folder.is_dir():
        return
    old = time.time() - WHOLE_KEPT
    for path in folder.glob("*.txt"):
        try:
            if str(path) not in named and path.stat().st_mtime < old:
                path.unlink()
        except OSError:
            continue


def excerpt(text: str, room: int) -> str:
    """Words that may be longer than `room`: whole when they fit; else their beginning and their end, around one line
    saying how many characters are not shown and where all of them are, word for word (whole())."""
    if len(text) <= room:
        return text
    room = max(room, SHOWN_AT_LEAST)
    head, tail = _until_space(text[: room * 2 // 3]), _from_space(text[len(text) - room // 3:])
    left = len(text) - len(head) - len(tail)
    return f"{head}\n[… {left:,} more characters, {EXCERPT_MARK} {whole(text)}]\n{tail}"


def _until_space(part: str) -> str:
    cut = part.rfind(" ", len(part) - 200)
    return part[:cut] if cut > 0 else part


def _from_space(part: str) -> str:
    cut = part.find(" ", 0, 200)
    return part[cut + 1:] if cut >= 0 else part


def fit(texts: list[str], room: int, first: list[int] = ()) -> list[str | None]:
    """Each text whole or as its excerpt, within `room` in all. Every one keeps at least SHOWN_AT_LEAST of itself (all
    of it when shorter); the room left goes to the ones named in `first`, in that order, then to the rest from the
    newest (the last) back, each whole when it fits, else as large an excerpt as is left. When even that floor does
    not fit them all, the oldest go (None), never one from the middle."""
    floors = [min(len(t), SHOWN_AT_LEAST) for t in texts]
    kept = len(texts)
    while kept and sum(floors[len(texts) - kept:]) > room:
        kept -= 1
    start = len(texts) - kept
    given = {i: floors[i] for i in range(start, len(texts))}
    left = room - sum(given.values())
    order = [i for i in first if i in given] + [i for i in reversed(range(start, len(texts))) if i not in first]
    for i in order:
        more = min(len(texts[i]) - given[i], max(left, 0))
        given[i] += more
        left -= more
    return [None if i < start else (texts[i] if given[i] >= len(texts[i]) else excerpt(texts[i], given[i]))
            for i in range(len(texts))]


def recent() -> list[dict]:
    """The latest messages, oldest first, each whole or as its excerpt (`whole` names the file with all of it), within
    the message and size budget: every one at least its excerpt, the room left to the newest, whole. When older messages
    are not carried, a first note (role "system", "earlier": how many) says so and names the log that keeps them all."""
    if not LOG.exists():
        return []
    from core import life  # (as they stand now, each with its row)
    lines = life.record_rows()
    try:  # (a message left out keeps its place and its row, so an undo brings it back in place)
        items = life.current_rows(life.numbered(lines)[-RECENT_MESSAGES:], keep_gone=True)
    except life.Unreadable as e:  # (never the conversation as said, which may hold what he asked to forget)
        return [{"t": time.time(), "role": "system", "text": f"(The conversation so far is not carried here: {e}.)",
                 "channel": "", "call_id": "", "earlier": len(lines)}]
    shown = fit([item["text"] for item in items], RECENT_CHARS)
    picked = []
    for item, text in zip(items, shown):
        if text is None:
            continue
        if text != item["text"]:
            item["whole"] = str(whole(item["text"]))
            item["text"] = text
        picked.append(item)
    earlier = len(lines) - len(picked)
    prune({item["whole"] for item in picked if "whole" in item})
    if earlier:
        note = (f"Earlier conversation: {earlier:,} older messages are not carried here; every message is kept, word for "
                f"word, as it stands now, in {life.record_where()} (one JSON object per line).")
        picked.insert(0, {"t": picked[0]["t"] if picked else time.time(), "role": "system", "text": note,
                          "channel": "", "call_id": "", "earlier": earlier})
    return picked


def full(item: dict) -> str:
    """A carried message's whole text (the page shows him every word; it costs no model context)."""
    if item.get("whole"):
        try:
            return open(item["whole"]).read()
        except OSError:
            pass
    return item.get("text", "")


def call(call_id: str) -> list[dict]:
    """Every message of one call, in order (for its Life summary)."""
    from core import life
    return [row for row in life.current_rows(life.numbered()) if row.get("call_id") == call_id]


def since(row: int, exclude_channel: str | None = None, exclude_call: str | None = None) -> list[dict]:
    """Other conversations after this row (not this channel kind, or not this conversation's own room), retaining
    placeholders so an undo can restore them in place."""
    if not LOG.exists():
        return []
    from core import life  # (as they stand now, each with its row)
    rows = [item for item in life.numbered() if item["row"] > row
            and (exclude_channel is None or item.get("channel") != exclude_channel)
            and (exclude_call is None or item.get("call_id") != exclude_call)]
    try:
        return life.current_rows(rows, keep_gone=True)
    except life.Unreadable:
        return []  # (nothing carried over while the change list cannot be read)
