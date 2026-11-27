"""Life: the user's private world, read in place (never copied into this repo).

Follows Life/AGENTS.md: episodic summaries of each call, and of each chat once it pauses, go to
Memory/Conversations/YYYY/MM/ (§6); the Queen's compact core is a generated view in Views/ (§4),
rebuilt daily from AGENTS.md, Self/ and the recent conversations, so it grows with what you tell her. Search here is plain ripgrep over Memory and
Self; search by meaning, and Deep Memory, are in core/memory.py. Summaries and the core are written by a local model in the background.

What the user corrected or asked to forget is kept in one private list in Light's state, never in Life:
`state/core/memory-changes.jsonl` (core/memory.py adds to it). Light's code never edits his notes for it: whatever is read
from Life or from the conversation goes through `current()` (the passages a change names: a forgotten sentence is never
brought back, a corrected one says what is true now), and every model that reads or writes his Life is told the list in
words (`changes_note()`: her standing notes, a Worker's brief, the summaries, the standing view's rebuild, the night). The
night's Sleep writes a correction into his notes under his Life's rule (keep both with their dates). A process with a
state of its own (a test, a probe, the bench) never gets the Life his live Light uses (`life()`): otherwise test
conversations reach a real Life.
"""
import bisect
import contextlib
import contextvars
import datetime as dt
import fcntl
import functools
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

CORE_NAME = "viventium-light-core.md"
CORE_MAX_AGE_H = 24
CORE_LEARN_H = 1        # after a new conversation, the core relearns once it is this old
RECENT_DAYS = 14         # conversations the daily core learns from
SEARCH_DIRS = ("Memory/Conversations", "Self")  # the per-turn hint: small and fast
SEARCH_SKIP = {"Media", "Archive", "99_System", "Views"}  # recall: media, old copies, internals, generated
ROOT = Path(__file__).resolve().parents[1]


_REFUSED: dict[tuple, str] = {}


def _not_for_this_process() -> str:
    """Why this process must not use the Life it was given ("" when it may). His live Light is named, never inferred:
    VX_RUNTIME=live, which vx exports to every part it starts. Anything else (a test, a probe, an eval, the bench, a
    clone) is asked core/state.live_reason(), the one isolation function: its state or its Life would be his. Asked
    once per setting (it looks at git and his private settings)."""
    if os.environ.get("VX_RUNTIME") == "live":
        return ""
    from core import state
    key = tuple(os.environ.get(k, "") for k in ("LIFE", "VX_STATE", "XPERFECT_STATE", "XPERFECT_LOCAL_STATE")) + (
        str(state.STATE_ROOT), str(state.OWNER_LIFE))
    if key not in _REFUSED:
        _REFUSED[key] = state.live_reason()
    return _REFUSED[key]


def life() -> Path | None:
    path = os.environ.get("LIFE")
    if not path or not Path(path, "AGENTS.md").exists():
        return None
    if why := _not_for_this_process():
        if not getattr(life, "_said", False):
            life._said = True
            print(f"Life: not used here: {why}.", file=sys.stderr)
        return None
    return Path(path)


# -- One pass: what one reader reads once (with 300 older summaries, 50 changes and 20,000 messages, the
#    page's list, one recall, the standing view's rebuild and the due check each read the change list, the record and
#    the summary folder once, never once per summary) --

_PASS: contextvars.ContextVar = contextvars.ContextVar("memory_pass", default=None)


@contextlib.contextmanager
def one_pass():
    """One reader's pass over her memory: inside it the change list (while its file is unchanged), the summary folder,
    each summary's text and what each summary is (its identity, retired or not) are read once. A pass inside a pass is
    the same pass. Outside one every read is fresh: a read that fails while the file looks unchanged is still seen.
    Writers keep their own fresh reads (record_change, a summary's publication)."""
    if _PASS.get() is not None:
        yield
        return
    token = _PASS.set({})
    try:
        yield
    finally:
        _PASS.reset(token)


def _once(key, make):
    """make() once per pass for this key (an Unreadable too); every time outside a pass."""
    held = _PASS.get()
    if held is None:
        return make()
    if key not in held:
        try:
            held[key] = (True, make())
        except Unreadable as e:
            held[key] = (False, e)
    ok, value = held[key]
    if not ok:
        raise value
    return value


def _forget_once(key) -> None:
    """A file this pass read was written (a recovered identity): the next read in the pass reads it again."""
    held = _PASS.get()
    if held is not None:
        held.pop(key, None)


# -- What the user corrected or asked to forget: a private list in Light's state, the one truth of it (core/memory.py adds
#    to it). Light's code never edits his notes for it: whatever is read applies it, and every model told about his
#    Life is told it in words (changes_note); the night's Sleep writes a correction into his notes, under his own rule. --

def ledger_file() -> Path:
    """Beside the conversation it qualifies (state/core/), so a backup and a restore keep both together
    (core/backup.py keeps state/ but not state/memory/, the index rebuilt from Life)."""
    from core import state  # (read when used: a probe's lane moves the state folder between cases)
    return state.STATE_ROOT / "core" / "memory-changes.jsonl"


class Unreadable(OSError):
    """The change list is there but cannot be read whole (no permission, a broken or unknown line): nothing from memory
    is shown until it is put right, since anything shown could be what they asked to forget. Never read as "no change"
    (before, an unreadable list read as empty and brought every forgotten thing back)."""


class Unconfirmed(OSError):
    """A change's line reached the list but the disk did not confirm it (fsync): it may have been kept."""


def ledger() -> list[dict]:
    """Every change, oldest first. An undo is its own line ({"kind": "undo", "of": id}): it takes nothing back from any
    file, it only says the change no longer holds. Only a missing list is empty: one that cannot be read, or a line that
    is not a change, raises Unreadable. In a pass (one_pass) it is read once while the file is unchanged: a change
    written meanwhile changes the file and is read."""
    path = ledger_file()
    if _PASS.get() is None:
        return _read_ledger(path)
    try:
        st = path.stat()
        key = ("ledger", str(path), st.st_dev, st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        key = ("ledger", str(path), "missing")
    except OSError:
        return _read_ledger(path)  # (it raises what it is)
    return _once(key, lambda: _read_ledger(path))


def _read_ledger(path: Path) -> list[dict]:
    try:
        raw = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        why = getattr(e, "strerror", None) or type(e).__name__
        raise Unreadable(f"the list of what they corrected and asked to forget cannot be read ({why})") from e
    out = []
    for n, row in enumerate(raw.split("\n"), 1):
        if not row.strip():
            continue
        try:
            entry = json.loads(row)
        except ValueError:
            entry = None
        if not _whole(entry):
            raise Unreadable(f"line {n} of the list of what they corrected and asked to forget is not a change "
                             f"({ledger_file()})")
        out.append(entry)
    return out


def _whole(entry) -> bool:
    """Whether a row is a change with all its kind needs (a forget row with nothing to apply was
    taken and did nothing): an id and a time; a correction what is true now; a forget its words or the conversation it
    is; an undo the change it undoes; places and messages, when given, as lists of what they name."""
    if not (isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]
            and isinstance(entry.get("at"), (int, float)) and entry.get("kind") in ("correct", "forget", "undo")):
        return False
    if entry["kind"] == "undo":
        return isinstance(entry.get("of"), str) and bool(entry["of"])
    if not all(isinstance(entry.get(k, []), list) for k in ("passages", "messages", "rows")):
        return False
    if not all(isinstance(p, dict) and isinstance(p.get("path"), str) and p["path"] and isinstance(p.get("text"), str)
               and all(_count(p.get(k), 1) for k in ("line", "nth", "of") if k in p)
               for p in entry.get("passages", [])):
        return False
    # A message is named by its row in the record (one identity per message), with its words then.
    if not all(_row_ref(m) and isinstance(m.get("text", ""), str)
               for m in entry.get("messages", [])):
        return False
    if not all(_row_ref(n) for n in entry.get("rows", [])):
        return False
    if not isinstance(entry.get("carry", []), list) or not all(_row_ref(n) for n in entry.get("carry", [])):
        return False
    if (not isinstance(entry.get("sources", []), list)
            or not all(_row_ref(ref) and isinstance(ref.get("call"), str)
                       and isinstance(ref.get("t"), (int, float)) and math.isfinite(ref["t"])
                       for ref in entry.get("sources", []))):
        return False
    if "span" in entry and entry["span"] is not None and not (
            isinstance(entry["span"], dict) and isinstance(entry["span"].get("call", ""), str)
            and all(isinstance(entry["span"].get(k), (int, float)) for k in ("from", "to"))):
        return False
    if any(k in entry and not isinstance(entry[k], str) for k in ("words", "said", "file", "title", "replaces", "by",
                                                                   "call", "sha")):
        return False
    if entry.get("file") and "rows" not in entry:
        return False  # pre-release whole-conversation shapes are not migrated
    if entry["kind"] == "correct":
        return isinstance(entry.get("said"), str) and bool(entry["said"].strip())
    # (a forget's words, the conversation it is, or messages it names whole: some of one conversation)
    return (bool(entry.get("words", "").strip()) or (bool(entry.get("file")) and "rows" in entry)
            or (bool(entry.get("messages")) and not entry.get("passages")))


def _count(value, least: int) -> bool:
    """A whole number at least `least` (never a bool)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= least


def _row_ref(value) -> bool:
    """A row alone can name another message after restore. Its original bytes must match too."""
    return (isinstance(value, dict) and _count(value.get("row"), 1)
            and isinstance(value.get("digest"), str) and re.fullmatch(r"[0-9a-f]{64}", value["digest"]) is not None)


def revision() -> tuple[int, int]:
    """Which version of the change list this is (it only grows): a reader that writes from what it read (a summary,
    the standing view, a greeting written ahead) checks it again before writing."""
    try:
        st = ledger_file().stat()
    except OSError:
        return (0, 0)
    return (st.st_mtime_ns, st.st_size)


@contextlib.contextmanager
def change_lock():
    """Held while a change is written and while a summary or standing view is published from that list: no
    change lands between the last revision check and publication. (A lock file has
    no words in it: an ordinary file beside the list.)"""
    if getattr(_HOLDING, "depth", 0):  # (this thread holds it already: an undo picks its change and writes it under one)
        _HOLDING.depth += 1
        try:
            yield
        finally:
            _HOLDING.depth -= 1
        return
    from core.state import closed_file
    lock = ledger_file().with_name("memory-changes.lock")
    with closed_file(lock, "a") as held:  # (his alone from the start: core/state.py)
        _flock(held, LOCK_WAIT, "the change list is busy")
        _HOLDING.depth = 1
        try:
            yield
        finally:
            _HOLDING.depth = 0
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)


_HOLDING = threading.local()


class TooLate(Exception):
    """A change whose moment passed before it was written (its tool had given way): nothing was written."""


class Turn:
    """A change's moment to be written, shared by the tool that waits for it and the thread that writes it (before,
    a forget she had called "not made" was kept a second later): the write begins before the tool gives way, or it
    never does. The writer asks begin() under the change list's lock, right before writing; the tool asks give_up() when
    its wait runs out ("writing": wait for the receipt; anything else: it was never written, and never will be)."""

    def __init__(self, seconds: float):
        self.deadline, self.state, self._lock = time.monotonic() + seconds, "waiting", threading.Lock()

    def begin(self) -> bool:
        with self._lock:
            if self.state == "waiting" and time.monotonic() <= self.deadline:
                self.state = "writing"
            elif self.state == "waiting":
                self.state = "too late"
            return self.state == "writing"

    def give_up(self) -> str:
        with self._lock:
            if self.state == "waiting":
                self.state = "given up"
            return self.state


LOCK_WAIT = float(os.environ.get("MEMORY_LOCK_WAIT", "10"))  # s: her memory's own locks, at most


def _flock(held, wait: float, busy: str) -> None:
    """An exclusive lock on an open lock file within `wait` seconds, else Unreadable (busy): never a wait without end
    (a lock is per open file, so a second holder in this very process would wait for ever)."""
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError as e:
            if time.monotonic() >= deadline:
                raise Unreadable(f"{busy}; try again in a moment") from e
            time.sleep(0.02)


def record_change(entry: dict, turn: Turn | None = None) -> None:
    """One line, written whole or not at all, under the list's lock: the only thing a change writes (his alone:
    core/state.private_file). A list that cannot be read is not added to (Unreadable); nor is a row that is not a whole
    change. A short write is taken back; a line written whose fsync failed raises Unconfirmed (it may have been
    kept), never "nothing changed". turn: the moment its tool waits for (TooLate when it passed: nothing written)."""
    from core import state
    if not _whole(entry):
        raise ValueError("not a whole change")
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode()
    with change_lock(), state.private_file(ledger_file(), "ab", buffering=0) as f:
        _read_ledger(ledger_file())  # (read whole first, never from a pass: a broken list stays as it is)
        if turn is not None and not turn.begin():
            raise TooLate("its moment passed before it was written")
        start = os.fstat(f.fileno()).st_size
        try:
            written = f.write(line)
        except OSError:
            os.ftruncate(f.fileno(), start)
            raise
        if written != len(line):
            os.ftruncate(f.fileno(), start)
            raise OSError("the change list could not be written whole")
        try:
            os.fsync(f.fileno())
        except OSError as e:
            raise Unconfirmed(f"the disk did not confirm it ({e.strerror or e})") from e


def in_force(changes: list[dict] | None = None) -> list[dict]:
    """The corrections and forgets that still hold (not undone), oldest first. Raises Unreadable (see ledger)."""
    rows = ledger() if changes is None else changes
    record = record_rows()
    if _CHANGES.get("rows") == rows and _CHANGES.get("record") is record:
        return _CHANGES["active"]
    undone = {r.get("of") for r in rows if r.get("kind") == "undo"}
    active = RowChanges([r for r in rows if r.get("kind") in ("correct", "forget") and r.get("id") not in undone],
                        record, rows)
    _CHANGES.update(rows=rows, record=record, active=active)
    return active


_CHANGES: dict = {}


class RowChanges(list):
    """One validated index per record/list version, shared by every message in a refresh."""
    def __init__(self, changes, record, every=None):
        super().__init__(changes)
        self.record, self.by_row, self.named = record, {}, set()
        active = {id(change) for change in changes}
        for change in changes if every is None else every:
            named = {ref["row"] for ref in change.get("messages", []) + change.get("rows", []) if self.matches(ref)}
            self.named.update(named)
            if id(change) in active:
                for row in named:
                    self.by_row.setdefault(row, []).append(change)

    def matches(self, ref):
        return (_row_ref(ref) and ref["row"] <= len(self.record) and self.record[ref["row"] - 1]
                and self.record[ref["row"] - 1]["digest"] == ref["digest"])


def row_changes(changes: list[dict]) -> RowChanges:
    return changes if isinstance(changes, RowChanges) else RowChanges(changes, record_rows())


def _day(at: float) -> str:
    return dt.datetime.fromtimestamp(at).strftime("%-d %b %Y")


@functools.lru_cache(maxsize=256)
def words_pattern(words: str, any_case: bool = True) -> re.Pattern:
    """These exact words, never inside a longer word ("cat" is not in "category")."""
    body = re.escape(words)
    if re.match(r"\w", words[:1]):
        body = r"(?<!\w)" + body
    if re.match(r"\w", words[-1:]):
        body += r"(?!\w)"
    return re.compile(body, re.IGNORECASE if any_case else 0)


def holds(text: str, words: str) -> bool:
    return bool(words) and words_pattern(words).search(text or "") is not None


LEAD = re.compile(r"\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|>\s*|#{1,6}\s+)?")  # (a list mark, a quote, a heading)


def without(line: str, words: str) -> str | None:
    """The line without the sentences that hold `words` (any case); None when nothing of it is left but its mark."""
    lead = LEAD.match(line).group(0)
    body = line[len(lead):]
    hits = [(max(0, m.start() - len(lead)), m.end() - len(lead)) for m in words_pattern(words).finditer(line)]
    if not hits:
        return line
    sentences, start = [], 0
    for end in [m.end() for m in re.finditer(r"[.!?…]+[\"')\]]*(?=\s|$)", body)] + [len(body)]:
        if end > start:
            sentences.append((start, end))
            start = end
    kept = [body[a:b].strip() for a, b in sentences if body[a:b].strip() and not any(h0 < b and h1 > a for h0, h1 in hits)]
    rest = " ".join(kept)
    return lead + rest if rest else None


def _same(a: str, b: str) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def line_mark(line: str) -> str:
    """Which words a line holds, without them: what the memory page keeps of the line it showed, to be sure a change
    it sends acts on that line as it still is (never the words themselves: they may be what was forgotten)."""
    import hashlib
    return hashlib.sha256(" ".join((line or "").split()).encode()).hexdigest()[:20]


_LINES: dict[str, tuple[tuple[int, int], list[str]]] = {}  # (a Life file's lines, by its version: placed() reads them)


def _file_lines(rel: str) -> list[str] | None:
    root = life()
    if not root or not rel:
        return None
    path = root / rel
    try:
        st = path.stat()
        key = (st.st_dev, st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)  # (a copy keeping the time is another)
        if (hit := _LINES.get(str(path))) and hit[0] == key:
            return hit[1]
        lines = path.read_text(errors="replace").split("\n")
    except OSError:
        return None
    _LINES[str(path)] = (key, lines)
    return lines


def placed(passage: dict) -> tuple[str, int | None]:
    """Where a passage a change names stands in its file now: ("exact", n) its words at line n; ("moved", None) its
    words are no longer where they can be told apart (edited since, by Sleep, main Viventium or him): the change's own
    words apply in that file only; ("gone", None) there is no such file. Identical lines are separate passages (the
    Dentist's and the Vet's appointments): the one still at its line, else the same one of as many identical lines as
    when it was named (`nth` of `of`), else, with more of them now, the nearest; with fewer, it cannot be told which
    was edited: moved."""
    lines = _file_lines(passage.get("path", ""))
    if lines is None:
        return ("gone", None)
    text = passage.get("text", "")
    hits = [n for n, line in enumerate(lines, 1) if _same(line, text)]
    saved, nth, of = int(passage.get("line") or 0), passage.get("nth"), passage.get("of")
    if saved in hits:
        return ("exact", saved)
    if hits and of and len(hits) == of and nth and 1 <= nth <= of:
        return ("exact", hits[nth - 1])
    if hits and (not of or len(hits) > of):
        return ("exact", min(hits, key=lambda n: (abs(n - saved), n)))
    return ("moved", None)


def _names(change: dict, path: str, line: str, number: int | None = None) -> bool:
    """Whether a change is about this line (number: its line in the file, when known) of this Life file: the passage it
    names, at its place now (placed); a named passage edited since: a line of the same file holding the change's words."""
    for p in change.get("passages", []):
        if p.get("path") != path:
            continue
        how, at = placed(p)
        if how == "exact" and (number == at if number is not None else _same(p.get("text", ""), line)):
            return True
        if how == "moved" and holds(line, change.get("words", "")):
            return True
    if change.get("carry") and kind_of(path) == "summary" and all(p.get("path") != path for p in change.get("passages", [])):
        older, rows = _stood(path)  # (a summary of hers written again from a stretch the change was carried onto)
        if not older and rows & {ref.get("row") for ref in change["carry"] if isinstance(ref, dict)}:
            return any(holds(line, words) for words in carry_words(change))
    return False


def carry_words(change: dict) -> list[str]:
    """The words a change on a summary's lines carries onto that summary's stretch: its own words, else
    (a correction named by its place alone) the words of each summary line it named."""
    if change.get("words"):
        return [change["words"]]
    return [words for p in change.get("passages", []) if kind_of(p.get("path", "")) == "summary"
            and (words := LEAD.sub("", str(p.get("text", "")), count=1).strip())]


def summary_input(rows: list[dict]) -> list[dict]:
    """What a summary is written from: the messages as they stand now (current_rows) and, on the stretch of a summary
    whose lines a change named (its carry: the messages that summary stood for), that change's words left out (a
    forget) or corrected (a correction), as every reader of that summary showed them (a line forgotten
    on an older summary came back when its conversation was written again from the record). Raises Unreadable."""
    now = current_rows(rows)
    carried: dict[int, list[dict]] = {}
    for change in in_force():
        for ref in change.get("carry", []) if isinstance(change.get("carry"), list) else []:
            if isinstance(ref, dict) and ref.get("row"):
                carried.setdefault(int(ref["row"]), []).append(change)
    if not carried:
        return now
    out = []
    for row in now:
        text = row["text"]
        for change in carried.get(row.get("row") or 0, []):
            flat = " ".join(text.split())
            words = next((w for w in carry_words(change) if holds(flat, " ".join(w.split()))), "")
            if not words:
                continue
            if change["kind"] == "forget":
                text = _drop(text, words)
                if text is None:
                    break
            else:
                text = tagged(text, change)
        if text and text.strip():
            out.append({**row, "text": text})
    return out


_RECORD: dict = {}  # (the conversation record's rows, read once per version of it: record_rows)


def record_rows(path: Path | None = None) -> list[dict | None]:
    """One record reader: LF-terminated JSON lines only, None for malformed complete lines.

    A restore or an in-place rewrite changes file identity, even with the same size, mtime and tail.
    Each valid row carries the SHA-256 of its own original line, excluding the terminating LF.
    An explicit path lets offline readers use exactly this parser too.
    """
    from core import relationship
    path = relationship.LOG if path is None else path
    try:
        st = path.stat()
    except FileNotFoundError:
        _RECORD.clear()
        return []
    except OSError as e:
        raise Unreadable(f"the conversation record cannot be read ({e.strerror or type(e).__name__})") from e
    key = (st.st_dev, st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)
    if _RECORD.get("path") == str(path) and _RECORD.get("key") == key:
        return _RECORD["rows"]
    rows, items = [], {}
    try:
        data = path.read_bytes()
    except OSError as e:
        raise Unreadable(f"the conversation record cannot be read ({e.strerror or type(e).__name__})") from e
    if data:
        # Whole lines only: a line still being written is read once it is whole. Read half, it would count as a row of
        # its own and its rest as the next, every later row one off for as long as this process runs.
        data = data[:data.rfind(b"\n") + 1]
        for raw in data.split(b"\n")[:-1]:
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                row = None
            rows.append({**row, "digest": hashlib.sha256(raw).hexdigest()} if isinstance(row, dict) else None)
            if rows[-1] and rows[-1].get("item"):
                items[str(rows[-1]["item"])] = len(rows)
    _RECORD.update(path=str(path), key=key, rows=rows, items=items)
    return rows


def row_ref(row: int) -> dict:
    rows = record_rows()
    return {"row": row, "digest": rows[row - 1]["digest"]} if 0 < row <= len(rows) and rows[row - 1] else {}


def matches(ref: dict) -> bool:
    return _row_ref(ref) and row_ref(ref["row"]) == {"row": ref["row"], "digest": ref["digest"]}


def numbered(rows: list[dict | None] | None = None) -> list[dict]:
    """The record's messages, each with its row ("row"): what every reader of the conversation carries."""
    return [{**row, "row": n} for n, row in enumerate(record_rows() if rows is None else rows, 1) if row]


def row_of_item(item_id: str) -> int:
    """The row of the message a live conversation's item became (core/relationship.append keeps its id), 0 if none."""
    record_rows()
    return int(_RECORD.get("items", {}).get(str(item_id), 0)) if item_id else 0


def row_text(row: int) -> str | None:
    """A row's own words, as the record keeps them (the original: never a text already shown otherwise)."""
    rows = record_rows()
    return str(rows[row - 1].get("text") or "") if 0 < row <= len(rows) and rows[row - 1] else None


def _named_rows(change: dict) -> set[int]:
    """Only references whose original record line is still at that row may change it."""
    return row_changes([change]).named


def _drop(text: str, words: str) -> str | None:
    """A message without the sentences that hold `words`: line by line, or, when the words run across its lines, the
    message read as one (a named message of two lines, its whole two lines given, was left as it was). None
    when nothing is left, or when the words are not in it at all (named without its words: the whole message)."""
    flat_words = " ".join((words or "").split())
    if not flat_words or not holds(" ".join(text.split()), flat_words):
        return None
    lines = text.split("\n")
    if any(holds(line, flat_words) for line in lines):
        kept = [line for line in (without(line, flat_words) for line in lines) if line is not None]
        return "\n".join(kept) if any(line.strip() for line in kept) else None
    return without(" ".join(line.strip() for line in lines if line.strip()), flat_words)


def row_now(row: int, text: str | None = None, changes: list[dict] | None = None) -> str:
    """A message as it stands now, by its row and original-line digest: "" when a change left it out (named whole, or its
    conversation forgotten whole); without the sentences a forget naming it took; its latest correction first. Never
    by its words or its time. text: its words, when the caller has them (else the record's). A Worker's
    result a forget names is left out whole: it is one report, and its words around what was found (the job, his
    request, the files it made) are not lines to cut (the page offers it in plain words, and its forget
    covers that row)."""
    changes = in_force() if changes is None else row_changes(changes)
    source = changes.record[row - 1] if 0 < row <= len(changes.record) else None
    text = str(source.get("text") or "") if text is None and source else text
    if text is None:
        return ""
    out = text
    for change in changes.by_row.get(row, []):
        if change["kind"] != "forget":
            continue
        if change.get("rows") and not change.get("messages"):
            return ""  # (a conversation forgotten whole)
        if source and source.get("role") == "worker":
            return ""  # (a Worker's result, named: the whole report)
        out = _drop(out, change.get("words", ""))
        if out is None:
            return ""
    fixes = [c for c in changes.by_row.get(row, []) if c["kind"] == "correct"]
    return tagged(out, fixes[-1]) if fixes else out


# What a reader shows before a line, never cut: the correction (what is true now) and a part left out. A line read with
# its correction after it lost the correction to any shortening (a 307-character line came back saying
# Ghent, without "I live in Leuven now").
ANNOTATION = re.compile(r'^((?:\d+:\s?)?\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|>\s*|#{1,6}\s+)?)'
                        r'((?:\[the user corrected this on [^\]"]*: "[^"]*"\]\s?|\(part of this line is left out: the user '
                        r'asked not to bring it back\)\s?)+)')  # (whole, also when what followed it was cut: "…")


def tagged(line: str, fix: dict) -> str:
    """The line with what is true now first (the user's words: their own double quotes become single ones)."""
    lead = LEAD.match(line).group(0)
    said = str(fix.get("said", "")).replace('"', "'")
    return f'{lead}[the user corrected this on {_day(fix["at"])}: "{said}"] {line[len(lead):]}'


def cut(line: str, room: int) -> str:
    """A line within `room` characters, its correction and its left-out mark whole whatever the room."""
    if len(line) <= room:
        return line
    m = ANNOTATION.match(line)
    keep = m.end() if m else 0
    return (line[:keep] if keep >= room and keep else line[:max(0, room - 1)]).rstrip() + ("…" if room > 0 or keep else "")


FIX = "[the user corrected this on "


def units(text: str) -> list[str]:
    """Text as what is shown together: a line, or the lines a correction runs across (a correction holding a line break
    stays one, never split)."""
    out, open_unit = [], None
    for line in text.split("\n"):
        if open_unit is not None:
            open_unit += "\n" + line
            if '"]' in line:
                out.append(open_unit)
                open_unit = None
            continue
        at = line.find(FIX)
        if at >= 0 and '"]' not in line[at:]:
            open_unit = line
        else:
            out.append(line)
    return out + ([open_unit] if open_unit is not None else [])


def latest_fix(changes: list[dict], about) -> dict | None:
    """The correction that holds for a passage: the newest one naming it (a later correction of the same passage, or of
    an earlier correction by its id, holds over it; never one that merely shares words: Ilse's
    correction had become Leo's)."""
    fixes = [c for c in changes if c["kind"] == "correct" and about(c)]
    return fixes[-1] if fixes else None


def current(text: str, made: float = 0.0, changes: list[dict] | None = None, path: str = "",
            first: int | None = None, call: str = "") -> str:
    """Text read from Life or from the conversation, as it stands now, by the change list.
    path: the Life file it is from, its first line being line `first` of the file (None: not known, then a passage is
    told by its words alone, so a line is never missed): a change applies to the passages it names (placed: at their
    place now, whatever the file's time; a note touched later must not bring a forgotten line back). No path: nothing
    applies (a conversation message goes by its row in the record: row_now, current_rows; never by its words or its
    time).
    A forget drops the sentences that hold its words (the whole line when its words are not in it); a correction puts
    what is true now first, the latest correction of that passage, in the user's own words. Raises Unreadable."""
    changes = in_force() if changes is None else changes
    if path and kind_of(path) == "summary":
        if root := life():
            if issue := source(path, root).get("unreadable"):
                return f"This summary cannot be read: {issue}."
        # Pre-sidecar summaries remain readable, but their identity is never prose.
        text = "\n".join("" if line.startswith(("- **row digests:**", "- **rows:**")) else line
                         for line in text.split("\n"))
    if not changes or not text:
        return text
    if not path:
        return text  # (a conversation message goes by its row: row_now, current_rows)
    out = []
    for i, line in enumerate(text.split("\n")):
        read, number = line, (first + i if first is not None else None)  # (matched to the line as read)
        about = lambda c: _names(c, path, read, number)  # noqa: E731
        for change in [c for c in changes if c["kind"] == "forget" and about(c)]:
            words = change.get("words", "")
            line = without(line, words) if words and holds(line, words) else None
            if line is None:
                break
        if line is None:
            continue
        if fix := latest_fix(changes, about):
            line = tagged(line, fix)
        out.append(line)
    return "\n".join(out)


class _Skipped(set):
    """The summaries readers skip: each file a whole-conversation forget names and, under any other name, a summary of
    the messages one names (a copy or a rename of it). Membership is asked per summary (`rel in gone`)."""

    def __init__(self, files: set[str], rows: set[int], shas: set[str] = frozenset()):
        super().__init__(files)
        self.rows, self.shas = rows, shas

    def __contains__(self, rel) -> bool:
        if set.__contains__(self, rel):
            return True
        if not isinstance(rel, str) or kind_of(rel) != "summary":
            return False
        return bool(self.rows and _stood(rel)[1] & self.rows) or bool(self.shas and _text_sha(rel) in self.shas)


def _text_sha(rel: str) -> str:
    """A Life file's text by its hash (a byte-identical copy of a summary forgotten whole), once per pass."""
    def made() -> str:
        try:
            return hashlib.sha256(_file_text(life() / rel).encode()).hexdigest()
        except (OSError, TypeError):
            return ""
    return _once(("sha", rel), made)


def skipped(changes: list[dict] | None = None) -> set[str]:
    """Life files a reader skips: Light's own summaries of conversations forgotten whole (kept, never deleted), by their
    file and by the messages they stand for."""
    changes = in_force() if changes is None else changes
    whole = [c for c in changes if c["kind"] == "forget" and c.get("file")]
    return _Skipped({c["file"] for c in whole},
                    {ref["row"] for c in whole for ref in c.get("rows", []) if isinstance(ref, dict) and ref.get("row")},
                    {c["sha"] for c in whole if isinstance(c.get("sha"), str) and c["sha"]})


def _stood(rel: str) -> tuple[bool, frozenset]:
    """(an older summary, the record rows a summary stands for): one of hers, the rows its entry in her index names
    (else, a copy or a rename with no entry of its own, its identity as read: recovered from times); an older one, its
    conversation's rows inside its stated minutes. Empty when that cannot be known. Once per summary in a pass."""
    def made() -> tuple[bool, frozenset]:
        from core.memory import _span
        root = life()
        if not root:
            return False, frozenset()
        path = root / rel
        try:
            head = _summary_meta_text(_file_text(path))
            if _older(head):
                span = _span(head)
                return True, frozenset(row["row"] for row in _stated(span["call"], head, span)) if span else frozenset()
            entry = _read_summary_index(_summary_index_path(path)).get(rel)
            versions = list(entry.get("versions", {}).values()) if isinstance(entry, dict) and \
                isinstance(entry.get("versions"), dict) else []
            refs = (versions[-1].get("row digests") if versions and isinstance(versions[-1], dict) else None) \
                or _summary_meta(path).get("row digests", "[]")
            refs = json.loads(refs)
            return False, frozenset(ref["row"] for ref in refs if isinstance(ref, dict) and ref.get("row"))
        except (OSError, Unreadable, TypeError, ValueError, KeyError, OverflowError, AttributeError):
            return False, frozenset()
    return _once(("stood", rel), made)


def superseded(rel: str) -> bool:
    """An older summary retired and written again since (RETIRED_REBUILT): readers leave it out, its new summary holds
    what is left of it. Only an older summary can be (one of hers is written in its place)."""
    root = life()
    if not root or kind_of(rel) != "summary":
        return False

    return bool(source(rel, root).get("superseded"))  # (what every reader asks first anyway: once per pass)


def summary_stretch(rel: str) -> list[dict]:
    """The messages a summary stands for, by row and digest: what a change on its lines is carried onto, so the
    summary written again from them leaves it out, or corrects it, too. [] when that cannot be known."""
    root = life()
    if not root:
        return []
    record = record_rows()
    return [{"row": n, "digest": record[n - 1]["digest"]} for n in sorted(_stood(rel)[1])
            if 0 < n <= len(record) and record[n - 1]]


def current_rows(rows: list[dict], keep_gone: bool = False) -> list[dict]:
    """Conversation messages (the record's rows, each carrying its row number "row") as they stand now, by their rows
    alone (row_now). A message left out is dropped, or with keep_gone kept as a placeholder that still carries its row
    (a new conversation's history: an undo then brings it back in place). For a new conversation's history, the
    night's day, summaries and the record Workers read (record_now). Raises Unreadable."""
    changes = in_force()
    out = []
    for row in rows:
        if not row.get("row"):
            out.append(row)  # (not a message of the record: nothing names it)
            continue
        stale = row.get("digest") and not changes.matches(row)
        text = "" if stale else row_now(int(row["row"]), str(row.get("text") or ""), changes)
        if text.strip():
            out.append({**row, "text": text})
        elif keep_gone:
            out.append({**{k: v for k, v in row.items() if k not in ("files", "whole")},
                        "text": LEFT_OUT, "left_out": True})
    return out


LEFT_OUT = "(left out here: the user asked not to bring this back)"
PART_LEFT_OUT = "(part of this line is left out: the user asked not to bring it back)"


RECORD_FORM = "2"  # (the form of record_now's lines: a copy written in an earlier form is written again)


def record_now(whose: str = "") -> Path:
    """The conversation record as it stands now (current_rows), in a private file beside it: what a Worker, a cortex
    or the night is pointed at to look something up, never the record itself (which keeps every word as said). Line
    for line with the record (a message left out keeps its line, with no words: never "left out here", which told a
    cortex on a Worker the fact of a forget), so a line number named elsewhere (the night's day
    file) is the same in both. Written again only when either has changed (or its own form: RECORD_FORM). whose: a
    reader that must keep its own files (each night routine: Sleep's and Dreaming's never shared, tests/probes/r37)."""
    from core import relationship
    out = ledger_file().with_name(f"conversation-now{'-' + whose if whose else ''}.jsonl")
    try:
        st = relationship.LOG.stat()
        stamp = f"{st.st_dev}:{st.st_ino}:{st.st_ctime_ns}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        stamp = "none"
    stamp += ":%d:%d" % revision() + f":{RECORD_FORM}"
    mark = out.with_suffix(".stamp")
    changes = in_force()  # (Unreadable: no copy is offered at all, not even the one made before)
    try:
        if mark.read_text() == stamp and out.exists():
            return out
    except OSError:
        pass
    out_lines = []
    for n, row in enumerate(record_rows(), 1):
        if row is None:
            out_lines.append(json.dumps({"text": ""}))  # (a line that cannot be read is not passed on)
            continue
        text = row_now(n, str(row.get("text") or ""), changes) if changes else str(row.get("text") or "")
        out_lines.append(json.dumps({**row, "text": text} if text.strip() else {
            **{k: row[k] for k in ("t", "role", "channel", "call_id") if k in row}, "text": ""}))
    from core import state
    temp = out.with_suffix(f".{os.getpid()}.tmp")
    try:
        with state.private_file(temp, "w") as f:
            f.writelines(line + "\n" for line in out_lines)
        temp.replace(out)
        with state.private_file(mark, "w") as f:
            f.write(stamp)
    except OSError:
        state.optional_write_failed("history_view")
        raise
    return out


def record_where(whose: str = "") -> str:
    """Where the record as it stands now is, as a reader's instructions name it (record_now): its path, or, when the
    private copy cannot be written or the change list cannot be read, a sentence saying so. Never the record itself,
    and never a failed conversation start or night for want of a path."""
    try:
        return str(record_now(whose))
    except OSError as error:
        return f"(not available here: the record as it stands now could not be written, {error.strerror or error})"


NOTE_ROOM = 2400  # the room for corrections in the note; every forget is named whatever its length


def _superseded(c: dict, later: list[dict]) -> bool:
    """A correction a later one replaces: by its id, or by naming every passage and message it named. Or one a later
    forget takes back whole: it takes every passage and message the correction named, whole (before,
    he corrected a line, then forgot it and every place the page offered, and her note still said "Corrected: Clara
    lives in Porto now"). A forget of part of a corrected line leaves the correction on the rest of it."""
    if c["kind"] != "correct":
        return False
    keys = {(p.get("path"), p.get("line"), " ".join(str(p.get("text", "")).split())) for p in c.get("passages", [])}
    said = {json.dumps(m, sort_keys=True) for m in c.get("messages", [])}
    for d in later:
        if d["kind"] == "forget" and (keys or said) and _takes_whole(d, c):
            return True
        if d["kind"] != "correct":
            continue
        if d.get("replaces") == c["id"]:
            return True
        theirs = {(p.get("path"), p.get("line"), " ".join(str(p.get("text", "")).split())) for p in d.get("passages", [])}
        if (keys or said) and keys <= theirs and said <= {json.dumps(m, sort_keys=True) for m in d.get("messages", [])}:
            return True
    return False


def _takes_whole(forget: dict, c: dict) -> bool:
    """Whether a forget takes whole every passage and message a change named: each passage named by it too (the same
    line of the same file) and nothing of its words left by it (without), each message named by it with nothing of its
    words left (_drop), or in a conversation it forgets whole (its rows)."""
    words = forget.get("words", "")
    theirs = {(p.get("path"), p.get("line"), " ".join(str(p.get("text", "")).split())) for p in forget.get("passages", [])}
    for p in c.get("passages", []):
        text = str(p.get("text", ""))
        if (p.get("path"), p.get("line"), " ".join(text.split())) not in theirs:
            return False
        if words and holds(text, words) and without(text, words) is not None:
            return False  # (part of the line is left: the correction still holds on it)
    whole = {(r.get("row"), r.get("digest")) for r in forget.get("rows", []) if isinstance(r, dict)}
    named = {(m.get("row"), m.get("digest")) for m in forget.get("messages", []) if isinstance(m, dict)}
    for m in c.get("messages", []):
        key = (m.get("row"), m.get("digest"))
        if key in whole:
            continue
        if key not in named or (words and holds(str(m.get("text", "")), words)
                                and _drop(str(m.get("text", "")), words) is not None):
            return False
    return True


def corrections_told(changes: list[dict] | None = None) -> list[dict]:
    """The corrections her standing note says in words (changes_note), oldest first: in force, neither replaced nor
    taken back whole by a later forget, each naming a place or a message still there. Raises Unreadable."""
    live = in_force() if changes is None else changes
    out = []
    for i, c in enumerate(live):
        refs = c.get("messages", []) + c.get("rows", [])
        if c["kind"] != "correct" or (refs and not c.get("passages") and not any(matches(ref) for ref in refs)):
            continue
        if not _superseded(c, live[i + 1:]):
            out.append(c)
    return out


def changes_note(changes: list[dict] | None = None, forgets: bool = True) -> str:
    """The change list in words, for every model that reads raw Life or writes what she reads (a Worker's brief, the
    summary writer, the standing view's rebuild, the night): it catches the same thing said in other words, which no
    filter can. Every forget is named, always (it is the only guard against the same thing in other words: before,
    the oldest fell out after 20 changes), and such a writer is told to leave it out without a word that it was there;
    corrections, newest first, within NOTE_ROOM (an older one left out of the words still holds on every passage it
    names). forgets=False: corrections only, for her own context and her own mind's parts (core(), the cortices):
    nothing of a forget reaches her, not its words and not that there was one (told the forget,
    she said "the plans I remember are something you asked me not to bring up"); a forget acts on the places it names,
    and the memory page offers every other place still holding it. "" with nothing to say. Raises Unreadable."""
    live = in_force() if changes is None else changes
    if not live:
        return ""
    forgotten, fixes = [], []
    for i, c in enumerate(live):
        refs = c.get("messages", []) + c.get("rows", [])
        if refs and not c.get("passages") and not c.get("file") and not any(matches(ref) for ref in refs):
            continue  # a stale message reference gives no instruction about the replacement record
        day = _day(c["at"])
        if c["kind"] == "correct":
            if not _superseded(c, live[i + 1:]):
                was = f' (it was: "{c["words"]}")' if c.get("words") else ""
                fixes.append((i, f'- Corrected on {day}: "{c.get("said", "")}"{was}.'))
        elif not forgets:
            continue
        elif c.get("file"):
            forgotten.append((i, f'- Not to bring back (asked on {day}): anything from the conversation '
                                 f'"{c.get("title") or c["file"]}"' + (f' of {_day(c["span"]["from"])}' if c.get("span") else "") + "."))
        else:
            forgotten.append((i, f'- Not to bring back (asked on {day}): "{c.get("said") or c.get("words", "")}".'))
    kept, size = [], 0
    for i, line in reversed(fixes):
        if kept and size + len(line) + 1 > NOTE_ROOM:
            break
        kept.append((i, line))
        size += len(line) + 1
    more = len(fixes) - len(kept)
    shown = [line for _, line in sorted(forgotten + kept)]
    if not shown:
        return ""
    return ("What the user changed in what you remember, newest last. It holds over anything else you are told or find "
            "about the same thing, in whatever words; their own notes are not changed by it"
            + ("; what they asked not to bring back is left out wholly, and nothing you write or say hints that it was "
               "there or that they asked" if forgotten else "") + ":\n" + "\n".join(shown)
            + (f"\n({more} older corrections are not listed here; each still holds where it is noted: on the memory "
               "page.)" if more else ""))


def _llm(prompt: str, max_tokens: int = 1200) -> str:
    """One background completion on the memory model (local profile: the Workers' server). Accuracy over
    speed: it thinks first (memory must be true), with room to think beyond the answer's own budget; if
    thinking still uses it all, once more without thinking. "" only if both give nothing."""
    from core import chatgpt_authorization as auth, helpers
    with auth.use(None):
        if helpers.online():  # (Hybrid and Cloud: Claude, then OpenAI, then this Mac; each thinks before it writes)
            return helpers.ask([{"role": "user", "content": prompt}], max_tokens=max_tokens, wait=900, think=True).text
    from openai import OpenAI
    client = OpenAI(base_url=os.environ["MEMORY_URL"], api_key="local", timeout=900)
    for effort, budget in (("high", max_tokens + 8000), ("none", max_tokens)):
        reply = client.chat.completions.create(
            model=os.environ.get("MEMORY_MODEL", "qwen3.6:latest"), max_tokens=budget,
            messages=[{"role": "user", "content": prompt}], extra_body={"reasoning_effort": effort})
        if text := (reply.choices[0].message.content or "").strip():
            return text
    return ""


UNREADABLE_NOTE = ("(What you remember of the user cannot be read right now: {why}. Nothing from it is shown here; if "
                   "they ask what you remember, tell them it is not available, and never guess it.)")


def core(forgets: bool = False) -> str:
    """Her standing knowledge of you (≤ ~600 words, Views/, rebuilt daily) as it stands now, then what he corrected,
    in words: her instructions on every channel and the greeting written ahead carry this (brain/queen.py). Nothing of
    a forget is in it (changes_note); forgets=True adds them, for a Worker's brief (a Worker reads his Life
    raw: the note in words is its only guard). "" with neither. When the change list cannot be read: a sentence saying
    so, and nothing of the view (it could hold what they asked to forget)."""
    root = life()
    path = root / "Views" / CORE_NAME if root else None
    text = path.read_text(errors="replace") if path and path.exists() else ""
    try:
        changes = in_force()
    except Unreadable as e:
        return UNREADABLE_NOTE.format(why=e) if root else ""
    text = current(text, 0.0, changes, f"Views/{CORE_NAME}", first=1).strip() if text else ""
    return "\n\n".join(part for part in (text, changes_note(changes, forgets=forgets)) if part)


def core_version() -> float:
    """When what core() gives last changed (the view rebuilt, or a change made): a live Queen picks up the new one on
    its next turn."""
    root = life()
    path = root / "Views" / CORE_NAME if root else None
    stamps = [path.stat().st_mtime if path and path.exists() else 0.0]
    try:
        stamps.append(ledger_file().stat().st_mtime)
    except OSError:
        pass
    return max(stamps)


def _core_stamp() -> Path:
    from core import state
    return state.STATE_ROOT / "memory" / "core-built"


def _core_changes_stamp() -> Path:
    """Up to when his changes are in the standing view: a section a change touched is written again by itself
    (refresh_core), which never moves the daily rebuild."""
    from core import state
    return state.STATE_ROOT / "memory" / "core-changes"


def _core_built(path: Path) -> float:
    """When the core view was last written whole by its model: the stamp refresh_core leaves, else the time its own
    first line gives, else the file's time."""
    try:
        return float(_core_stamp().read_text())
    except (OSError, ValueError):
        pass
    try:
        with path.open(errors="replace") as f:
            first = f.readline()
        if m := re.search(r"on (\d{4}-\d\d-\d\d \d\d:\d\d)", first):
            return dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").timestamp()
    except (OSError, ValueError):
        pass
    return path.stat().st_mtime


def core_applied(path: Path) -> float:
    """Up to when the standing view holds his changes: its last whole writing, or a section written again since."""
    try:
        since = float(_core_changes_stamp().read_text())
    except (OSError, ValueError):
        since = 0.0
    return max(_core_built(path), since)


def _core_whole_due(path: Path) -> bool:
    """Whether the standing view is due to be written whole: none yet, a day old, or within the hour after a
    conversation it has not learned from (a new summary updates its month's folder)."""
    root = life()
    if not root or not path.exists():
        return True
    now, built = dt.datetime.now(), _core_built(path)
    if now.timestamp() - built > CORE_MAX_AGE_H * 3600:
        return True
    month = root / "Memory" / "Conversations" / f"{now:%Y}" / f"{now:%m}"
    return now.timestamp() - built > CORE_LEARN_H * 3600 and month.exists() and month.stat().st_mtime > built


def core_is_stale() -> bool:
    """Daily, within the hour after a conversation it has not learned from yet (a new user's name, a trip), or once
    the user has corrected or forgotten something since it was written (refresh_core writes again the sections that
    change touched, told the list, and keeps every other section byte for byte): the core grows the same day, at most
    hourly for a new conversation (it is one background model call; core/clock.py's upkeep starts it, never during a
    call)."""
    root = life()
    from core import helpers
    if not root or not helpers.available():
        return False
    path = root / "Views" / CORE_NAME
    try:
        rows = ledger()
    except Unreadable:
        return False  # (never rebuilt from a list that cannot be read: it would bring back what they forgot)
    try:
        tried = float(_core_tried_stamp().read_text())
    except (OSError, ValueError):
        tried = 0.0
    if tried and time.time() - tried < CORE_RETRY and not any(float(c.get("at") or 0) > tried for c in rows):
        return False  # (it was just tried and gave nothing usable: again after CORE_RETRY, or at once for a new change)
    if _core_whole_due(path):
        return True
    applied = core_applied(path)
    return any(float(c.get("at") or 0) > applied for c in rows)


# The standing view's sections, the runtime's own (the model had written them without their "## "
# marks, and the memory page offered each title as a line to correct or forget). The runtime writes the titles; the
# model writes only what is under them.
CORE_SECTIONS = ("Who you are (Viventium)", "Who I am (the user)", "How I like to be spoken to",
                 "What matters to me now", "People and pets")
CORE_HEAD = ("<!-- Generated by Viventium AI from Life/AGENTS.md, Self/ and recent Memory/Conversations on {when}. "
             "Regenerated daily; edit the sources, not this view. -->")


def _title_key(text: str) -> str:
    """A title by its words alone: no marks, no case, no parenthesis ("Who I am" is "Who I am (the user)")."""
    text = re.sub(r"\([^)]*\)", " ", text.casefold().replace("&", " and "))
    return re.sub(r"[^0-9a-z]+", "", text)


_TITLES = {_title_key(title): title for title in CORE_SECTIONS}


def _title_parts(line: str) -> tuple[str, str]:
    """(the standing view's section title a line starts with, the words after it on the same line), whatever marks or
    numbering a model wrote around it: "## People and pets", "**People and pets:**", "People and pets", "## 2. Who I
    am", "**Who I am:** I am Noor." (a writing with such titles had been taken as none). ("", "") for a
    line that is no title."""
    rest = re.sub(r"^\s{0,3}#{1,6}\s*", "", line.strip())
    if bold := re.match(r"^(\*\*|__)(.+?)\1\s*:?\s*(.*)$", rest):
        head, after = bold.group(2), bold.group(3)
    else:
        head, _, after = rest.partition(":")
    head = re.sub(r"^\d+[.)]\s*", "", head.strip().strip("*_ ").rstrip(":").strip("*_ "))
    title = _TITLES.get(_title_key(head), "") if head and len(head) <= 60 else ""
    return (title, after.strip().strip("*_").strip()) if title else ("", "")


def core_title(line: str) -> str:
    """The standing view's section title a line is, whatever marks or numbering were written around it ("## People and
    pets", "**People and pets:**", "People and pets", "## 5. People and pets"); "" when it is none, or when words of
    the section follow it on the line (_title_parts reads those, as core_sections does)."""
    title, after = _title_parts(line)
    return "" if after else title


def core_sections(text: str) -> dict[str, str]:
    """The standing view's sections by their titles (_title_parts: words written after a title on its line are the
    section's first line), each body as written, line for line, without the blank lines around it. A title the text
    does not have is not in it; what comes before the first title (its note) is no section's. A title said twice keeps
    its first body."""
    out: dict[str, str] = {}
    title, lines = "", []

    def put() -> None:
        if title and title not in out:
            out[title] = "\n".join(lines).strip("\n")
    for line in text.split("\n"):
        found, after = _title_parts(line)
        if found:
            put()
            title, lines = found, ([after] if after else [])
        elif title:
            lines.append(line)
    put()
    return out


def _core_body(text: str) -> str:
    """What a model wrote under a title, as a body: its lines, without a heading of its own (a heading it adds is no
    fact: kept, it would show on the memory page as a title of its own, or, without its marks, as a line to correct or
    forget), without blank lines around it."""
    lines = [line.rstrip() for line in text.split("\n") if not re.match(r"^\s{0,3}#{1,6}(\s|$)", line)]
    return "\n".join(lines).strip("\n").strip()


def _core_text(sections: dict[str, str], head: str = "") -> str:
    """The standing view as the runtime writes it: its note (the one it had, when only a section is written again: its
    time is that of the last whole writing), then each fixed title as a "## " heading and its body."""
    return ((head or CORE_HEAD.format(when=f"{dt.datetime.now():%Y-%m-%d %H:%M}")) + "\n"
            + "\n\n".join(f"## {title}\n{sections.get(title, '')}".rstrip("\n") for title in CORE_SECTIONS) + "\n")


def _users_part(summary: str) -> str:
    """A conversation summary without its "Assistant …" sections (Light's own summary format, below):
    what she said or offered once must not become who she is (a refusal to send a voice note had become
    a standing rule in her core view, and she then refused every voice note)."""
    return re.sub(r"(?ms)^#{2,4} Assistant[^\n]*\n.*?(?=^#{1,4} |\Z)", "", summary)


def _now_text(path: Path, root: Path, changes: list[dict]) -> str:
    """A Life file's text as it stands now, by the change list (the passages it names)."""
    if issue := source(str(path.relative_to(root)), root).get("unreadable"):
        return f"This summary cannot be read: {issue}."
    text = current(_file_text(path), 0.0, changes, str(path.relative_to(root)), first=1)
    return "\n".join(line for line in text.split("\n") if not line.startswith(("- **row digests:**", "- **rows:**")))


def _within(text: str, room: int, what: str) -> str:
    """Text for a prompt within its room; cut only with a line that says so (never silently)."""
    if len(text) <= room:
        return text
    return text[:room] + f"\n(… {len(text) - room:,} more characters of {what} are not shown here.)"


def refresh_core() -> None:
    """The standing view written again (core_is_stale says when). Whole when it is due whole (none yet, a day old, a
    conversation it has not learned from) or not yet in its five sections: from his Life and his recent conversations.
    Otherwise, after his changes, only the sections a change touched (a correction or a forget naming one of its lines,
    or an undo of one), each written again by itself; every other section is kept byte for byte (before,
    every change had the whole view written again 24 s later, its untouched lines reworded each time, and once its
    titles without their marks). Either way the runtime writes the five titles, and a model only what is under them.
    A writing a change raced is not kept: it stays due, and is told the change."""
    root = life()
    began, first = time.time(), revision()
    path = root / "Views" / CORE_NAME
    try:
        old = path.read_text(errors="replace") if path.exists() else ""
    except OSError:
        old = ""
    had = core_sections(old)
    with one_pass():  # (what it reads: the change list, the record and the summary folder once)
        try:
            changes, rows = in_force(), ledger()
        except Unreadable:
            return  # (never rebuilt from a list that cannot be read)
        # What they changed comes first, in words, and holds over the rest whatever words it uses (a conversation
        # forgotten whole is named by its title: what this view learned from it before goes too).
        note = changes_note(changes)
        whole = len(had) < len(CORE_SECTIONS) or _core_whole_due(path)
        touched = None if whole else _core_touched(old, changes, rows, core_applied(path))
        if touched is None:
            whole, asks = True, {}
            prompt = _core_whole_prompt(root, changes, note)
        else:
            asks = {title: _core_section_prompt(title, old, had, wants, changes, note) for title, wants in touched.items()}
    if whole:
        made = {title: _core_body(body) for title, body in core_sections(_llm(prompt, max_tokens=1500) or "").items()}
        if not made:  # (nothing, or none of its sections: the last good view stays, never marked written, tried again)
            return _core_tried(began)
        sections = {title: made[title] if title in made else had.get(title, "") for title in CORE_SECTIONS}
    else:
        sections = dict(had) if asks else None  # (no section touched: the view stays byte for byte)
        for title, ask in asks.items():
            if ask is None:  # (nothing left in it, nothing to put back: written empty, no model asked)
                sections[title] = ""
                continue
            body = _core_reply(_llm(ask, max_tokens=900), title)
            if not body:
                return _core_tried(began)  # (it stays due: written again after CORE_RETRY, or a new change)
            sections[title] = body
    from core import state
    try:
        with change_lock():
            if revision() != first:
                return  # The next refresh will see the change.
            if sections is not None:
                path.parent.mkdir(exist_ok=True)
                kept = next((line for line in old.split("\n")[:1] if line.startswith("<!--")), "")
                temp = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=f".{path.name}.",
                                                     suffix=".part", delete=False) as f:
                        temp = Path(f.name)
                        f.write(_core_text(sections, "" if whole else kept))
                    os.replace(temp, path)
                finally:
                    if temp is not None:
                        temp.unlink(missing_ok=True)
            if whole:
                with state.private_file(_core_stamp(), "w") as f:
                    f.write(str(began))
            with state.private_file(_core_changes_stamp(), "w") as f:
                f.write(str(began))
            _core_tried_stamp().unlink(missing_ok=True)
    except Unreadable:
        return  # A busy change list leaves the view due.


CORE_RETRY = 15 * 60  # s: a writing of the view that gave nothing usable is tried again after this (or at a new change)


def _core_tried_stamp() -> Path:
    from core import state
    return state.STATE_ROOT / "memory" / "core-tried"


def _core_tried(began: float) -> None:
    """A writing that gave nothing usable: never marked written (it stays due), and not asked again before CORE_RETRY,
    unless a change comes (it had been marked written, so nothing retried it; and with no view yet it
    was asked at every upkeep, every 20 s)."""
    from core import state
    with state.private_file(_core_tried_stamp(), "w") as f:
        f.write(str(began))


def _core_whole_prompt(root: Path, changes: list[dict], note: str) -> str:
    """What the standing view is written whole from: what they changed, in words, first; then their own Life files and
    the summaries of their recent conversations, each as it stands now."""
    sources = [root / "AGENTS.md", *sorted((root / "Self").glob("*.md")),
               *sorted((root / "Self" / "Identity").glob("*.md"))]
    text = "\n\n".join(f"### {p.relative_to(root)}\n{_now_text(p, root, changes)}" for p in sources if p.is_file())
    since = dt.datetime.now().timestamp() - RECENT_DAYS * 86400
    gone, made = skipped(changes), {}
    for p in _summaries():
        try:
            at = p.stat().st_mtime
        except OSError:
            continue
        if at > since and str(p.relative_to(root)) not in gone:
            made[p] = at
    recent = sorted(made, key=lambda p: -made[p])
    # (each by its date and short id, never its file's name: name_of)
    talks = "\n\n".join(f"### {name_of(str(p.relative_to(root)), root)}\n"
                        f"{_within(_users_part(_now_text(p, root, changes)), 4000, 'it')}" for p in recent)
    return ((note + "\n\n" if note else "") +
        "Below are the user's own private Life files, then summaries of their recent conversations "
        "(newest first). Write the compact standing briefing that Viventium, their warm personal AI "
        "voice companion, keeps in mind in every conversation. Under 600 words, plain sentences, in these five "
        "sections, each under its own title line written exactly so: "
        + ", ".join(f"## {title}" for title in CORE_SECTIONS) + ". Only facts stated in the files or by the user in "
        "those conversations; say 'unknown' rather than guess. Who you are comes from the files only: from the "
        "conversations, use only what the user said, never what Viventium said, offered or claimed about herself or her "
        "limits (one past reply is not a rule). Who they are and what they prefer come only from their own "
        "words: something mentioned in passing, misheard, or said by Viventium and repeated is not settled; "
        "keep it out, or say it as uncertain. What the user corrected is written only as corrected, and "
        "what they asked not to bring back is left out, whatever words the files use. This briefing goes "
        "into every conversation, so leave out "
        "anything sensitive: money, accounts and transactions, health, legal matters, IDs, addresses, "
        "passwords and any account or card numbers (she looks those up in Life only when they matter). "
        "No file paths.\n\n" + _within(text, 90_000, "their files")
        + ("\n\n## Recent conversations\n\n" + _within(talks, 40_000, "these summaries") if talks else ""))


def _section_of(lines: list[str], at: int | None) -> str:
    """The standing view's section a line sits under: the nearest title at or above line `at` (1 = the first)."""
    for n in range(min(at or 0, len(lines)), 0, -1):
        if title := core_title(lines[n - 1]):
            return title
    return ""


def _core_touched(old: str, changes: list[dict], rows: list[dict], applied: float) -> dict | None:
    """The standing view's sections his changes since `applied` touched: {title: [(how, change, passage)]}. how is
    "change" (a correction or a forget in force that names one of its lines) or "back" (an undo of one whose line a
    writing since took out: it goes back in; one whose line is still there is simply read again, nothing to write).
    A change that names none of its lines touches none (each reader applies it; the daily writing is told it). None
    when a line's section cannot be told (it is written whole then)."""
    rel, lines = f"Views/{CORE_NAME}", old.split("\n")
    named = {c["id"]: c for c in rows if c.get("kind") in ("correct", "forget")}
    active = {c["id"] for c in changes}
    touched: dict[str, list] = {}
    for c in rows:
        if float(c.get("at") or 0) <= applied:
            continue
        if c.get("kind") in ("correct", "forget") and c["id"] in active:
            how, target = "change", c
        elif c.get("kind") == "undo" and c.get("of") in named:
            how, target = "back", named[c["of"]]
        else:
            continue
        for p in target.get("passages", []):
            if p.get("path") != rel or core_title(str(p.get("text", ""))):
                continue  # (another file's line; or a title, which is the runtime's: nothing to write)
            where, at = placed(p)
            if how == "back" and (where == "exact" or _held(p, changes)):
                continue  # (still there, read again as it is; or named again by a change in force: nothing goes back)
            title = core_title(str(p.get("section", ""))) or (_section_of(lines, at) if where == "exact" else "")
            if not title:
                return None
            touched.setdefault(title, []).append((how, target, p))
    return touched


SECTION_ASK = "Below is one section of the short standing briefing"


def _held(passage: dict, changes: list[dict]) -> bool:
    """Whether a change in force names this very line (its file, its words) again."""
    said = " ".join(str(passage.get("text", "")).split())
    return any(p.get("path") == passage.get("path") and " ".join(str(p.get("text", "")).split()) == said
               for c in changes for p in c.get("passages", []))


def _core_section_prompt(title: str, old: str, had: dict[str, str], wants: list, changes: list[dict],
                         note: str) -> str | None:
    """What one touched section is written again from: what they changed, in words, first; then the section as it stands
    now (a forgotten sentence not there, a correction first), what goes back in, and the rule to keep every other line
    word for word. None: nothing is left in it and nothing goes back (it is written empty, without a model)."""
    rel, lines = f"Views/{CORE_NAME}", old.split("\n")
    start = next((n for n, line in enumerate(lines, 1) if core_title(line) == title), 0)
    first = next((n for n in range(start + 1, len(lines) + 1) if lines[n - 1].strip()), start + 1)
    now = current(had.get(title, ""), 0.0, changes, rel, first=first).strip("\n") if had.get(title) else ""
    back = []
    for how, change, p in wants:
        if how != "back":
            continue
        line = LEAD.sub("", str(p.get("text", "")), count=1).strip()
        if change["kind"] == "correct":
            back.append(f'they took back a correction ("{change.get("said", "")}"): this line holds again as it was: '
                        f'"{line}"')
        else:
            back.append(f'they put back what they had asked not to bring up: this line goes back in: "{line}"')
    if not now.strip() and not back:
        return None
    return ((note + "\n\n" if note else "") + SECTION_ASK + " that Viventium, the user's warm personal AI voice "
            f'companion, keeps in mind in every conversation: "{title}". The user has just changed what you remember '
            "(above). Write this section again with their change in it, and nothing else changed: a correction goes "
            "into its line as what is true now, in plain words (never in brackets); what they asked not to bring back "
            "is left out, whatever words it is in, with no word that anything was left out; "
            + ("; ".join(back) + "; " if back else "")
            + "every other line stays exactly as it is, word for word. Write only the lines of this section, with no "
            "title and no heading; if nothing of it is left, write: Unknown.\n\nThe section now:\n" + now)


def _core_reply(text: str, title: str) -> str:
    """A section's body as its model wrote it: without a title of its own at the top (with or without its marks), and
    nothing from another section's title on (it wrote more than it was asked)."""
    lines = [line for line in (text or "").strip().split("\n") if not line.strip().startswith("```")]
    if lines and (core_title(lines[0]) == title or re.match(r"^\s{0,3}#{1,6}\s", lines[0])):
        lines = lines[1:]
    cut = next((n for n, line in enumerate(lines) if core_title(line)), len(lines))
    return _core_body("\n".join(lines[:cut]))


# What each Life file is to her memory, by the folders Life/AGENTS.md lays out: where a passage comes from, in plain
# words (her standing view, a conversation's summary, his saved notes, an original as it was said or received, history,
# a sensitive file). Light's code edits none of them for a change. A label says whose a note is: "past decisions" over a
# line with a date was told back as "you told me on" that date, a conversation that
# never was.
ORIGINALS = ("Memory/Transcripts", "Memory/Ambient", "Communications", "Sources")
HISTORY = ("Archive", "Decisions_and_History")
SENSITIVE = ("Finance", "Health", "Legal", "Projects", "Workspaces")
NOT_MEMORY = ("Media", "99_System", "Views")
FOLDERS = {"Self": "your notes about yourself", "People": "your notes on people", "Plans": "your plans",
           "Places": "your notes on places", "Insights": "a connection noticed while dreaming",
           "CURRENT.md": "your notes on what matters now",
           "Calendar": "your calendar notes", "Events": "your notes on events", "Home": "your home notes",
           "Learning": "your learning notes", "Social": "your social notes", "Finance": "your money notes",
           "Health": "your health notes", "Legal": "your legal notes", "Projects": "your projects",
           "Workspaces": "your work", "Decisions_and_History": "your notes on past decisions",
           "Archive": "an archived note"}
TEXT = (".md", ".txt")


def kind_of(rel: str) -> str:
    """core (what she keeps in mind every conversation), summary (of a conversation), saved, original, history,
    sensitive, or other (not memory: the Life rules, a README, a template, media, bookkeeping)."""
    def under(folders) -> bool:
        return any(rel == f or rel.startswith(f + "/") for f in folders)
    name = rel.rsplit("/", 1)[-1]
    if rel == f"Views/{CORE_NAME}":
        return "core"
    if rel in ("AGENTS.md", "README.md") or name == "README.md" or "/_template/" in rel or not rel[:1].isupper() \
            or not rel.endswith(TEXT):
        return "other"
    if rel.startswith("Memory/Conversations/"):
        return "summary"
    for kind, folders in (("original", ORIGINALS), ("history", HISTORY), ("sensitive", SENSITIVE), ("other", NOT_MEMORY)):
        if under(folders):
            return kind
    return "saved"


def _summary_index_path(path: Path) -> Path:
    """Bookkeeping belongs to her state, isolated for each Life folder."""
    from core.state import STATE_ROOT
    root = life()
    name = hashlib.sha256(str(root.resolve() if root else path.parent.resolve()).encode()).hexdigest()
    return STATE_ROOT / "core" / "summary-index" / f"{name}.json"


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _inside(path: Path, root: Path) -> Path | None:
    """The folder of `path` (or the path itself) that is `root`, by file identity, never by its spelling: this Mac's
    disk ignores letter case, so ".../life/self/notes.md" is his Self/Notes.md (a path typed in another
    case walked past every guard). None when it is not inside it."""
    try:
        target = path.expanduser().absolute()
        targets = [target, target.resolve()]
    except (OSError, RuntimeError, ValueError):
        return None
    if not root or not root.exists():
        return None
    for each in targets:
        for folder in (each, *each.parents):
            if folder.exists() and _same_file(folder, root):
                return folder
    return None


def life_rel(path: Path) -> str | None:
    """A path's place in his Life as his Life spells it (its own letter case, found by file identity: _inside), None
    when it is not in his Life."""
    root = life()
    if not root:
        return None
    try:
        target = path.expanduser().absolute().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    base = _inside(target, root)
    if base is None:
        return None
    try:
        parts = target.relative_to(base).parts
    except ValueError:
        return None
    here, out = root, []
    for part in parts:
        try:
            names = os.listdir(here)
        except OSError:
            return None
        name = part if part in names else next(
            (n for n in names if n.casefold() == part.casefold() and _same_file(here / n, here / part)), None)
        if name is None:
            return None
        out.append(name)
        here = here / name
    return "/".join(out)


def private_memory_path(path: Path) -> bool:
    """Generic file readers must never turn state or a backup into model input, nor give a Life file a change in force
    applies to as its bytes: both are read through user_content (a Life file as she reads it in recall: read_now). By
    file identity, whatever the letter case it is typed in (_inside)."""
    from core import backup
    from core.state import STATE_ROOT
    try:
        named = {path.name.casefold(), path.resolve().name.casefold()}
    except (OSError, RuntimeError, ValueError):
        named = {path.name.casefold()}
    return (".summary-index.json" in named
            or any(_inside(path, root) is not None for root in (STATE_ROOT, backup.home(), backup.HOME))
            or read_now(path) is not None)


READ_ROOM = 12_000  # characters of one file a direct read gives (as read_file reads its bytes)


def read_now(path: Path) -> str | None:
    """A Life text file as she reads it in recall when a change in force applies to it: a forgotten line or sentence
    not there (with no mark), a corrected one corrected, her bookkeeping lines never shown. What a direct
    read (read_file, a file named in his words) gives instead of its bytes (both gave the raw file, the
    forgotten line in it). None when no change applies, or it is not a Life text file or a summary that cannot be read
    (then the reader's own rules hold: summary_read_issue). When the change list cannot be read, nothing of it is
    given."""
    root = life()
    try:
        rel = life_rel(path)  # (by file identity: whatever its letter case)
        if not root or rel is None or not (root / rel).is_file():
            return None
        if kind_of(rel) == "other":
            return None
        with one_pass():
            if kind_of(rel) == "summary" and summary_read_issue(root / rel):
                return None
            changes = in_force()
            text = _file_text(root / rel)
            now = current(text, 0.0, changes, rel, first=1) if changes else text
            if kind_of(rel) == "summary":
                now = "\n".join(line for line in now.split("\n") if not line.startswith(("- **row digests:**", "- **rows:**")))
    except Unreadable as e:
        return f"Nothing of this file can be shown right now: {e}."
    except (OSError, ValueError):
        return None
    return now if now != text else None


def user_content(path: Path, chat=None) -> str | None:
    """Controlled reads of referenced user content; never a general exception for state.

    Whole-message names are derived from the current record text. Attachments must
    match a current record or a pending native message and their stored checksum.
    """
    import stat
    from core import attachments, relationship
    if (now := read_now(path)) is not None:  # (a Life file a change applies to: as recall reads it)
        return now[:READ_ROOM] + ("\n(… the file goes on; a Worker can read all of it)" if len(now) > READ_ROOM else "")
    target = path.absolute()
    try:
        # The file itself, never a link to one; its real place inside the real folder it belongs to. A folder above it
        # may be a link (on this Mac /var is /private/var): only where the file really is decides.
        if not stat.S_ISREG(target.lstat().st_mode):
            return None
        real = target.resolve()
        rows = current_rows(numbered())
        if real.parent == (relationship.STATE / "whole").resolve():
            for row in rows:
                text = row["text"]
                if real.name == hashlib.sha256(text.encode()).hexdigest()[:24] + ".txt":
                    return text if real.read_text() == text else None
        if not real.is_relative_to(attachments.INBOX.resolve()):
            return None
        refs = [ref for row in rows for ref in row.get("files", [])]
        for item in getattr(chat, "items", ()):
            if item.type == "message" and item.role == "user" and not item.extra.get("memory_row"):
                refs.extend(item.extra.get("files", []))
        for ref in refs:
            if (Path(ref.get("path", "")).resolve() == real and ref.get("sha256")
                    and not attachments.check(ref)):
                with real.open("rb") as f:
                    data = f.read(12_000)
                if b"\0" in data[:4096]:
                    return None
                return data.decode("utf-8", errors="replace") + (
                    "\n(… the file goes on; a Worker can read all of it)" if real.stat().st_size > len(data) else "")
    except (OSError, ValueError):
        return None
    return None


def summary_read_issue(path: Path) -> str:
    """Apply the summary read boundary to explicitly named files too: one that cannot be read, or a conversation he
    asked not to bring back whole (skipped: every other reader leaves it out already)."""
    root = life()
    rel = life_rel(path) if root else None  # (by file identity: whatever its letter case)
    if rel is not None:
        if kind_of(rel) == "summary":
            try:
                if rel in skipped():
                    return SKIPPED_WHOLE
            except Unreadable as e:
                return str(e)
            return source(rel, root).get("unreadable", "")
    return ""


def _summary_index(path: Path, text: str | None = None) -> dict:
    """Missing is an empty cache. Unreadable bytes or types are explicitly unreadable."""
    text = _file_text(path) if text is None else text
    return _read_summary_index(_summary_index_path(path), str(path.relative_to(life())),
                               hashlib.sha256(text.encode()).hexdigest())


def _parse_index(target: Path) -> dict:
    try:
        value = json.loads(target.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise Unreadable("the conversation summary index cannot be read") from e
    if not isinstance(value, dict):
        raise Unreadable("the conversation summary index is not an object")
    return value


def _read_summary_index(target: Path, key: str | None = None, version: str | None = None) -> dict:
    """The index (read once per pass), with `key`'s entry checked: a malformed entry belongs to its summary; it cannot
    discard another summary's valid (or stale) digest evidence."""
    value = _once(("index", str(target)), lambda: _parse_index(target))
    if key is None or key not in value:
        return value
    entry = value[key]
    if not isinstance(entry, dict) or not isinstance(entry.get("versions"), dict):
        raise Unreadable("a conversation summary index entry cannot be read")
    # Each version stands alone. A bad old one never erases the current digest.
    versions = {}
    for digest, identity in entry["versions"].items():
        try:
            refs = json.loads(identity["row digests"])
            valid = (isinstance(identity["source_ref"], str) and isinstance(refs, list)
                     and bool(refs) and all(_row_ref(ref) for ref in refs))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            if digest == version:
                raise Unreadable("a conversation summary index identity cannot be read")
            continue
        versions[digest] = identity
    return {**value, key: {**entry, "versions": versions}}


def _summary_rows(meta: dict, path: Path | None = None, whole: bool = False) -> list[dict]:
    """Recovery candidates: the exact span when present, bounded by publication (whole: the record's rows themselves,
    else their references).

    Old files have no precise publication field. Their mtime is an upper bound;
    never extend it to the end of the displayed minute.
    """
    from core.memory import _span
    try:
        span = _span(meta)
    except (TypeError, ValueError, OverflowError) as e:
        raise Unreadable("the summary's conversation and time span cannot be read") from e
    if not span:
        raise Unreadable("the summary's conversation and time span cannot be read")
    try:
        published = float(meta["published"]) if "published" in meta else path.stat().st_mtime if path else float("inf")
        if path and not math.isfinite(published):
            raise ValueError("nonfinite publication time")
    except (OSError, TypeError, ValueError) as e:
        raise Unreadable("the summary's publication time cannot be read") from e
    exact = bool(meta.get("span"))
    try:
        rows = _rows_between(span["call"], span["from"], span["to"], end_too=exact, published=published)
    except (TypeError, ValueError, OverflowError) as e:
        raise Unreadable("the summary's record times cannot be read") from e
    return rows if whole else [{"row": row["row"], "digest": row["digest"]} for row in rows]


def _summary_identity(path: Path, text: str, meta: dict, index: dict) -> dict | None:
    entry = index.get(str(path.relative_to(life())), index.get(path.name, {}))
    versions = entry.get("versions", {}) if isinstance(entry, dict) else {}
    identity = versions.get(hashlib.sha256(text.encode()).hexdigest()) if isinstance(versions, dict) else None
    if not isinstance(identity, dict) or identity.get("source_ref") != meta.get("source_ref"):
        return None
    try:
        refs = json.loads(identity.get("row digests", ""))
        if not isinstance(refs, list) or not refs or not all(_row_ref(ref) for ref in refs):
            return None
    except (TypeError, ValueError):
        return None
    record = record_rows()  # (one look at the record for all of its rows)
    if refs and any(not (ref["row"] <= len(record) and record[ref["row"] - 1]
                         and record[ref["row"] - 1]["digest"] == ref["digest"]) for ref in refs):
        raise Unreadable("the summary's message reference is stale; its record changed")
    expected = _summary_rows(meta, path)
    # A valid old identity can name less than its displayed minute. Times bound
    # recovery; they never replace a digest that has stopped matching.
    valid = refs == expected if meta.get("span") else all(ref in expected for ref in refs)
    return identity if refs and valid else None


def _her_versions(entry) -> list[dict]:
    """The identities of a summary she wrote herself, oldest first (never one a reader recovered from times)."""
    versions = entry.get("versions") if isinstance(entry, dict) else None
    return [v for v in versions.values() if isinstance(v, dict) and not v.get("recovered")] \
        if isinstance(versions, dict) else []


def _edited(path: Path, text: str, index: dict) -> dict | None:
    """One of her summaries that he (or a Worker) edited since she wrote it: she wrote this file, and its bytes are none
    she wrote. Her last identity of it, marked edited (his edit wins): it is never written over or written
    again, its stretch counts as covered, and a change works on its lines as on his own notes. None otherwise (a lost
    index cannot tell an edit from hers: the recovery of a lost index holds)."""
    try:
        entry = index.get(str(path.relative_to(life())), {})
    except ValueError:
        return None
    hers = _her_versions(entry)
    if not hers:
        return None
    now = entry["versions"].get(hashlib.sha256(text.encode()).hexdigest())
    if isinstance(now, dict) and not now.get("recovered"):
        return None  # (as she wrote it)
    return {**hers[-1], "edited": True}


def _his(path: Path) -> bool:
    """Whether a summary file is one of hers he edited (_edited): never written over."""
    try:
        return bool(_summary_meta_now(path).get("edited"))
    except (Unreadable, OSError):
        return False


HERS_WAITING = ("a message it was written from was forgotten or corrected since; it is due to be written again "
                "without it")
HERS_EMPTY = "everything the user said in it was forgotten since, so nothing of it is read"


def _changed_since(identity: dict, head: dict) -> bool:
    """A change in force that names one of the messages this summary of hers was written from (by its row), made since
    she wrote it and not among the changes it was written with: it is not read, and it is written again in its place
    (a message forgotten "only some" stayed in her summary, and she had said she would not bring it up).
    A conversation forgotten whole skips its summaries instead (skipped); one he edited goes by his notes' way
    (_edited)."""
    try:
        rows = {ref["row"] for ref in json.loads(identity["row digests"]) if isinstance(ref, dict)}
        published = float(head.get("published") or 0)
    except (KeyError, TypeError, ValueError):
        return False
    used = set(identity.get("changes") or [])
    return any(c["id"] not in used and float(c.get("at") or 0) > published
               and any(isinstance(ref, dict) and ref.get("row") in rows for ref in c.get("messages", []))
               for c in in_force())


def _undone(identity: dict) -> bool:
    """Whether a change her summary was written with no longer holds (undone since): what it left out or corrected is
    back, so it is written again (a forget undone after its rebuild never came back)."""
    used = identity.get("changes")
    if not isinstance(used, list) or not used:
        return False
    active = {c["id"] for c in in_force()}
    return any(change_id not in active for change_id in used)


def _her_rows(call_id: str) -> tuple[set[int], set[int]]:
    """The rows of this conversation her summaries stood for, by her own index (no walk of his Life): (those whose file
    is there, those whose file is gone from his Life: he deleted or moved it, never written again). Her
    own deletion takes its entry out of her index first (_uncache_summary). Once per pass."""
    root = life()
    if not root:
        return set(), set()

    def made() -> dict:
        try:
            index = _read_summary_index(_summary_index_path(root / "Memory"))
        except Unreadable:
            return {}
        by: dict = {}
        for rel, entry in index.items():
            hers = _her_versions(entry)
            if not hers or not isinstance(rel, str) or "/" not in rel:
                continue
            try:
                refs = json.loads(hers[-1]["row digests"])
                ref = str(hers[-1]["source_ref"])
            except (KeyError, TypeError, ValueError):
                continue
            call = summary_call(ref)
            there, gone = by.setdefault(call, (set(), set()))
            (there if (root / rel).exists() else gone).update(r["row"] for r in refs if isinstance(r, dict) and r.get("row"))
        return by
    there, gone = _once(("her rows", str(root)), made).get(call_id, (set(), set()))
    return set(there), set(gone)


def _gone_hers(call_id: str) -> set[int]:
    """The rows of this conversation whose summary of hers is gone from his Life (_her_rows): never written again."""
    return _her_rows(call_id)[1]


def _uncache_summary(path: Path) -> None:
    """Her own summary taken out of his Life (everything said in it was forgotten): its entry leaves her index, so it is
    never mistaken for one he deleted (_gone_hers) and the stretch comes back after an undo."""
    target = _summary_index_path(path)
    if not target.exists():
        return
    from core.state import closed_file
    with closed_file(target.with_suffix(".lock"), "a") as lock:
        _flock(lock, LOCK_WAIT, "the summary index is busy")
        try:
            index = _parse_index(target)
        except Unreadable:
            return
        if index.pop(str(path.relative_to(life())), None) is None:
            return
        staged = target.with_suffix(f".{os.getpid()}.{time.monotonic_ns()}.part")
        try:
            with closed_file(staged, "w") as f:  # (0600 from its first byte)
                json.dump(index, f)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
            _forget_once(("index", str(target)))


def _cache_summary(path: Path, text: str, identity: dict) -> None:
    target = _summary_index_path(path)
    from core.state import closed_file
    # Readers may recover different entries at the same time as publication.
    with closed_file(target.with_suffix(".lock"), "a") as lock:
        deadline = time.monotonic() + 0.15
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as e:
                if time.monotonic() >= deadline:
                    raise Unreadable("the summary's index lock is busy; try again") from e
                time.sleep(0.01)
        try:
            index = _parse_index(target)  # (as it is now, never a pass's earlier read: other entries are kept)
        except Unreadable:
            index = {}  # the record rebuilds a damaged cache
        rel = str(path.relative_to(life()))
        entry = index.get(rel, {})
        versions = entry.get("versions", {}) if isinstance(entry, dict) else {}
        versions = dict(versions) if isinstance(versions, dict) else {}
        versions[hashlib.sha256(text.encode()).hexdigest()] = identity
        index[rel] = {"versions": versions}
        staged = target.with_suffix(f".{os.getpid()}.{time.monotonic_ns()}.part")
        try:
            with closed_file(staged, "w") as f:  # (0600 from its first byte)
                json.dump(index, f)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
            _forget_once(("index", str(target)))


def _summary_meta(path: Path) -> dict:
    """Public header plus private identity, checked and recovered from the record (once per summary in a pass)."""
    return _once(("meta", str(path)), lambda: _summary_meta_now(path))


def _summary_meta_now(path: Path, waiting_too: bool = False) -> dict:
    """waiting_too: a summary of hers due to be written again after a change to its messages (_changed_since) is given
    too, never refused: what her writers look for to write it again in its place (_already, _publish); every reader
    refuses it."""
    try:
        text = _file_text(path)
    except OSError as e:
        raise Unreadable("the summary file cannot be read") from e
    meta = _summary_meta_text(text)
    if meta.get("record") != "private index":
        if "row digests" not in meta and _legacy_changes(path, meta):
            raise Unreadable(_retired_why(meta))
        return meta
    try:
        index = _summary_index(path, text)
    except Unreadable:
        index = {}
    identity = _summary_identity(path, text, meta, index)
    if identity is None:
        try:
            legacy = _read_summary_index(path.parent / ".summary-index.json", path.name,
                                         hashlib.sha256(text.encode()).hexdigest())
        except Unreadable:
            legacy = {}
        identity = _summary_identity(path, text, meta, legacy)
    if (identity is None or identity.get("recovered")) and (edited := _edited(path, text, index)):
        return {**meta, **edited}
    if identity is None:
        refs = _summary_rows(meta, path)
        if not refs:
            raise Unreadable("the summary's conversation has no matching record rows")
        identity = {"source_ref": meta["source_ref"], "row digests": json.dumps(refs, separators=(",", ":")),
                    "recovered": True}
        try:
            _cache_summary(path, text, identity)
        except OSError as e:
            raise Unreadable(f"the summary's identity cannot be recovered ({e.strerror or str(e)})") from e
    if not waiting_too and _changed_since(identity, meta):  # (not read until written again without it)
        raise Unreadable(HERS_WAITING if _left_of(identity) else HERS_EMPTY)
    return {**meta, **identity}


def _left_of(identity: dict) -> bool:
    """Whether anything the user said in a summary's messages is still to keep (else it is never written again: before,
    it had said "due to be written again" for good)."""
    try:
        record = record_rows()
        rows = [{**record[r["row"] - 1], "row": r["row"]} for r in json.loads(identity["row digests"])
                if isinstance(r, dict) and 0 < r.get("row", 0) <= len(record) and record[r["row"] - 1]]
        return any(row.get("role") == "user" for row in summary_input(rows))
    except (KeyError, TypeError, ValueError, Unreadable):
        return True


RETIRED_WAITING = "this older summary was retired after a correction or forget; its conversation is due to rebuild"
RETIRED_REBUILT = ("this older summary was retired after a correction or forget, and its conversation was summarized "
                   "again without it")
RETIRED_LOST = "this older summary was retired after a forget; its messages are not in the record, so it cannot be rebuilt"
RETIRED_EMPTY = ("this older summary was retired after a forget; nothing the user said in it is left, so there is nothing "
                 "to rebuild")
SKIPPED_WHOLE = "the user asked not to bring this conversation back"
# Why a summary cannot be read, as she is told it (her own search, read_file): a reason that is a change of his (a
# forget or a correction it waits on, a conversation forgotten whole) is never said to her, and one with nothing of his
# left is not shown to her at all (nothing of a forget reaches her, not even that there was one).
# The memory page, which is his, says each reason as it is.
CHANGED_REASONS = (HERS_WAITING, RETIRED_WAITING, RETIRED_LOST, SKIPPED_WHOLE)
NOTHING_LEFT = (HERS_EMPTY, RETIRED_EMPTY, RETIRED_REBUILT)


def unreadable_for_her(issue: str) -> str:
    """The sentence she is given for a summary that cannot be read: its reason, unless that is a change of his."""
    hidden = issue in CHANGED_REASONS or issue in NOTHING_LEFT
    return "This summary cannot be read." if hidden else f"This summary cannot be read: {issue}."


def _retired_why(meta: dict) -> str:
    """What a retired older summary is now, said plainly: waiting for its rebuild, written again
    (then readers leave it out: source's "superseded"), its messages not in the record (it cannot be rebuilt), or
    nothing he said in it left."""
    from core.memory import _span
    try:
        span = _span(meta)
        rows = _stated(span["call"], meta, span) if span else []
    except (TypeError, ValueError, OverflowError):
        rows = []
    if not rows:
        return RETIRED_LOST
    call, mine = span["call"], {row["row"] for row in rows}
    there, gone = _her_rows(call)  # (her own index: never a walk of his Life per summary read)
    covered = there | gone
    try:
        changes = in_force()
        carried = any(c.get("carry") for c in changes)
        for row in rows:  # (the first message of his still to keep is enough: it is waiting)
            if row["row"] in covered or row.get("role") != "user":
                continue
            if row_now(row["row"], str(row.get("text") or ""), changes).strip() and (not carried or summary_input([row])):
                return RETIRED_WAITING
    except Unreadable:
        return RETIRED_WAITING
    return RETIRED_REBUILT if mine & covered else RETIRED_EMPTY


def _legacy_changes(path: Path, meta: dict) -> list[str]:
    """The recorded changes that retire an older summary (main's: no row identity) whole: its prose is never read
    again, and its own stretch is due (_due). Only a change that names messages of the record retires it, when one of
    them is a message of its own conversation (the same call id) inside its stated minutes, end minute included (the
    message's conversation and time from the change's saved source first, else from the record while that row still
    holds it; one that cannot be known retires it): their words may be anywhere in its prose. A message of another
    conversation said in the same minutes never retires it (a Telegram message forgotten inside an older
    voice call's minutes had retired that call's summary); within his one Telegram id, time decides. A change that names one of its lines (a passage) never retires it: that line alone is
    left out, or shown as corrected, everywhere it is read, and every other line stays (one
    forgotten line had hidden the trip's date and the pottery class with it, and she said a request was never made).
    A change that names its file whole skips it whole (skipped). Never by a call id alone (his Telegram stretches share
    one), never by the conversation the change was said in (its `call`). Undone changes count too: a copy or a restore of the file
    never makes retired prose valid again. None of this ever selects a message for a forget."""
    from core.memory import _span
    try:
        span = _span(meta)
    except (TypeError, ValueError, OverflowError):
        span = None
    if not span:
        return []
    exact, call = bool(meta.get("span")), span["call"]
    return [change["id"] for change in _touches()
            if change["unknown"] & {"", call} or any(_any_between(change["times"].get(c, []), span["from"], span["to"], exact)
                                                     for c in (call, ""))]


def _any_between(times: list[float], start: float, end: float, end_too: bool = False) -> bool:
    """Whether a time of these (in order) falls from `start` to `end` (`end` itself only with end_too)."""
    at = bisect.bisect_left(times, start)
    return at < len(times) and (times[at] < end or (end_too and times[at] == end))


def _touches() -> list[dict]:
    """The messages each recorded correction and forget names, for _legacy_changes, by conversation: {call id: their
    times, in order} (the saved source's call and time first, else the record's while that row still holds it), and the
    conversations where one of them cannot be known ("" when its conversation cannot be known either: it touches every
    one; a time whose conversation is not known is kept under "": its time alone decides). Made once per version of the
    change list and of the record in a pass."""
    changes, record = ledger(), record_rows()

    def made() -> list[dict]:
        out = []
        for change in changes:
            if change["kind"] not in ("forget", "correct"):
                continue
            saved = {(s["row"], s["digest"]): s for s in change.get("sources", [])}
            times: dict[str, list[float]] = {}
            unknown: set[str] = set()
            for ref in change.get("messages", []) + change.get("rows", []):
                kept = saved.get((ref["row"], ref["digest"])) or {}
                held = (record[ref["row"] - 1] if 0 < ref["row"] <= len(record) and record[ref["row"] - 1]
                        and record[ref["row"] - 1]["digest"] == ref["digest"] else None) or {}
                call = str(kept.get("call") or held.get("call_id") or "")
                try:
                    t = float(kept["t"] if kept.get("t") is not None else held.get("t"))
                except (TypeError, ValueError, OverflowError):
                    t = math.nan
                if not math.isfinite(t):
                    unknown.add(call)  # (unknown coordinates cannot certify old prose; "": any conversation's)
                    continue
                times.setdefault(call, []).append(t)  # ("": a conversation not known, its time alone decides)
            out.append({"id": change["id"], "times": {call: sorted(ts) for call, ts in times.items()},
                        "unknown": unknown})
        return out
    return _once(("touches", id(changes), id(record)), made)


def _summaries() -> list[Path]:
    """Every conversation summary in Life: one walk of Memory/Conversations per pass."""
    root = life()
    folder = root / "Memory" / "Conversations" if root else None

    def walk() -> list[Path]:
        if not folder or not folder.is_dir():
            return []
        return sorted(p for p in folder.rglob("*.md") if kind_of(str(p.relative_to(root))) == "summary")
    return _once(("summaries", str(folder)), walk)


def _file_text(path: Path) -> str:
    """A Life file's text (a summary, a note): one read with its lines (_file_lines), again only once the file changed.
    OSError when it cannot be read."""
    root = life()
    try:
        rel = str(path.relative_to(root)) if root else ""
    except ValueError:
        rel = ""
    if rel and (lines := _file_lines(rel)) is not None:
        return "\n".join(lines)
    return path.read_text(errors="replace")


def _older(head: dict) -> bool:
    """A summary main wrote, or one as old: no row identity of its own (no private index, no row digests)."""
    return head.get("record") != "private index" and "row digests" not in head


def _call_summaries(call_id: str) -> list[tuple[Path, dict, dict]]:
    """This conversation's summaries (by the conversation their header names), each with its header and span."""
    return _summaries_by_call().get(call_id, [])


def _summaries_by_call() -> dict[str, list[tuple[Path, dict, dict]]]:
    """Every summary by the conversation its header names: the folder walked and each summary read once per pass. One
    whose header cannot be read is not counted."""
    from core.memory import _span

    def made() -> dict:
        by: dict = {}
        for path in _summaries():
            try:
                head = _summary_meta_text(_file_text(path))
                span = _span(head)
            except (OSError, TypeError, ValueError, OverflowError):
                continue
            if span:
                by.setdefault(span["call"], []).append((path, head, span))
        return by
    return _once(("by call", str(life())), made)


def _retired_summaries(call_id: str) -> dict[str, list[str]]:
    """This conversation's older summaries that a recorded change touches (_legacy_changes), each with the changes that
    retired it: never read again, each one's own stretch due (_due). One pass: the folder, the change list and the
    record read once."""
    root = life()
    with one_pass():
        return {str(path.relative_to(root)): found for path, head, _ in _call_summaries(call_id)
                if _older(head) and (found := _legacy_changes(path, head))}


_META = re.compile(r"\s*-\s*\*\*([\w ]+):\*\*\s*(.+)")  # (a summary's head: "- **source:** …", in its first lines)
MIXED_CONVERSATION = "conversation, partly typed and partly spoken"
SUMMARY_KINDS = ("Telegram chat", "typed chat", "voice call", MIXED_CONVERSATION)


def summary_call(ref: str) -> str:
    """The conversation ID after a summary's kind in source_ref."""
    return next((ref[len(kind) + 1:] for kind in SUMMARY_KINDS if ref.startswith(kind + " ")), "")


def _summary_meta_text(text: str) -> dict:
    meta = {}
    for line in text.split("\n")[:14]:
        if m := _META.match(line):
            meta[m.group(1).strip().lower()] = m.group(2).strip()
    return meta


def _date(text: str) -> str:
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", text or "")
    try:
        return dt.date(*map(int, m.groups())).isoformat() if m else ""
    except ValueError:
        return ""


def source(rel: str, root: Path | None = None) -> dict:
    """Where a passage of memory comes from, in plain words, for her to say and the memory page to show:
    {kind, label, date (YYYY-MM-DD or "")}. A summary says which conversation and when (once per file in a pass)."""
    root = root or life()
    return dict(_once(("source", rel, str(root)), lambda: _source_now(rel, root)))


def _source_now(rel: str, root: Path | None) -> dict:
    kind, date = kind_of(rel), ""
    if kind == "core":
        return {"kind": kind, "label": "kept in mind in every conversation", "date": ""}
    if kind == "summary":
        unreadable = ""
        try:
            meta = _summary_meta(root / rel) if root else {}
        except Unreadable as e:
            unreadable = str(e)
            try:
                meta = _summary_meta_text(_file_text(root / rel)) if root else {}
            except OSError:
                meta = {}
        said = meta.get("source", "").lower()
        what = next((name for key, name in ((MIXED_CONVERSATION, MIXED_CONVERSATION), ("telegram", "Telegram chat"),
                                            ("typed", "typed chat"), ("call", "voice call"))
                     if key in said), "conversation")
        date = _date(meta.get("started", "")) or _date(rel.rsplit("/", 1)[-1])
        return {"kind": kind, "label": f"summary of a {what}", "date": date,
                **({"unreadable": unreadable} if unreadable else {}),
                **({"superseded": True} if unreadable in (RETIRED_REBUILT, HERS_EMPTY) else {})}
    top = rel.split("/", 1)[0]
    if kind == "original":
        date = _date(rel.rsplit("/", 1)[-1])
        return {"kind": kind, "label": "an original record, kept as it was", "date": date}
    return {"kind": kind, "label": FOLDERS.get(top, "saved in Life"), "date": ""}


def theirs(label: str) -> str:
    """A source's words as she is told them: the labels speak to the user on the memory page ("your notes about
    yourself"); in her notes and her tools "your" would be hers (before, "your notes about yourself:
    my favourite colour is green" read as her own note, and she answered with a line heard nearby instead)."""
    return label.replace("your notes about yourself", "their notes about themselves").replace("your ", "their ")


def cite(rel: str, root: Path | None = None, her: bool = False) -> str:
    """One short line naming a source: "summary of a Telegram chat" with its date. her: as she is told it (theirs)."""
    found = source(rel, root)
    when = dt.date.fromisoformat(found["date"]).strftime("%-d %b %Y") if found["date"] else ""
    said = found["label"] + (f", {when}" if when else "")
    return theirs(said) if her else said


# A conversation's summary is named by its date and a short id wherever she or the memory page names it, never by its
# file's name: that name came from its title, which can hold what he later asked to forget, and a summary written again
# in place, or main's with one line forgotten, keeps its file (her recall still said "…-a-pentecost-plan.md"
# after the forget). No file in Life is renamed for it.
SUMMARY_ID = 6  # hex characters of a summary's short id (with its date: two alike are refused, never guessed between)
_NAMED = re.compile(r"conversation-(?:(\d{4}-\d\d-\d\d)-)?([0-9a-f]{6,64})(?:\.md)?", re.IGNORECASE)


def _short_id(rel: str) -> str:
    return hashlib.sha256(rel.encode()).hexdigest()


def name_of(rel: str, root: Path | None = None) -> str:
    """How a Life file is named to her and on the memory page: a summary of a conversation by its date and a short id
    ("conversation-2026-11-17-3f9a2b"), any other file by its place in Life (his own notes, as he named them)."""
    if not rel or kind_of(rel) != "summary":
        return rel
    date = source(rel, root)["date"]
    short = _short_id(rel)[:SUMMARY_ID]
    return f"conversation-{date}-{short}" if date else f"conversation-{short}"


def summary_label(path: Path, otherwise: str | None = None) -> str:
    """A path as her tools say it (read_file): a summary of his Life by its name (name_of), anything else as it is
    (`otherwise`, else the path itself)."""
    try:
        rel = life_rel(path) if life() else None
    except (OSError, ValueError):
        rel = None
    if rel and kind_of(rel) == "summary":
        return name_of(rel)
    return str(path) if otherwise is None else otherwise


def file_named(name: str) -> str | None:
    """The summary a name from name_of says, as its place in Life: the name alone or at the end of a path, with or
    without ".md". None when it is no summary's name, or names more than one (never a guess between them)."""
    m = _NAMED.fullmatch((name or "").strip().strip("[]()'\"").strip().rsplit("/", 1)[-1])
    root = life()
    if not m or not root:
        return None
    date, short = m.group(1), m.group(2).lower()
    found = [rel for p in _summaries() if _short_id(rel := str(p.relative_to(root))).startswith(short)]
    if len(found) > 1 and date:
        found = [rel for rel in found if source(rel, root)["date"] == date]
    return found[0] if len(found) == 1 else None


def bookkeeping(rel: str, number: int, line: str) -> bool:
    """A summary's own bookkeeping line (its head's "- **source:** …" lines, as _summary_meta_text reads them): never
    something it keeps about him, so never a place to offer or to name."""
    return kind_of(rel) == "summary" and 0 < number <= 14 and _META.match(line or "") is not None


def _keywords(text: str) -> list[str]:
    """Up to eight distinctive words to look for, a possessive dropped ("the bakery's" is looked for as "bakery": with
    its 's it matched no line and no message that says "the bakery", and her look missed what he had said)."""
    words = (re.sub(r"['\u2019]s$", "", w) for w in re.findall(r"[\w'\u2019-]{3,}", text.lower()))
    return [w for w in dict.fromkeys(words) if len(w) >= 3 and w not in COMMON][:8]


SEARCH_WAIT = float(os.environ.get("MEMORY_SEARCH_WAIT", "5"))  # s: one word search of his Life, at most


def _search_problem(why: str, issues: set[str] | None) -> None:
    if issues is None:
        raise Unreadable(why)
    issues.add(why)


def search_notice(issues: set[str], found: bool) -> str:
    if not issues:
        return ""
    status = "incomplete" if found else "unavailable"
    return f"The word search is {status} ({', '.join(sorted(issues))})."


def rg(args: list[str], *, issues: set[str] | None = None) -> str:
    """Run one bounded word search. Callers that can report partial results can collect issues and use stdout."""
    try:
        result = subprocess.run(["rg", *args], capture_output=True, text=True, timeout=SEARCH_WAIT)
    except subprocess.TimeoutExpired as e:
        _search_problem(f"the search of their Life took longer than {SEARCH_WAIT:.0f} seconds", issues)
        # A timed-out process can leave an unfinished line. Keep only its complete matches.
        return (e.stdout or b"").rpartition(b"\n")[0].decode(errors="replace")
    except (OSError, UnicodeError):
        _search_problem("the search could not run or its output could not be read", issues)
        return ""
    if result.returncode not in (0, 1):
        # stderr can name private files. Report the status without its contents.
        _search_problem(f"the search failed with status {result.returncode}", issues)
    return result.stdout


def _lines(path: str, words, most: int, *, issues: set[str] | None = None) -> list[tuple[int, str]]:
    found = rg(["-i", "-n", "--max-count", str(most), "-e", "|".join(map(re.escape, words)), path],
               issues=issues).strip().splitlines()
    out = []
    for line in found:
        number, _, text = line.partition(":")
        if number.isdigit():
            out.append((int(number), text))
    return out


def _current_lines(root: Path, path: Path, lines: list[tuple[int, str]], changes: list[dict],
                   marked: bool = False, room: int = 0) -> list[tuple[int, str]]:
    """Matched lines as they stand now (the change list, by the passages it names), each with the section it sits
    under: in Light's summaries the section says whose words they are (what the user stated, what Viventium suggested,
    words only heard nearby, an open question), and a line shown alone had lost it (before, "My
    favourite colour is orange", heard at a dinner, came back as his). What a forget took out is simply not there, with
    no mark (until then her own search said "left out here: the user asked not to bring this
    back", and she told him the plans were something he had asked her not to bring up). marked (her own search): a
    summary that cannot be read says so (unreadable_for_her: never that a change of his is why); her per-turn note,
    which she did not ask for, leaves it out."""
    rel = str(path.relative_to(root))
    held = source(rel, root)
    if issue := held.get("unreadable"):  # (one written again since: nothing of it, its new summary holds it; and her
        # per-turn note, which she did not ask for, never carries one)
        if held.get("superseded") or not marked or issue in NOTHING_LEFT:
            return []
        return [(0, unreadable_for_her(issue))]
    kept = []
    for n, text in lines:
        if text.startswith(("- **row digests:**", "- **rows:**")):
            continue
        now = current(text, 0.0, changes, rel, first=n)
        if now.strip():
            kept.append((n, now))
    if not kept:
        return kept
    every = _file_lines(rel) or []
    out = []
    for n, text in kept:
        head = section_at(every, n, rel, changes)
        if shown := labelled(text, head, room):
            out.append((n, shown))
    return out


def marked(text: str, rel: str, changes: list[dict], gone: str = "", part: str = "") -> str:
    """A Life file's text as it stands now (current, line by line), a line a forget took out said where it was
    (`gone`, after its list mark) and a line it took part of said after what is left of it (`part`): what the memory
    page shows of a summary, so a fact he asked not to bring up is never mistaken for one that was never said. Raises
    Unreadable."""
    forgets, out = [c for c in changes if c["kind"] == "forget"], []
    for n, line in enumerate(text.split("\n"), 1):
        now = current(line, 0.0, changes, rel, first=n)
        if forgets and current(line, 0.0, forgets, rel, first=n).strip() != line.strip():
            lead = LEAD.match(line).group(0)
            now = lead + (gone or LEFT_OUT) if not now.strip() else f"{now} {part or PART_LEFT_OUT}"
        if now.strip() or not line.strip():
            out.append(now)
    return "\n".join(out)


def part_left(line: str) -> str:
    """A line a forget took part of, saying so first (after its correction, if any)."""
    m = ANNOTATION.match(line)
    at = m.end() if m else len(LEAD.match(line).group(0))
    return f"{line[:at]}{PART_LEFT_OUT} {line[at:]}"


def section_at(every: list[str], n: int, path: str = "", changes: list[dict] | None = None) -> str:
    """The section a line sits under (its nearest "##" heading above it), "" when none."""
    for number in range(min(n - 1, len(every)), 0, -1):
        line = every[number - 1]
        if line.startswith("##"):
            return current(line, changes=changes, path=path, first=number).lstrip("#").strip()
    return ""


def labelled(text: str, head: str, room: int = 0) -> str:
    """Keep a section label with its passage, counting the label within the passage's room."""
    if not head or text.lstrip().startswith("#") or text == LEFT_OUT:
        return cut(text, room) if room else text
    tail = f" (under: {head})"
    if not room or len(text) + len(tail) <= room:
        return text + tail
    body_room = max(room // 2, room - len(tail))
    body = cut(text, body_room)
    label_room = room - len(body) - len(" (under: )")
    if label_room <= 0:
        return body
    result = body + " (under: " + cut(head, label_room) + ")"
    # A corrected label is indivisible. If it cannot fit, omit this passage rather
    # than show it under an old or incomplete correction. Body corrections stay whole.
    return result if len(result) <= room or FIX in text else ""


HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)")


def heading_context(every: list[str], n: int, most: int = 4) -> list[tuple[int, str]]:
    """The first nonblank lines below a Markdown heading, up to its next peer or parent heading.
    Return original line numbers so corrections and forgets apply to each line as usual."""
    if not 0 < n <= len(every) or not (head := HEADING.match(every[n - 1])):
        return []
    out = []
    for number in range(n + 1, len(every) + 1):
        text = every[number - 1]
        if (next_head := HEADING.match(text)) and len(next_head[1]) <= len(head[1]):
            break
        if text.strip():
            out.append((number, text))
            if len(out) == most:
                break
    return out


def folders_named(only) -> tuple[str, ...]:
    """The Life folders a limit names ("Plans", "People/"): those that exist, as Life names them (any case)."""
    root = life()
    if not root or not only:
        return ()
    have = {d.name.lower(): d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")}
    return tuple(have[n.strip().strip("/").lower()] for n in only if n.strip().strip("/").lower() in have)


def search_hits(keywords: str, files: int = 5, most: int = 4, only: tuple[str, ...] = (),
                *, issues: set[str] | None = None) -> tuple[list[dict], int]:
    """The recall search over all of Life's text (not media, archives, internals or generated views), or only the
    folders `only` names when his words limit where to look: the files that match the most keywords, each with its
    matching lines as they stand now, and how many files matched in all. One ripgrep pass, about half a second on a
    large Life. A conversation forgotten whole is not searched."""
    root = life()
    words = _keywords(keywords)
    if not root or not words:
        return [], 0
    try:
        if only:
            dirs = [str(root / name) for name in folders_named(only)]
        else:
            dirs = [str(d) for d in sorted(root.iterdir()) if d.is_dir() and d.name not in SEARCH_SKIP and not d.name.startswith(".")]
            dirs += [str(p) for p in sorted(root.glob("*.md")) if p.name == "CURRENT.md"]
    except OSError:
        _search_problem("Life could not be listed", issues)
        return [], 0
    if not dirs:
        return [], 0
    found = rg(["-i", "-o", "-F", "--with-filename", "--no-line-number", "--max-filesize", "2M",
                *[part for word in words for part in ("-e", word)], *dirs], issues=issues)
    hits: dict[str, set[str]] = {}
    for line in found.splitlines():
        path, _, match = line.rpartition(":")
        if path:
            hits.setdefault(path, set()).add(match.lower())
    with one_pass():  # (the change list, the record and each summary read once for all of it)
        changes = in_force()
        gone = skipped(changes)
        hits = {p: w for p, w in hits.items() if str(Path(p).relative_to(root)) not in gone}
        ranked, out, replaced = [], [], 0
        for path, words_found in hits.items():
            try:
                ranked.append((-len(words_found), -Path(path).stat().st_mtime, path))
            except OSError:
                _search_problem("a matching file could not be read", issues)
        for _, _, path in sorted(ranked, key=lambda entry: entry[:2]):
            matched = _lines(path, words, most, issues=issues)
            expanded = dict(matched)
            every = _file_lines(str(Path(path).relative_to(root)))
            if every is None:
                _search_problem("a matching file could not be read", issues)
                continue
            for n, _ in matched:
                for number, text in heading_context(every, n):
                    expanded.setdefault(number, text)
            lines = _current_lines(root, Path(path), sorted(expanded.items()), changes, marked=True, room=LINE_ROOM)
            if lines:
                rel = str(Path(path).relative_to(root))
                # (a summary is named by its date and short id, never its file's name: that name came from its title,
                # which can hold what he forgot; one she cannot read, by what it is and when alone)
                hidden = bool(source(rel, root).get("unreadable"))
                out.append({"path": rel, "name": "" if hidden else name_of(rel, root),
                            "source": cite(rel, root, her=True), "lines": lines})
            else:  # (an older summary written again: its new one holds what is left of it; or a file whose every
                replaced += 1  # line found is one he asked to forget: never counted, so a count never hints at it)
            if len(out) == files:
                break
    return out, len(ranked) - replaced


LINE_ROOM = 240  # characters of one matched line in her search (its correction, its mark and its section kept whole)


def search(keywords: str, limit_chars: int = 1800, only: tuple[str, ...] = ()) -> str:
    """The recall search as text: each file with where it comes from, then its lines (line number: text)."""
    if limit_chars <= 0:
        return ""
    if not life() or not _keywords(keywords):
        return cut("No Life folder or keywords.", limit_chars)
    try:
        issues: set[str] = set()
        hits, matched = search_hits(keywords, only=only, issues=issues)
    except Unreadable as e:
        return UNREADABLE_NOTE.format(why=e)[:max(0, limit_chars)]
    notice = search_notice(issues, bool(hits))
    if notice and (not hits or limit_chars <= len(notice) + 2):
        return cut(notice, limit_chars)
    prefix = notice + "\n\n" if notice else ""
    return prefix + render(hits, matched, limit_chars - len(prefix))


def render(hits: list[dict], matched: int, limit_chars: int = 1800) -> str:
    """Her search as text, within `limit_chars`: whole files first; past the room, a file's lines that still fit, and
    corrections only when the whole corrected line fits. An omitted correction never exposes its old words."""
    out, size = [], 0
    for hit in hits:
        head = f"[{hit['name']}] {hit['source']}\n" if hit.get("name") else f"({hit['source']})\n"
        entries = [f"{n}: {text}" for n, text in hit["lines"]]
        block = head + "\n".join(entries)
        gap = 2 if out else 0
        if size + gap + len(block) <= limit_chars:
            out.append(block)
            size += gap + len(block)
            continue
        kept, used = [], size + gap + len(head)
        for entry in entries:
            newline = 1 if kept else 0
            if used + newline + len(entry) <= limit_chars:
                kept.append(entry)
                used += newline + len(entry)
            elif FIX not in entry and not (out or kept) and limit_chars > used:
                kept.append(cut(entry, limit_chars - used))
                used += len(kept[-1])
        if kept:
            out.append(head + "\n".join(kept))
            size = used
    if not out:  # (what she remembers, never a claim on his notes: a line he asked to forget is in them, unsaid)
        return cut("Matching memory needs more room." if hits else "Nothing you remember of them holds those words.",
                   limit_chars)
    more = f"\n\n({len(out)} of {matched} files that hold those words are shown.)" if matched > len(out) else ""
    text = "\n\n".join(out)
    return text + more if len(text) + len(more) <= limit_chars else text


COMMON = {"what", "where", "when", "which", "that", "this", "have", "your", "with", "about", "does",
          "there", "they", "them", "would", "could", "should", "remind", "tell", "know", "just", "like",
          "please", "really", "think", "want", "need", "from", "into", "also", "were", "will", "been",
          "the", "and", "for", "you", "are", "was", "but", "not", "can", "did", "how", "who", "why", "our"}


def related_hits(text: str) -> list[tuple[str, str]]:
    """Per-turn memory: the best Life matches for the user's words, only strong hits (at least two distinct words
    in one file), as (file, its matching lines as they stand now). Cheap (~50 ms); the model decides what it means."""
    root = life()
    words = [w for w in dict.fromkeys(re.findall(r"[a-z']{4,}", text.lower())) if w not in COMMON][:8]
    if not root or len(words) < 2:
        return []
    dirs = [str(root / d) for d in SEARCH_DIRS if (root / d).exists()]
    hits: dict[str, set[str]] = {}
    for word in words:
        try:
            found = rg(["-i", "-l", "--fixed-strings", word, *dirs]).split("\n")
        except Unreadable:
            return []  # (her per-turn note, unasked: none this turn rather than a wait)
        for path in filter(None, found):
            hits.setdefault(path, set()).add(word)
    with one_pass():
        changes = in_force()
        gone = skipped(changes)
        strong = [p for p in hits if len(hits[p]) >= 2 and str(Path(p).relative_to(root)) not in gone]
        out = []
        for path in sorted(strong, key=lambda p: (-len(hits[p]), -Path(p).stat().st_mtime)):
            try:
                matched = _lines(path, hits[path], 4)
            except Unreadable:
                break  # (a search that took too long: no more of the note this turn, never a wait)
            lines = _current_lines(root, Path(path), matched, changes, room=LINE_ROOM)
            if lines:
                out.append((str(Path(path).relative_to(root)), "\n".join(f"{n}:{line}" for n, line in lines)))
            if len(out) == 2:
                break
    return out


def note_block(rel: str, lines: str, room: int) -> str:
    """One passage of a per-turn note: "From <file> (<where it comes from>):" then its lines. (No bracket around the
    file's name: "[path]" then its lines was a shape she copied, opening her own replies, and once a greeting, with
    "[" and a line of memory.) A summary by its date and short id (name_of), never its file's name."""
    with one_pass():  # (what the summary is, read once for its name and its source)
        head = f"From {name_of(rel)} ({cite(rel, her=True)}):\n"
    if len(head) >= room:
        return ""
    body = whole_lines(lines, room - len(head))
    return head + body if body and len(head) + len(body) <= room else ""


def whole_lines(text: str, room: int) -> str:
    """Whole lines within `room` (a line is never shown without its correction or its section): past the room, every
    line carrying a correction still, whole, the correction's own line breaks too (units); the first line cut (cut)
    only when nothing else fits (a later line's correction was left out, one with a line break lost its end)."""
    out, size = [], 0
    for unit in units(text):
        gap = 1 if out else 0
        if size + len(unit) + gap > room and FIX not in unit:
            if not out:
                out.append(cut(unit, max(room, 0)))
                size += len(out[-1])
            continue
        out.append(unit)
        size += len(unit) + gap
    return "\n".join(out)


def related(text: str, limit_chars: int = 700) -> str:
    hits = related_hits(text)[:2]
    room = max(0, (limit_chars - 2 * max(0, len(hits) - 1)) // max(1, len(hits)))
    return "\n\n".join(block for rel, lines in hits if (block := note_block(rel, lines, room)))


CHAT_PAUSE = 30 * 60  # s: a chat (Telegram, or typed on the page) quiet this long is summarised into Life
# What one summary reads at once: about 40,000 tokens, well inside the window of every model that writes one (this
# Mac's memory model holds 65,536, vx). A longer conversation is summarized in parts, every word read (before, a
# summary read the first 60,000 characters and the rest was never seen).
SUMMARY_ROOM = int(os.environ.get("MEMORY_SUMMARY_CHARS", "150000"))


def _parts(turns: list[dict], room: int) -> list[list[dict]]:
    """A conversation in consecutive parts of whole messages, each within `room` (a message longer than that alone)."""
    out, part, size = [], [], 0
    for turn in turns:
        n = len(str(turn.get("text") or "")) + 40
        if part and size + n > room:
            out.append(part)
            part, size = [], 0
        part.append(turn)
        size += n
    return out + ([part] if part else [])


TRIES = 3  # a summary written while a change landed is written again, told it, this many times at most
JOB_STRETCHES = 6  # stretches one summary job writes for its own conversation, at most (each one model call)
JOB_SWEEP = 2  # other conversations' retired stretches one job writes, at most (never during a call)


def write_call_summary(call_id: str, turns: list[dict], replace: Path | None = None) -> Path | None:
    """Life §6: a timestamped episodic summary of one conversation (a call, or a stretch of chat) under
    Memory/Conversations/YYYY/MM/: one file, read in parts when it is longer than one summary's model reads at once
    (each part summarized in turn, under its own heading in the file). Written from the conversation as it stands now
    (current_rows) at one version of the change list, which both its body and its title models are told; when a change
    lands while it is written, it is written again (a forget made meanwhile came back). Published under
    the list's lock after that version is checked once more, by one rename (no reader ever sees a part of it, and no
    change lands between the check and the rename). Its identity is its stretch's first and last rows in the
    record: a stretch already in Life (replace, or found by them) is written again in its place, never a
    second time. The file, or None (it stays due)."""
    root = life()
    from core import helpers
    if not root or not turns or not helpers.available():
        return None
    for _ in range(TRIES):
        seen = revision()
        try:
            now, note, used = summary_input(turns), changes_note() + _carried_note(turns), _changes_on(turns)
        except Unreadable:
            return None  # (never written from a list that cannot be read)
        if not now:
            return None
        parts = _parts(now, SUMMARY_ROOM)
        bodies = []
        for n, part in enumerate(parts, 1):
            body = _summary_body(part, n, len(parts), note)
            if not body:
                return None
            bodies.append(body)
        path, text, key = _summary_file(call_id, turns, now, parts, bodies, note)
        try:
            with change_lock():
                if revision() != seen:
                    continue
                if any(t.get("digest") and not matches(t) for t in turns):
                    return None  # a restore/rewrite during the model call: no summary of another record
                return _publish(path, text, key, replace, used)
        except Unreadable:
            return None  # (the change list busy past LOCK_WAIT: it stays due, written next time)
    return None


def _carried_note(turns: list[dict]) -> str:
    """For the writer of a stretch that a change on its earlier summary's lines was carried onto: what
    that line said, as it was written there, and the user's own words of it, so the writer leaves it out (or corrects
    it) in whatever words the messages say it. The words alone are matched only where a message holds them (the
    backstop: summary_input); this is the writer's judgment, told plainly."""
    rows = {t["row"] for t in turns if t.get("row")}
    out = []
    for change in in_force():
        carry = change.get("carry")
        if not isinstance(carry, list) or not any(isinstance(r, dict) and r.get("row") in rows for r in carry):
            continue
        lines = "; ".join(f'"{line}"' for p in change.get("passages", []) if kind_of(p.get("path", "")) == "summary"
                          and (line := LEAD.sub("", str(p.get("text", "")), count=1).strip()))
        if not lines:
            continue
        if change["kind"] == "forget":
            out.append(f"- In this conversation they asked not to bring back what its earlier summary said in {lines} "
                       f'(in their words: "{change.get("said") or change.get("words", "")}"). Leave it out, whatever '
                       "words the messages below say it in.")
        else:
            out.append(f"- In this conversation they corrected what its earlier summary said in {lines}: what is true "
                       f'now is "{change.get("said", "")}". Keep only that.')
    return ("\n" + "\n".join(out)) if out else ""


def _changes_on(turns: list[dict]) -> list[str]:
    """The changes in force that bear on these messages (naming them, or carried onto them): what a summary of them is
    written with, kept with its identity, so an undo of one makes it due again (_undone)."""
    rows = {t["row"] for t in turns if t.get("row")}
    return [c["id"] for c in in_force()
            if any(isinstance(ref, dict) and ref.get("row") in rows
                   for ref in c.get("messages", []) + c.get("rows", []) + (c.get("carry") or []))]


def _publish(path: Path, text: str, key: str, replace: Path | None = None, used: list[str] = ()) -> Path | None:
    """The summary into Life by one rename (written whole beside it first): over the summary of the same stretch when
    there is one (replace, or one found by its rows: a retry, or the stretch written again after a forget), else as a
    new file. Never over one he edited: that one stands for the stretch as it is, and is returned
    unwritten. used: the changes it was written with (_changes_on). None when it could not be written."""
    from core.state import optional_write_failed
    folder = path.parent
    temp = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = replace if replace is not None and replace.exists() else None
        if target is None:
            with one_pass():  # (its folder's summaries judged once each, the change list read once)
                for other in sorted(folder.glob("*.md")):
                    try:
                        same = _summary_key(_summary_meta_now(other, waiting_too=True)) == key
                    except Unreadable:
                        continue  # unrelated unreadable summaries cannot stop publication
                    if same:
                        target = other
                        break
        if target is not None and _his(target):
            return target  # (his edit wins: never written over)
        held = _PASS.get()
        if held is not None:
            held.clear()  # (a summary is written now: nothing read before it in this pass still holds)
        if target is None:
            target = path
            for n in range(2, 100):  # never over an earlier summary
                if not target.exists():
                    break
                target = path.with_name(f"{path.stem}-{n}.md")
        temp = target.parent / f".{target.name}.{os.getpid()}.part"
        temp.write_text(text)
        os.replace(temp, target)
        if "- **record:** private index\n" in text:  # (after the rename, never before: a failed rename had
            source, refs = key.rsplit("|", 1)       # left her index naming a summary that is not there)
            try:
                _cache_summary(target, text, {"source_ref": source, "row digests": refs,
                                              **({"changes": list(used)} if used else {})})
            except OSError:                # (in his Life without its version: never taken for his edit of her
                optional_write_failed("summary_index")
                try:                       # earlier one; its identity is recovered from its times)
                    _uncache_summary(target)
                except (Unreadable, OSError):
                    pass
        return target
    except OSError:
        optional_write_failed("summary")
        if temp is not None:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
        return None


def _summary_key(meta: dict) -> str:
    """Which stretch of conversation a summary is: its conversation and its first and last rows in the record (one
    written from turns that are not in the record says its exact times instead)."""
    if meta.get("row digests"):
        return f"{meta.get('source_ref', '')}|{meta['row digests']}"
    if meta.get("rows"):
        return ""  # a row-only reference is not an identity after restore
    return f"{meta.get('source_ref', '')}|span {meta['span']}" if meta.get("span") else ""


def conversation_kind(turns: list[dict]) -> tuple[str, bool]:
    """What kind of conversation these turns are, from each turn's own channel (one room can be typed and spoken),
    and whether any of it was spoken (its words may be misheard)."""
    kinds = {t.get("channel") for t in turns}
    if kinds == {"telegram"}:
        return "Telegram chat", False
    if kinds == {"typed"}:
        return "typed chat", False
    if "typed" in kinds and "call" in kinds:
        return MIXED_CONVERSATION, True
    return "voice call", True


def _summary_body(turns: list[dict], part: int, parts: int, note: str = "") -> str:
    """One part's summary, as its model writes it ("" when it gave nothing). note: the change list in words."""
    kind, spoken = conversation_kind(turns)
    transcript = "\n".join(f"{_who(t)}: {t['text']}" for t in turns)
    return _llm((note + "\n\n" if note else "") +
        f"Summarize this {kind} between the user and Viventium (their AI companion) as episodic "
        "memory. Markdown sections: Goals, Decisions, Commitments, Corrections, Facts the user "
        "stated (only what the user said), Assistant suggestions, Unresolved questions, Sensitivity "
        "(low/medium/high), Confidence. Record only what was actually said in it; never "
        "infer or invent. Be specific and brief; write 'none' for empty sections. "
        "A fact about the user comes only from the user's own words: what Viventium said, offered, guessed or "
        "repeated back is never one, and a guess stays a guess. "
        + ("The user's words came through speech recognition, so names and numbers may be misheard: where a fact "
           "rests on such a word, say it may be misheard. Lines marked as heard nearby were not said to Viventium "
           "and may be someone else's: never a fact about the user. " if spoken else "")
        + "Where a line says the user corrected it, keep only the corrected version, and leave out what they asked "
        "not to bring back, whatever words it is in. Leave out how Viventium said "
        "she feels and what moves her: her inner life is private and is not memory of the user."
        + (f" This is part {part} of {parts} of one long conversation, in order." if parts > 1 else "") + "\n\n"
        + transcript)


def _summary_file(call_id: str, stretch: list[dict], turns: list[dict], parts: list[list[dict]], bodies: list[str],
                  note: str = "") -> tuple[Path, str, str]:
    """The summary's place, its whole text and its identity (_summary_key): its stretch's first and last rows."""
    root = life()
    start = dt.datetime.fromtimestamp(stretch[0]["t"])  # (the stretch's own times: where a retry looks for it)
    end = dt.datetime.fromtimestamp(stretch[-1]["t"])
    kind, spoken = conversation_kind(turns)
    transcript = "\n".join(f"{_who(t)}: {t['text']}" for t in turns)
    # (its title is named from its opening: a title, not memory; told the change list too, so it never names
    # what they asked not to bring back)
    title = _llm((note + "\n\n" if note else "") + "Give a 3-6 word title for this conversation, no punctuation, "
                 "leaving out anything the user asked not to bring back:\n\n" + transcript[:4000], 20) or kind.capitalize()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or kind.lower().replace(" ", "-")
    out = root / "Memory" / "Conversations" / f"{start:%Y}" / f"{start:%m}" / f"{start:%Y-%m-%d-%H%M}-{slug}.md"
    rows = [t["row"] for t in stretch if t.get("row")]
    where = ({"rows": f"{rows[0]} to {rows[-1]}",
              "row digests": json.dumps([{"row": t["row"], "digest": t.get("digest") or row_ref(t["row"])["digest"]}
                                         for t in stretch], separators=(",", ":"))} if len(rows) == len(stretch)
             else {"span": f"{float(stretch[0]['t']):.6f} to {float(stretch[-1]['t']):.6f}"})
    meta = {"source": f"Viventium AI {kind}", "source_ref": f"{kind} {call_id}",
            "started": f"{start:%Y-%m-%d %H:%M}", "ended": f"{end:%Y-%m-%d %H:%M}",
            "participants": "user, Viventium",
            "words": ("typed and spoken, through speech recognition" if kind == MIXED_CONVERSATION else
                      "spoken, through speech recognition" if spoken else "typed"),
            **({"parts": f"{len(parts)}, each summarized in turn"} if len(parts) > 1 else {}),
            **({"record": "private index",
                "span": f"{min(float(t['t']) for t in stretch):.9f} to {max(float(t['t']) for t in stretch):.9f}"}
               if "row digests" in where else where),
            "published": f"{time.time():.9f}",
            "last_sync": f"{dt.datetime.now():%Y-%m-%d %H:%M}"}
    if len(parts) == 1:
        body = bodies[0]
    else:  # (each part under its own heading, its sections one level down)
        body = "\n\n".join(
            f"## Part {n} of {len(parts)}, {dt.datetime.fromtimestamp(part[0]['t']):%H:%M} to "
            f"{dt.datetime.fromtimestamp(part[-1]['t']):%H:%M}\n\n" + re.sub(r"(?m)^(#{2,5}) ", r"#\1 ", text.strip())
            for n, (part, text) in enumerate(zip(parts, bodies), 1))
    return out, (f"# {title}\n\n" + "\n".join(f"- **{k}:** {v}" for k, v in meta.items()) + "\n\n" + body + "\n"), \
        _summary_key({**meta, **where})


def _who(turn: dict) -> str:
    """Who said a line, as the summary's model is told: words only heard (Wing, Listen only) may be someone else's."""
    if turn.get("heard"):
        return "heard nearby (maybe not said to Viventium, maybe someone else)"
    return turn["role"]


def _call_rows(call_id: str) -> list[dict]:
    """Every message of one conversation, in order, each with its row in the record (one index per version of the
    record, shared by every summary a pass looks at)."""
    return list(_calls()[0].get(call_id, ()))


def _calls() -> tuple[dict, dict]:
    """The record by conversation, once per version of it: {call: its messages in row order} and, made when first
    asked, {call: its messages' (time, place) in time order} (_rows_between)."""
    rows = record_rows()
    held = _RECORD.get("calls")
    if held is None or held[0] is not rows:
        calls: dict = {}
        for n, row in enumerate(rows, 1):
            if row:
                calls.setdefault(row.get("call_id"), []).append({**row, "row": n})
        held = (rows, calls, {})
        _RECORD["calls"] = held  # (one assignment: a reader in another thread sees the old index or the new, whole)
    return held[1], held[2]


def _rows_between(call_id: str, start: float, end: float, end_too: bool = False,
                  published: float = math.inf) -> list[dict]:
    """This conversation's messages from `start` to `end` (`end` itself only with end_too), none recorded after
    `published`, in row order. Raises ValueError when a time of its record cannot be read."""
    calls, times = _calls()
    every = calls.get(call_id, [])
    if call_id not in times:
        found = []
        for i, row in enumerate(every):
            t = float(row.get("t") or 0)  # (ValueError/TypeError: a time that cannot be read)
            if math.isfinite(t):
                found.append((t, i))
        times[call_id] = sorted(found)
    order = times[call_id]
    out = []
    for t, i in order[bisect.bisect_left(order, (start, -1)):]:
        if t > end or (t == end and not end_too):
            break
        if t <= published:
            out.append(every[i])
    return sorted(out, key=lambda row: row["row"])


def _marks_file() -> Path:
    from core.state import STATE_ROOT
    return STATE_ROOT / "core" / "summarized.json"


def _summarized_to(call_id: str) -> int:
    """The conversation's high-water mark: the last row its ordinary summaries reached (0: none, or a mark that cannot be
    certified any more: a restored or rewritten record). A retired older summary below it, or a summary that must be
    written again, is a due stretch of its own (_due), never a reason to start the conversation over: that once returned
    0 for the whole conversation, and for Telegram that was every message he ever sent her. Raises
    ValueError when the marks cannot be read: the conversation then stays due, never started over."""
    with one_pass():
        return _marks_of(call_id)[0]


def _marks(path: Path) -> dict:
    """The marks file as it is, read once per pass while it is unchanged (ValueError: it cannot be read)."""
    def read() -> dict:
        marks = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(marks, dict):
            raise ValueError("the marks of what was summarized cannot be read")
        return marks
    if _PASS.get() is None:
        return read()
    try:
        st = path.stat()
        key = ("marks", str(path), st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        return read()
    held = _PASS.get()
    if key not in held:
        held[key] = read()
    return held[key]


def _marks_of(call_id: str) -> tuple[int, int]:
    """(the high-water mark, the last row main's own count covered): main's summaries hold everything up to that row
    of the conversation (its count only grew once a summary was written); after that, only her summaries with row
    identity cover a row. Kept in the marks when its count is converted (_mark). Marks written before messages had row identity count
    messages: the row of that message."""
    marks = _marks(_marks_file())
    rows = marks.get("rows", {})
    if not isinstance(rows, dict) or any(not _count(n, 0) for n in rows.values()):
        raise ValueError("the summary row marks cannot be read")
    main = marks.get("main", {})
    if not isinstance(main, dict) or any(not _count(n, 0) for n in main.values()):
        raise ValueError("the main summary marks cannot be read")
    if call_id in rows:
        refs = marks.get("digests", {})
        if not isinstance(refs, dict):
            raise ValueError("the summary digests cannot be read")
        if call_id in refs and not matches({"row": rows[call_id], "digest": refs[call_id]}):
            return 0, 0  # a restored or rewritten record is due again
        stretches = marks.get("stretches", {})
        if not isinstance(stretches, dict):
            raise ValueError("the summary stretches cannot be read")
        stretch = stretches.get(call_id)
        if stretch is None:
            return 0, 0  # a last-row-only mark cannot certify earlier source rows
        snapshot = row_changes([])
        expected = [{"row": r["row"], "digest": r["digest"]}
                    for r in _call_rows(call_id) if r["row"] <= rows[call_id]]
        if not expected or stretch != expected or not all(snapshot.matches(ref) for ref in stretch):
            return 0, 0
        return int(rows[call_id]), min(int(main.get(call_id, 0)), int(rows[call_id]))
    count = marks.get(call_id, 0)
    if not _count(count, 0):
        raise ValueError("the summary count cannot be read")
    said = _call_rows(call_id)
    row = said[count - 1]["row"] if 0 < count <= len(said) else (said[-1]["row"] if count > len(said) and said else 0)
    return row, row


def _due(call_id: str, upto: int, main: int = 0) -> list[tuple[list[dict], Path | None]]:
    """The stretches of this conversation below its mark (`upto`) that are due again, each to be written alone with row
    identity, with the file it is written in place of (None: a new one, beside):
      - a retired older summary's own stretch: the record rows inside its stated minutes, end minute included (its
        file stays in his Life as it is, never read again; the new summary goes beside it);
      - a summary of hers whose identity no longer holds (its index entry lost, or its record changed): its own rows,
        in its place;
      - rows after main's count (`main`) that no summary of hers covers any more, though he said something there (a
        stretch whose every word was forgotten, then brought back by an undo).
    Rows a summary with row identity names are never in one, nor is anything after the mark (the next ordinary stretch)
    or main's own coverage. Each holds at least one of his messages as it stands now. One pass: the record, the change
    list and the summary folder read once."""
    root = life()
    if not root or upto <= 0:
        return []
    every = [row for row in _call_rows(call_id) if row["row"] <= upto]
    if not every:
        return []
    retired = _retired_summaries(call_id)
    covered: set[int] = set()
    groups: list[tuple[list[dict], Path | None]] = []
    for path, head, span in _call_summaries(call_id):
        if _older(head):
            if str(path.relative_to(root)) in retired:
                groups.append((_stated(call_id, head, span), None))
            continue  # (an older summary keeps what main's count covered)
        refs = _certified(path, head)
        if refs is None:
            groups.append((_span_rows(call_id, head, path), path))
        else:
            covered.update(ref["row"] for ref in refs)
    covered.update(_gone_hers(call_id))
    visible = {row["row"] for row in summary_input(every) if row.get("role") == "user"}
    taken: set[int] = set()
    out = []
    for rows, target in sorted(groups, key=lambda group: group[0][0]["row"] if group[0] else 0):
        stretch = [row for row in rows if row["row"] <= upto and row["row"] not in covered and row["row"] not in taken]
        if any(row["row"] in visible for row in stretch):
            out.append((stretch, target))
            taken.update(row["row"] for row in stretch)
    run: list[dict] = []
    for row in every + [None]:  # (after main's count: rows no summary of hers covers any more)
        if row is not None and row["row"] > main and row["row"] not in covered and row["row"] not in taken:
            run.append(row)
            continue
        if any(r["row"] in visible for r in run):
            out.append((run, None))
        run = []
    return sorted(out, key=lambda item: item[0][0]["row"])


def older_stretch(rel: str) -> list[dict]:
    """An older summary's conversation as the record keeps it: its conversation's rows inside its stated minutes, end
    minute included, less those a summary of hers with row identity names (another stretch's). What her look at that
    conversation shows, each message by its row, for him to name (core/memory: a whole-conversation forget of an older
    summary); never a selection of messages by itself. [] when it is not an older summary or its header cannot be
    read."""
    from core.memory import _span
    root = life()
    if not root:
        return []
    with one_pass():
        try:
            head = _summary_meta_text(_file_text(root / rel))
            span = _span(head)
        except (OSError, TypeError, ValueError, OverflowError):
            return []
        if not span or not _older(head):
            return []
        covered: set[int] = set()
        for path, other, _ in _call_summaries(span["call"]):
            if not _older(other) and (refs := _certified(path, other)) is not None:
                covered.update(ref["row"] for ref in refs)
        return [row for row in _stated(span["call"], head, span) if row["row"] not in covered]


def _stated(call_id: str, head: dict, span: dict) -> list[dict]:
    """An older summary's own stretch: its conversation's rows inside its stated minutes, end minute included (an exact
    span with its end), in row order; none when the record's times cannot be read."""
    try:
        return _rows_between(call_id, span["from"], span["to"], end_too=bool(head.get("span")))
    except (TypeError, ValueError, OverflowError):
        return []


def _certified(path: Path, head: dict) -> list[dict] | None:
    """The rows a summary of hers names while its identity holds (its index entry, matching the record); None when it
    must be written again (its entry lost or only recovered from times, its record changed, or a change it was written
    with undone since). One he edited is covered as it is: never written again."""
    try:
        text = _file_text(path)
        if head.get("record") == "private index":
            index = _summary_index(path, text)
            identity = _summary_identity(path, text, head, index)
            if (identity is None or identity.get("recovered")) and (edited := _edited(path, text, index)):
                return json.loads(edited["row digests"])  # (his edit: covered, never written again)
            if identity is None or identity.get("recovered") or _undone(identity) or _changed_since(identity, head):
                return None
            return json.loads(identity["row digests"])
        refs = json.loads(head["row digests"])  # (an older shape of hers: its rows in its header)
        record = record_rows()
        if isinstance(refs, list) and refs and all(_row_ref(ref) and ref["row"] <= len(record) and record[ref["row"] - 1]
                                                   and record[ref["row"] - 1]["digest"] == ref["digest"] for ref in refs):
            return refs
    except (OSError, TypeError, ValueError, KeyError):
        pass
    return None


def _span_rows(call_id: str, head: dict, path: Path) -> list[dict]:
    """A summary of hers that must be written again: its own rows, by its exact span, none recorded after it was
    published (_summary_rows), in row order."""
    try:
        return _summary_rows(head, path, whole=True)
    except Unreadable:
        return []


def _due_calls() -> list[str]:
    """The conversations with a stretch due below their mark (another conversation's summary job writes it: a voice
    call's room never comes again): a retired older summary's, or one of hers to write again in its place after a change
    to its messages or an undo (forgetting one message of a past call had hidden its whole summary for
    good). Only those a recorded change touches are looked at. One pass over the summary folder, the change list and
    the record."""
    out = []
    with one_pass():
        try:
            touched = {call for change in _touches() for call in [*change["times"], *change["unknown"]]}
        except (OSError, ValueError, Unreadable):
            return out
        every = "" in touched  # (a change whose conversation cannot be known touches every one)
        for call in sorted(_summaries_by_call(), key=str):
            if not (every or call in touched):
                continue
            try:
                if _due(call, *_marks_of(call)):
                    out.append(call)
            except (OSError, ValueError, Unreadable):
                continue
    return out


def _already(call_id: str, stretch: list[dict]) -> tuple[Path, int] | None:
    """A summary already in Life for a stretch starting at this one's first row (published, its mark lost): its file and
    its last row (the turns after it start the next stretch; it is written again in its place)."""
    root = life()
    if not root or not stretch:
        return None
    start = dt.datetime.fromtimestamp(stretch[0]["t"])
    folder = root / "Memory" / "Conversations" / f"{start:%Y}" / f"{start:%m}"
    for path in sorted(folder.glob("*.md")) if folder.exists() else []:
        try:
            meta = _summary_meta_now(path, waiting_too=True)  # (one waiting to be written again is still this one)
            refs = json.loads(meta.get("row digests", "[]"))
        except (Unreadable, TypeError, ValueError):
            continue
        if (isinstance(refs, list) and refs and all(_row_ref(ref) and matches(ref) for ref in refs)
                and refs[0]["row"] == stretch[0]["row"] and _summary_rows(meta, path) == refs):
            return path, refs[-1]["row"]
    return None


def relationship_call_after(call_id: str) -> list[dict]:
    """What of this conversation is still to summarize (only to know whether it is due: never shown): its due stretches
    below its mark (_due), then what was said since its last summary. A mark that cannot be read leaves it due, through
    the same guarded path as summarize (never an error first). One pass."""
    with one_pass():
        try:
            last, main = _marks_of(call_id)
            holes = _due(call_id, last, main)
        except (OSError, ValueError):
            return _call_rows(call_id)
        return [row for stretch, _ in holes for row in stretch] + [row for row in _call_rows(call_id) if row["row"] > last]


def summarize(call_id: str, due_only: bool = False) -> Path | None:
    """What was said in this conversation since its last summary, as one episodic Life summary; with nothing said since,
    its first due stretch below the mark, alone (_due: a retired older summary's own stretch, or one of hers to write
    again), with row identity, the mark and every other summary as they are. due_only: a due stretch or
    nothing (another conversation's job). What the user asked to forget is left out of it, and what they corrected is
    said as corrected (write_call_summary). One at a time per state (a second caller returns, and the conversation
    stays due); none while the change list or the marks cannot be read. A stretch already in Life whose mark was lost
    is written again in its place (it may have been written before a forget), and what was said after it is the next
    stretch."""
    marks_file = _marks_file()
    from core.state import closed_file, optional_write_failed
    lock = marks_file.with_name("summarizing.lock")
    try:
        held = closed_file(lock, "a")
    except OSError:
        optional_write_failed("summary")
        return None
    with held:
        try:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        try:
            with one_pass():
                last, main = _marks_of(call_id)
                stretch = [row for row in _call_rows(call_id) if row["row"] > last]
                holes = (_due(call_id, last, main) if due_only or not any(row["role"] == "user" for row in stretch)
                         else [])
                there = None if holes or due_only else _already(call_id, stretch)
        except (OSError, ValueError):
            return None  # (never started over from a mark that cannot be read: it stays due, said in the log)
        if holes:  # (in another conversation's job too, one of hers in its place: a call's room never comes again;
            # one he edited is never due, and never written over: _his)
            return _rebuild(call_id, *holes[0])
        if due_only:
            return None
        if there:
            stretch = [row for row in stretch if row["row"] <= there[1]]
            if _his(there[0]):  # (his edit of it holds that stretch: never written again)
                _mark(call_id, there[1])
                return None
        try:
            seen = revision()
            turns = summary_input(stretch)
        except Unreadable:
            return None
        if not stretch:
            return None
        if not any(t["role"] == "user" for t in turns):  # a greeting or a lone result is not a conversation
            if any(t["role"] == "user" for t in stretch) and life():  # all they said was forgotten: nothing to keep
                try:
                    with change_lock():
                        if revision() != seen:
                            return None
                        if there:
                            _uncache_summary(there[0])
                            there[0].unlink(missing_ok=True)
                        _mark(call_id, stretch[-1]["row"])
                except Unreadable:
                    return None  # (a lock busy past LOCK_WAIT: it stays due)
            return None
        out = write_call_summary(call_id, stretch, replace=there[0] if there else None)
        if out:  # a failed summary stays due: the next try covers the same conversation
            try:
                _mark(call_id, stretch[-1]["row"])
            except OSError:
                optional_write_failed("summary_mark")  # (it stays due)
        return out


def _rebuild(call_id: str, stretch: list[dict], target: Path | None) -> Path | None:
    """A due stretch below the mark, written alone with row identity: in place of a summary of hers whose identity no
    longer holds, else as a new file beside the older summary it stands for (that file stays in his Life as it is,
    never read again). The mark and every other summary stay as they are; once it is written its rows are covered,
    so it is no longer due. Nothing is written when nothing he said there is left (and nothing is due then)."""
    try:
        turns = summary_input(stretch)
    except Unreadable:
        return None
    if not any(turn["role"] == "user" for turn in turns):
        return None
    return write_call_summary(call_id, stretch, replace=target)


def _mark(call_id: str, row: int) -> None:
    """How far each conversation is summarized: the last row of its last summary, written whole by one rename. Ids and
    row numbers with original-line digests, so an ordinary file (core/state.private_file refuses a state folder that holds the Life, as
    core_test's does). When main's count for it is replaced, the row that count reached is kept ("main": what main's
    own summaries hold, _marks_of)."""
    path = _marks_file()
    try:
        marks = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        marks = {}
    marks = marks if isinstance(marks, dict) else {}
    rows = dict(marks.get("rows") or {})
    main = dict(marks.get("main") or {})
    count = marks.get(call_id)
    if call_id not in rows and call_id not in main and _count(count, 1):
        said = _call_rows(call_id)
        main[call_id] = said[count - 1]["row"] if count <= len(said) else (said[-1]["row"] if said else 0)
    rows.pop(call_id, None)  # (most recently marked last: the 200 kept are the latest used, never his Telegram first)
    rows[call_id] = int(row)
    digests = dict(marks.get("digests") or {})
    digests[call_id] = row_ref(row).get("digest", "")
    stretches = dict(marks.get("stretches") or {})
    stretches[call_id] = [{"row": r["row"], "digest": r["digest"]} for r in _call_rows(call_id) if r["row"] <= row]
    rows = dict(list(rows.items())[-200:])
    marks = {**{k: v for k, v in marks.items() if k not in ("rows", "digests", "stretches", "main", "retired", call_id)},
             "rows": rows, "digests": {key: digests[key] for key in rows if key in digests},
             "stretches": {key: stretches[key] for key in rows if key in stretches},
             "main": {key: main[key] for key in rows if key in main}}
    temp = path.with_name(f".{path.name}.{os.getpid()}.part")
    from core.state import closed_file
    with closed_file(temp, "w") as f:  # (his alone from the start, like the folder it makes: core/state.py)
        f.write(json.dumps(marks))
    os.replace(temp, path)


if __name__ == "__main__":  # background jobs: python -m core.life core | summary <call_id>
    if sys.argv[1] == "core" and core_is_stale():
        refresh_core()
    elif sys.argv[1] == "summary":
        # Its own conversation (what was said since its last summary, then each due stretch below its mark, each
        # once), then, unless a call is on, another conversation's retired stretch: a voice call's room never comes
        # again, so its rebuild waits for no job of its own.
        from core.state import call_live
        call, wrote = sys.argv[2], []
        for _ in range(JOB_STRETCHES):
            if not any(t["role"] == "user" for t in relationship_call_after(call)):
                break
            out = summarize(call)
            if out is None or out in wrote:
                break
            wrote.append(out)
        for other in [] if call_live() else [c for c in _due_calls() if c != call][:JOB_SWEEP]:
            if (out := summarize(other, due_only=True)) is not None:
                wrote.append(out)
        print("\n".join(map(str, wrote)) or None)
        if wrote and os.environ.get("MEMORY_EMBED") != "off":  # index new summaries when meaning search is on
            from core import memory
            memory.refresh(seconds=120)
        if wrote and core_is_stale():  # what she just learned reaches her core view the same day
            refresh_core()
        if any(t["role"] == "user" for t in relationship_call_after(call)):  # still a conversation to keep: try again
            sys.exit(1)
    print(json.dumps({"done": sys.argv[1]}))
