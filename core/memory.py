"""Her memory: found by meaning beside the word match (core/life.py), and what she keeps, shown and changed.

A local index of Life's own text (read in place; the index lives in Light's state, never in Life or a repo),
embedded by a small local model. Recall:

  per_turn(words)   before she answers: the word match as before, plus the nearest passage by meaning,
                    in the same space and within a fixed wait, so her first word is never later for it
  deep(talk, seen)  the memory search of the Deep memory cortex, after every answer (brain/rounds.py): a wider
                    look across Life with the last few turns; the cortex then judges, on its card's place, what of it
                    bears on the turn (the search alone cannot tell a true match from small talk)
  search(words)     the recall tool: the word search over all of Life, plus the nearest passages by meaning
Every passage says where it comes from and when (core/life.cite) and goes through core/life.current: what the user
asked to forget is never brought back, and what they corrected says what is true now. When the search by meaning is not
there (its server away, no index yet), recall says so: words only. Without it, all of it falls back to the word match.
A limit in his words ("only my plans") keeps a search to those Life folders.

What she keeps, shown and changed (by voice: brain/memory_tools.py; on screen: settings/memory.py):

  inspect(about)                every place in her memory that bears on it, item by item, with where it comes from
  correct(old, new, passages)   from now on she goes by what he says is true (`new`, his words), about the passages
                                it names (as recall showed them) and, in the conversation, what said the old words
  forget(what, passages)        she does not bring it up again: the passages it names, and what said those words
                                in the conversation before; or a whole conversation, by its summary's reference
  undo(change)                  the change no longer holds
  changes()                     what was changed, newest first
A change writes one line, to Light's private change list (core/life.ledger), and nothing else: his notes are never
edited by it (the night's Sleep writes a correction into them under his Life's own rule; deleting from his notes is an
ordinary request for a Worker). Every reader applies the list, and every model that reads his Life is told it in words.

    python -m core.memory refresh | stats | search "<what you want to find>"
"""
import fcntl
import hashlib
import contextvars
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from core import life
from core.state import STATE_ROOT, closed_dir, closed_file

INDEX = STATE_ROOT / "memory" / "index.sqlite"
EMBED_URL = os.environ.get("EMBED_URL", "http://127.0.0.1:11437")  # Light's own small Ollama for the embedding model (vx serve_embed)
EMBED_MODEL = os.environ.get("EMBED_MODEL", "qwen3-embedding:0.6b")
# How the index cuts a file into passages and numbers them. An index made another way is built again, once, on this
# Mac's embedding server (no guessing where an old passage starts; the earlier cut numbered a passage from a
# blank line above it).
CHUNKER = "4"
# What is found without being asked for stays out of the sensitive folders (as her core view does) and out of
# code and tool output; the recall tool's word search still reaches all of Life when she chooses to look.
AUTO_SKIP = life.SEARCH_SKIP | set(filter(None, os.environ.get(
    "MEMORY_AUTO_SKIP", "Projects,Workspaces,Finance,Health,Legal").split(",")))
ASK = ("Instruct: Given what was just said in a conversation, retrieve the user's own notes and past "
       "conversations that bear on it\nQuery: ")  # (this model family expects the task with the query)
CHUNK, MAX_FILE, BATCH = 900, 1_000_000, 32
QUERY = 6000  # characters searched as one (about 1,500 tokens; its server reads 8,192, vx serve_embed): longer, in parts
# Seconds her turn waits for the per-turn search by meaning; later than this, words only. A warm server answers in tens
# of milliseconds, so the wait ends as soon as it does: the bound binds only on a server waking from idle, which can
# take a few tenths of a second. At 0.15 s, the first message after a long quiet spell lost its meaning half.
TURN_WAIT = float(os.environ.get("MEMORY_TURN_WAIT", "0.8"))
TURN_ASK = 5.0  # seconds the per-turn request itself may take: never hung up at her turn's wait (it finishes, warm)
MEANING_ROOM = 400  # characters of a passage found by meaning in her search (its section and corrections kept whole)
NEAR = float(os.environ.get("MEMORY_NEAR", "0.60"))        # per turn: how alike a passage must be to be shown
DEEP_NEAR = float(os.environ.get("MEMORY_DEEP_NEAR", "0.40"))  # Deep Memory: candidates; a model then weighs them
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="memory")
_loaded: tuple | None = None  # (index mtime, matrix, rows)


def embed(texts: list[str], timeout: float = 120.0) -> np.ndarray:
    """Unit vectors for these texts from the local embedding model. Raises when it does not answer (why_not says why
    in words)."""
    body = json.dumps({"model": EMBED_MODEL, "input": texts, "keep_alive": -1}).encode()
    request = urllib.request.Request(EMBED_URL + "/api/embed", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        vectors = np.asarray(json.load(reply)["embeddings"], dtype=np.float32)
    return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)


def folders(root: Path) -> list[Path]:
    """Life's own folders (capitalised, as Life/AGENTS.md lays them out), minus AUTO_SKIP."""
    return [d for d in sorted(root.iterdir()) if d.is_dir() and d.name[:1].isupper() and d.name not in AUTO_SKIP]


def _files(root: Path) -> dict[str, tuple[int, int]]:
    with life.one_pass():  # (each summary judged once, the change list and the record read once)
        return _files_now(root)


def _files_now(root: Path) -> dict[str, tuple[int, int]]:
    found = {}
    for folder in folders(root):
        for path in folder.rglob("*"):
            if path.suffix.lower() in (".md", ".txt") and path.is_file() and not any(p.startswith(".") for p in path.parts):
                if life.source(str(path.relative_to(root)), root).get("unreadable"):
                    continue
                stat = path.stat()
                if 0 < stat.st_size <= MAX_FILE:
                    found[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
    return found


def pieces(text: str) -> list[tuple[int, str]]:
    """A file as passages of about CHUNK characters, cut at blank lines, each with the number of its first line with
    words on it (a passage starting after blank lines was numbered from the blank)."""
    out, block, start, size = [], [], 1, 0

    def put() -> None:
        lead = next((i for i, line in enumerate(block) if line.strip()), len(block))
        out.append((start + lead, "\n".join(block[lead:]).strip()))
    for number, line in enumerate(text.split("\n"), 1):
        # Flush before a normal line would cross the ceiling. Identity headers from older
        # summaries are skipped too; their line numbers still belong to the original file.
        if line.startswith(("- **row digests:**", "- **rows:**")):
            if block:
                put()
                block, size = [], 0
            continue
        if len(line) > 2 * CHUNK:
            if block:
                put()
                block, size = [], 0
            # One long paragraph still has its original line number in every piece.
            count = (len(line) + CHUNK - 1) // CHUNK
            width = (len(line) + count - 1) // count
            for offset in range(0, len(line), width):
                out.append((number, line[offset:offset + width]))
            continue
        if block and size + len(line) + 1 > 2 * CHUNK:
            put()
            block, size = [], 0
        if not block:
            start = number
        block.append(line)
        size += len(line) + 1
        if (not line.strip() and size >= CHUNK) or size >= 2 * CHUNK:
            put()
            block, size = [], 0
    if block:
        put()
    return [(n, piece) for n, piece in out if len(piece) >= 40]


_MAKING = threading.Lock()


def _open() -> sqlite3.Connection:
    # Her index is his alone from the start: made 0600 here when it is not there yet, in a folder made 0700 (SQLite
    # gives its journal the database file's mode). Only when it is made, and one thread at a time: a second
    # descriptor closed on a database another connection of this process has open would drop SQLite's locks on it.
    with _MAKING:
        closed_dir(INDEX.parent)
        try:
            os.close(os.open(INDEX, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            pass
    db = sqlite3.connect(INDEX, timeout=30)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, path TEXT, line INTEGER, text TEXT, vec BLOB);
        CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);""")
    return db


def refresh(seconds: float | None = None) -> dict:
    """Bring the index up to date with Life: new and changed files are embedded, removed ones dropped.
    One refresh at a time (a second caller returns at once); `seconds` stops a long first build early, and
    the next refresh continues where it stopped."""
    root = life.life()
    if not root:
        return {"life": False}
    began, done = time.monotonic(), {"embedded": 0, "removed": 0, "files": 0}
    with closed_file(INDEX.with_suffix(".lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"busy": True}
        db = _open()
        with db:
            if (row := db.execute("SELECT value FROM meta WHERE key='model'").fetchone()) and row[0] != EMBED_MODEL:
                db.execute("DELETE FROM chunks"); db.execute("DELETE FROM files")  # another model: other vectors
            if (row := db.execute("SELECT value FROM meta WHERE key='life'").fetchone()) and row[0] != str(root):
                db.execute("DELETE FROM chunks"); db.execute("DELETE FROM files")  # another Life folder
            if (db.execute("SELECT value FROM meta WHERE key='chunker'").fetchone() or [""])[0] != CHUNKER:
                db.execute("DELETE FROM chunks"); db.execute("DELETE FROM files")  # cut another way: built again
            db.execute("INSERT OR REPLACE INTO meta VALUES('model', ?)", (EMBED_MODEL,))
            db.execute("INSERT OR REPLACE INTO meta VALUES('life', ?)", (str(root),))
            db.execute("INSERT OR REPLACE INTO meta VALUES('chunker', ?)", (CHUNKER,))
        now, had = _files(root), dict((p, (m, s)) for p, m, s in db.execute("SELECT path, mtime_ns, size FROM files"))
        for path in [p for p in had if now.get(p) != had[p]]:
            with db:
                db.execute("DELETE FROM chunks WHERE path=?", (path,)); db.execute("DELETE FROM files WHERE path=?", (path,))
            done["removed"] += path not in now
        for path in sorted(p for p in now if now[p] != had.get(p)):
            if seconds is not None and time.monotonic() - began > seconds:
                done["more"] = True
                break
            parts = pieces((root / path).read_text(errors="replace"))
            vectors = [embed([f"{path}\n{text}" for _, text in parts[i:i + BATCH]]) for i in range(0, len(parts), BATCH)]
            with db:  # a file's passages and its row land together: a stopped build never half-knows a file
                for (line, text), vector in zip(parts, (v for batch in vectors for v in batch)):
                    db.execute("INSERT INTO chunks(path, line, text, vec) VALUES(?,?,?,?)", (path, line, text, vector.tobytes()))
                db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (path, *now[path]))
            done["embedded"] += len(parts)
            done["files"] += 1
        db.close()
    return {**done, "seconds": round(time.monotonic() - began, 1)}


def _index() -> tuple[np.ndarray, list[tuple[str, int, str]]]:
    """The whole index in memory (a few thousand passages), reloaded when a refresh has changed it."""
    global _loaded
    root = life.life()
    try:
        stamp = (INDEX.stat().st_mtime_ns, str(root))
    except OSError:
        return np.zeros((0, 1), dtype=np.float32), []
    if not root:  # no Life folder: no memory (a test without one never reads an index built from a real one)
        return np.zeros((0, 1), dtype=np.float32), []
    if _loaded is None or _loaded[0] != stamp:
        db = _open()
        mine = (db.execute("SELECT value FROM meta WHERE key='life'").fetchone() or [""])[0] == str(root) and (
            db.execute("SELECT value FROM meta WHERE key='chunker'").fetchone() or [""])[0] == CHUNKER
        rows = db.execute("SELECT path, line, text, vec FROM chunks").fetchall() if mine else []
        db.close()
        matrix = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float32).reshape(len(rows), -1) if rows \
            else np.zeros((0, 1), dtype=np.float32)
        _loaded = (stamp, matrix, [(r[0], r[1], r[2]) for r in rows])
    return _loaded[1], _loaded[2]


class Near(list):
    """What a search by meaning found, best first, and whether it could search at all: `answered` False means it could
    not (`why` says why, in words), so an empty result is never read as "nothing there". Each call has its own: two
    searches at once never share a reason."""

    def __init__(self, hits=(), answered: bool = True, why: str = ""):
        super().__init__(hits)
        self.answered, self.why = answered, why


def answered(found) -> bool:
    """Whether a search's result came from a search that ran (a plain list, as before: yes)."""
    return getattr(found, "answered", True)


def why_not(e: BaseException) -> str:
    """Why the embedding server gave no vectors, in words: too slow, refused, or not there."""
    reason = getattr(e, "reason", e)
    if isinstance(e, urllib.error.HTTPError):
        return f"its model refused the request ({e.code})"
    if isinstance(reason, (socket.timeout, TimeoutError)) or isinstance(e, (socket.timeout, TimeoutError)):
        return "it did not answer in time"
    return "its model is not running"


def windows(text: str) -> list[str]:
    """A query as the search by meaning reads it: whole when it fits, else in parts of about QUERY characters cut at a
    line or a sentence, each searched: the end of a long dictation, where a constraint often is, as much as its start."""
    rest, out = text.strip(), []
    while len(rest) > QUERY:
        cut = max(rest.rfind("\n", 0, QUERY), rest.rfind(". ", 0, QUERY))
        cut = cut + 1 if cut > QUERY // 2 else QUERY
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return out + ([rest] if rest else [])


def nearest(query: str | list[str], k: int = 6, under: tuple[str, ...] = (), timeout: float = 5.0,
            spans: bool = False) -> Near:
    """The passages closest in meaning to `query` (all of it: a long one in parts, each passage scored by the part it
    is closest to; a list: each of its texts so, the closest of all of them scoring a passage): (how alike 0..1, file, line, text), best first, each as it stands now (core/life.current, by the
    passages a change names; a conversation forgotten whole is not searched). `under` keeps it to files below those
    Life folders. spans: each with the last line of the file it runs to, too (a look offers the passage by its own
    lines, never its first line alone). Empty and not answered (Near) when there is no index or the embedding server did not answer, with why. One pass: the change list, her index and each summary read once for all of it (before,
    with line forgets carried, every passage had read them again, and the search took seconds)."""
    with life.one_pass():
        found = _nearest(query, k, under, timeout)
    return found if spans else Near([hit[:4] for hit in found], found.answered, found.why)


def _nearest(query: str | list[str], k: int, under: tuple[str, ...], timeout: float) -> Near:
    if os.environ.get("MEMORY_EMBED") == "off":
        return Near(answered=False)
    matrix, rows = _index()
    if not rows:
        return Near(answered=False, why=("its index is being built again" if INDEX.exists() and _stale() else
                                         "no index yet") if life.life() else "")
    parts = list(dict.fromkeys(part for text in ([query] if isinstance(query, str) else query) for part in windows(text)))
    if not parts:
        return Near()
    try:
        asked = np.concatenate([embed([ASK + part for part in parts[i:i + BATCH]], timeout=timeout)
                                for i in range(0, len(parts), BATCH)])
    except Exception as e:  # noqa: BLE001 (the server did not answer: said, and the word match still answers)
        return Near(answered=False, why=why_not(e))
    if asked.shape[1] != matrix.shape[1]:
        return Near(answered=False, why="its index was built by another model")
    scores = (matrix @ asked.T).max(axis=1)
    if under:
        scores = np.where([path.startswith(tuple(u.rstrip("/") + "/" for u in under)) for path, _, _ in rows], scores, -1.0)
    changes, out = life.in_force(), []  # (Unreadable: the caller says it, nothing is shown)
    gone = life.skipped(changes)
    for i in np.argsort(-scores)[:k * 3 if changes else k]:
        if scores[i] <= 0:
            break
        path, line, text = rows[i]
        if path in gone:
            continue
        found = _passage_span(path, line, text)  # (read again from the file: numbered as it is, never a stale copy)
        if found is None:
            continue
        now, line, end = found
        if changes:
            now = life.current(now, 0.0, changes, path, first=line)
            if not now.strip():
                continue
        out.append((float(scores[i]), path, line, now, end))
        if len(out) == k:
            break
    return Near(out)


def _passage_now(path: str, line: int, text: str) -> tuple[str, int] | None:
    """An indexed passage as its file holds it now, at the line it was indexed at (the index's own cut numbers it
    exactly: CHUNKER), as many lines as it was embedded with. None when the file no longer has it there (edited since:
    the next refresh embeds it again) or is gone; never a guess at where it moved."""
    found = _passage_span(path, line, text)
    return found[:2] if found else None


def _passage_span(path: str, line: int, text: str) -> tuple[str, int, int] | None:
    """_passage_now, with the last line of the file the passage runs to."""
    if life.source(path).get("unreadable"):
        return None
    lines = life._file_lines(path)
    if lines is None or not 0 < line <= len(lines):
        return None
    passage = text.strip().split("\n")
    if len(lines[line - 1]) > 2 * CHUNK:
        # The line may have many indexed pieces. Match the exact piece and retain
        # that bound when it is recalled; never expand it back to the whole line.
        return (text, line, line) if any(piece == text for _, piece in pieces(lines[line - 1])) else None
    if lines[line - 1].strip() != passage[0].strip():
        return None
    end = min(line - 1 + len(passage), len(lines))
    last = end
    while last >= line and not lines[last - 1].strip():
        last -= 1
    # A chunk can end on a heading while its body starts in the next chunk. Bring the same
    # section context as word search, before nearest() applies changes to the original lines.
    if context := life.heading_context(lines, last):
        end = max(end, context[-1][0])
    return "\n".join(lines[line - 1:end]), line, end


def _stale() -> bool:
    """Whether the index on disk was cut another way (CHUNKER) and is waiting to be built again."""
    try:
        db = _open()
        try:
            return (db.execute("SELECT value FROM meta WHERE key='chunker'").fetchone() or [""])[0] != CHUNKER
        finally:
            db.close()
    except sqlite3.Error:
        return False


def shown(path: str, line: int, text: str, room: int) -> str:
    """A passage found by meaning as she is shown it: the section it starts under (heard nearby is never shown as his),
    then its lines within `room`, each correction and mark whole (core/life.whole_lines)."""
    if room <= 0:
        return ""
    head = life.section_at(life._file_lines(path) or [], line, path)
    rendered = life.labelled(life.whole_lines(text, room), head, room)
    return rendered if len(rendered) <= room else ""


NOTE_WAIT = float(os.environ.get("MEMORY_NOTE_WAIT", "3"))  # s: the whole per-turn note, at most (then none)
_turns = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory-turn")  # (its own: never behind deep work)


def per_turn(text: str, limit_chars: int = 700) -> tuple[str, list[str]]:
    """This turn's memory note and the files it came from: the word match (core/life.related_hits) and the
    nearest passage by meaning from the same folders, in the space the word match had alone, each saying where it
    comes from. Her turn waits TURN_WAIT for the meaning search; if it has not answered by then the turn goes on
    with words only (the request itself finishes: never hung up at her wait), and the log says why.
    The whole note gets NOTE_WAIT: her reply never waits on it longer (nothing on her reply path
    waits unbounded); without it she answers from the conversation, and recall is still hers to call."""
    if limit_chars <= 0:
        return "", []
    work = _turns.submit(_per_turn, text, limit_chars)
    try:
        return work.result(timeout=NOTE_WAIT)
    except Exception:  # noqa: BLE001  (late, or failed: no note this turn, never a wait)
        logging.getLogger("viventium.memory").warning("the per-turn memory note gave way after %.1f s", NOTE_WAIT)
        return "", []


def _per_turn(text: str, limit_chars: int) -> tuple[str, list[str]]:
    began = time.monotonic()
    meaning = _pool.submit(nearest, text, 3, life.SEARCH_DIRS, TURN_ASK)
    try:
        words = life.related_hits(text)
    except life.Unreadable as e:
        return life.UNREADABLE_NOTE.format(why=e)[:limit_chars], []
    try:
        found = meaning.result(timeout=max(TURN_WAIT - (time.monotonic() - began), 0.01))
    except Exception as e:  # noqa: BLE001 (late, or Life unreadable: words only this turn)
        found = Near(answered=False, why=f"it did not answer within {TURN_WAIT:g} s" if isinstance(e, TimeoutError)
                     else f"it failed ({type(e).__name__})")
    if not answered(found) and found.why:
        logging.getLogger("viventium.memory").info("the per-turn search by meaning gave nothing: %s", found.why)
    near = [hit for hit in found if hit[0] >= NEAR]
    selected = list(words[:2])
    fresh = [hit for hit in near if hit[1] not in {path for path, _ in selected}]
    room = max(0, (limit_chars - 2) // 2)
    if fresh:  # one place for the nearest by meaning; the best word match keeps the other
        score, path, line, passage = fresh[0]
        selected = selected[:1] + [(path, shown(path, line, passage, room))]
    if len(selected) == 1:
        room = limit_chars
    blocks, named = [], []
    for path, lines in selected:
        if block := life.note_block(path, lines, room):
            blocks.append(block)
            named.append(path)
    return "\n\n".join(blocks), named


def related(text: str, limit_chars: int = 700) -> str:
    return per_turn(text, limit_chars)[0]


def deep(talk: list[tuple[str, str]], seen: tuple[str, ...] = (), limit: int = 5, each: int = 900) -> Near:
    """Deep Memory's candidates: what in Life is nearest in meaning to the last few turns (role, words), each message
    on its own (talk_parts; a long one in parts: nearest), beyond the files she was already shown. Up to `limit` passages, the
    closest first, one per file, each starting with where it comes from and when. Candidates only: the cortex decides
    which of them bear on the talk. Not answered (Near) when its search could not run, with why: never "nothing
    found". One pass, as nearest."""
    with life.one_pass():
        return _deep(talk, seen, limit, each)


def talk_parts(talk: list[tuple[str, str]]) -> list[str]:
    """What Deep memory searches with: each of the last four messages on its own (a long one in parts: nearest), the
    closest of them scoring a passage. Joined into one query, older messages can outweigh the newest words: on a real
    request the earlier find came sixth of the five passages kept, and second with each message on its own. (Each line
    on its own as well ranked it second too, but asked the embedding server for twice the text: on a slower Mac, past
    its wait.)"""
    return list(dict.fromkeys(words.strip() for _, words in talk[-4:] if words.strip()))


def _deep(talk: list[tuple[str, str]], seen: tuple[str, ...], limit: int, each: int) -> Near:
    try:  # (the talk comes from her conversation as it stands: by row, where it is kept; never by its words here)
        near = nearest(talk_parts(talk), k=12)
    except life.Unreadable as e:
        return Near(answered=False, why=f"Life could not be read ({e})")
    if not near.answered:
        return Near(answered=False, why=near.why)
    found, files = [], set(seen)
    for score, path, line, text in near:
        if score < DEEP_NEAR or path in files:
            continue
        where = life.cite(path, her=True)
        if each <= len(where) + 3:
            continue
        body = shown(path, line, text, each - len(where) - 3)
        if not body:
            continue
        files.add(path)
        found.append({"path": path, "line": line, "source": where,
                      "text": f"({where}) " + body, "score": round(score, 3)})
        if len(found) == limit:
            break
    return Near(found)


def search(words: str, only: tuple[str, ...] = ()) -> str:
    """The recall tool: the word search over all of Life (core/life.search), or only the folders his words limit it to,
    then the nearest passages by meaning from files it did not already show, each with where it comes from and when.
    She asked for it, so she reads and judges the result; what it could not search is said, never taken as "nothing
    there"."""
    try:
        within = life.folders_named(only) if only else ()
    except OSError:
        return life.search_notice({"Life could not be listed"}, False)
    if only and not within:
        return f"There is no folder called {', '.join(only)} in their Life: nothing was searched."
    with life.one_pass():  # (one recall: the change list, the record and each summary read once)
        return _search(words, within)


def _search(words: str, within: tuple[str, ...]) -> str:
    issues: set[str] = set()
    try:
        hits, matched = life.search_hits(words, only=within, issues=issues)
        seen = {hit["path"] for hit in hits}
        meaning = nearest(words, k=6, under=within, timeout=2.0)
        near = [hit for hit in meaning if hit[1] not in seen][:3]
    except life.Unreadable as e:
        return life.UNREADABLE_NOTE.format(why=e)
    why = "" if answered(meaning) else getattr(meaning, "why", "")
    # Explicit recall has no caller's character limit: reserve enough room for
    # every source and its complete correction, unlike the automatic turn note.
    room = max(1800, sum(len(f"[{h['name']}] {h['source']}\n") +
                         sum(len(f"{n}: {line}") + 1 for n, line in h["lines"]) + 2 for h in hits))
    by_word = life.render(hits, matched, limit_chars=room) if life.life() and life._keywords(words) else life.search(words)
    def recalled(path, line, text):
        label = life.section_at(life._file_lines(path) or [], line, path)
        room = max(MEANING_ROOM, len(text) + len(label) + 12) if life.FIX in text or life.FIX in label else MEANING_ROOM
        return shown(path, line, text, room)
    by_meaning = "\n\n".join(f"[{life.name_of(path)}] {life.cite(path, her=True)}\n{recalled(path, line, text)}"
                               for _, path, line, text in near)  # (a summary by its date and short id: life.name_of)
    notice = life.search_notice(issues, bool(hits))
    if notice:
        notice += "\n\n"
        if not hits:
            by_word = ""
    limit = ""
    if why:
        fallback = "" if issues else ": this is what the words alone found"
        limit = f"\n\n(Search by meaning is not available right now ({why}){fallback}.)"
    if not life.life():
        return by_word
    unanswered = (
        "If the results do not answer the question, tell the user about the search limit."
        if issues else
        "What it shows is what you have on it: when nothing here answers what they ask, say only that you do not have "
        "it, not where you looked, and never that a note or a conversation lacks it."
    )
    # (said with every result, whatever it holds: never a hint of a forget, and never a claim on his notes)
    head = ("From the user's Life memory" + (f", only {', '.join(within)}, as they asked" if within else "") + ". When you "
            "use something from it, say in a few words where and when it comes from (a past conversation and its date, "
            "their notes): never a file name aloud. Their own notes and their own words come first; a line under Heard "
            "nearby may be someone else's, and one under Assistant suggestions is only what Viventium said. "
            + unanswered + "\n\n")
    if not by_meaning:
        return (head if hits or issues else "") + (notice + by_word + limit).strip()
    if not hits:
        return head + notice + "Closest by meaning:\n\n" + by_meaning
    return head + notice + by_word + "\n\nAlso close by meaning:\n\n" + by_meaning


# -- What she keeps, shown and changed: one line in the change list (core/life.ledger) is all a change writes --

ORDER = {"core": 0, "saved": 1, "summary": 2, "sensitive": 3, "conversation": 4, "original": 5, "history": 6}


def _new_id() -> str:
    return "m" + secrets.token_hex(6)  # (random: two changes in one moment never share an id)


def _message(ref: str) -> tuple[dict | None, str]:
    """The message a look names: row:<n>:<digest>, checked against its original line. A direct row:<n> or
    said:<time> resolves once to a row and digest; a shared timestamp is refused.
    (message with its row, why not)."""
    rows = life.numbered()
    if ref.startswith("row:"):
        n, _, digest = ref[4:].partition(":")
        found = [row for row in rows if n.isdigit() and row["row"] == int(n)]
        if found and digest and found[0]["digest"] != digest:
            return None, "That message has changed since the look. Its reference is stale; look again."
    else:
        try:
            t = float(ref[5:])
        except ValueError:
            return None, f"{ref} is not a message a look showed."
        found = [row for row in rows if abs(float(row.get("t") or 0) - t) < 1e-6]
        if len(found) > 1:
            return None, (f"More than one message was said at {ref[5:]}: name the one meant by its row, as a look shows "
                          "it (row:<n>). Nothing was changed.")
    found = [row for row in found if row.get("role") in ("user", "assistant", "worker")]
    return (found[0], "") if found else (None, f"{ref} is not a message a look showed.")


def _passages(refs, shown: dict | None = None) -> tuple[list[dict], list[dict], str]:
    """The places a change is about, as recall or a look showed them: "People/Ilse.md:3" (a line of a Life file, kept
    with its words as they read now) or "row:<n>" (a message of the conversation, by its row in the record, kept with
    its words; "said:<time>" is resolved to its row once, now). shown: the
    mark of the line the page showed for each place (its id: core/life.line_mark): a place that no longer holds it is
    refused (a
    page left open while the file changed must never change the line that is there now).
    (passages, messages, why not)."""
    root = life.life()
    passages, messages = [], []
    for ref in refs or ():
        ref = str(ref).strip().strip("[]()").strip()
        if not ref:
            continue
        if ref.startswith(("said:", "row:")):
            row, why = _message(ref)
            if row is None:
                return [], [], why
            if shown is not None and ref in shown and shown[ref] != row["digest"]:
                return [], [], "That message has changed since the page showed it; look again."
            if not any(m["row"] == row["row"] for m in messages):
                messages.append({"row": row["row"], "digest": row["digest"], "text": str(row.get("text") or "")})
            continue
        asked, _, number = ref.rpartition(":")
        rel = life.file_named(asked) or asked  # (a summary, by the name recall gives it: its date and short id)
        if not rel or not number.isdigit() or ".." in rel or rel.startswith("/") or not root:
            return [], [], f'"{ref}" is not a place recall showed: give the file and the line, like People/Ilse.md:3.'
        try:
            lines = (root / rel).read_text(errors="replace").split("\n")
        except OSError:
            return [], [], f"There is no {asked} in their Life."
        if not 1 <= int(number) <= len(lines) or not lines[int(number) - 1].strip():
            return [], [], f"{asked} has no line {number} with words on it."
        if shown is not None and ref in shown and shown[ref] != life.line_mark(lines[int(number) - 1]):
            return [], [], ("That line has changed since the page showed it: nothing was changed. Look again, and act "
                            "on what it says now.")
        if rel == f"Views/{life.CORE_NAME}" and life.core_title(lines[int(number) - 1]):
            return [], [], "That is a title of what is kept in mind, not something it keeps: nothing was changed."
        twins = [n for n, line in enumerate(lines, 1) if life._same(line, lines[int(number) - 1])]
        # (a line kept in mind says the section it is under: the one written again for it, wherever it moves)
        section = life._section_of(lines, int(number)) if rel == f"Views/{life.CORE_NAME}" else ""
        passages.append({"path": rel, "line": int(number), "text": lines[int(number) - 1],
                         "nth": twins.index(int(number)) + 1, "of": len(twins),  # (identical lines are separate places)
                         **({"section": section} if section else {})})
    return passages, messages, ""


def _place(root: Path, rel: str, line: int | None = None) -> dict:
    found = life.source(rel, root)
    return {"path": rel, "line": line, "kind": found["kind"], "source": life.cite(rel, root), "date": found["date"]}


_TURN: contextvars.ContextVar = contextvars.ContextVar("memory_turn", default=None)


def within_turn(turn, fn, *args):
    """fn(*args) as a change made for her tool: its write begins before the tool gives way, or never (core/life.Turn)."""
    token = _TURN.set(turn)
    try:
        return fn(*args)
    finally:
        _TURN.reset(token)


def _key(change: dict) -> tuple:
    """What a change is, without its id or time: the same change asked again is the same key."""
    refs = lambda name: tuple((r.get("row"), r.get("digest")) for r in change.get(name, []))  # noqa: E731
    return (change.get("kind"), change.get("said"), change.get("words"), change.get("file"), change.get("replaces"),
            tuple((p.get("path"), p.get("line"), p.get("text")) for p in change.get("passages", [])),
            refs("messages"), refs("rows"))


def _keep(entry: dict) -> dict:
    """The change, kept: its one line in the change list, written whole or not at all (core/life.record_change), under
    the list's lock. The same change already in force is not written twice (three tries left three
    identical forgets, and one "put it back" left it forgotten). When the disk did not confirm a line written, it may
    have been kept: said so, never "nothing was changed"; when its tool gave way before it was written, it never is."""
    try:
        with life.change_lock():
            if entry.get("kind") in ("forget", "correct"):
                same = next((c for c in life.in_force() if _key(c) == _key(entry)), None)
                if same is not None:
                    return {"ok": True, "already": True, **same}
            # Keep non-content source coordinates with identity, so a later restore can
            # retire legacy prose even if its original row is no longer in the record.
            rows = life.record_rows()
            sources = []
            for ref in entry.get("messages", []) + entry.get("rows", []):
                if life.matches(ref):
                    row = rows[ref["row"] - 1]
                    sources.append({"row": ref["row"], "digest": ref["digest"],
                                    "call": row.get("call_id", ""), "t": row.get("t", 0)})
            if sources:
                entry["sources"] = sources
            life.record_change(entry, _TURN.get())
    except life.TooLate:
        return {"ok": False, "late": True, "why": "Nothing was changed: their memory was too slow just now"}
    except life.Unconfirmed as e:
        return {"ok": False, "maybe": True, "id": entry["id"],
                "why": f"It may have been kept ({e}): look at the changes to see whether it is there."}
    except life.Unreadable as e:
        return {"ok": False, "why": f"Nothing was changed: {e}."}
    except OSError as e:
        return {"ok": False, "why": f"It could not be kept ({e.strerror or e}): nothing was changed."}
    return {"ok": True, **entry}


def _carry(passages: list[dict]) -> dict:
    """A change on a summary's lines is carried onto the messages that summary stands for: when that
    conversation is written again (a retired older summary's rebuild, one of hers written again), the writer is given
    those messages with its words left out or corrected, and every reader of the new summary applies it by its words,
    as on the old one (core/life.summary_input, _names). {"carry": [{row, digest}]} or {}."""
    refs, seen = [], set()
    for p in passages:
        if life.kind_of(p.get("path", "")) == "summary":
            for ref in life.summary_stretch(p["path"]):
                if ref["row"] not in seen:
                    seen.add(ref["row"])
                    refs.append(ref)
    return {"carry": refs} if refs else {}


def _quietly(fn, *args) -> list:
    """What else to offer after a change is kept: empty when it cannot be found now (a search that gave way), never an
    error after the write (the change was kept, and she was told it failed)."""
    try:
        return fn(*args)
    except life.Unreadable:
        return []


FROM_MOST = 6  # messages a forget of a summary's line offers as where it may have come from


def _came_from(passages: list[dict], messages: list[dict], words: str, also: list[dict]) -> list[dict]:
    """A change on a summary's lines, naming no message: the messages of that conversation it may have come from, as a
    look shows them, the ones sharing most words with the line or the change first (the line's words
    are the summary's, not his, so the message that said it stayed, and came back when the conversation was written
    again). For her to name too, in the same turn; never applied by themselves. A few, never one already offered."""
    if messages:
        return []
    lines = [p["text"] for p in passages if life.kind_of(p.get("path", "")) == "summary"]
    if not lines:
        return []
    record, seen = life.record_rows(), {i["id"] for i in also}
    rows = [{**record[ref["row"] - 1], "row": ref["row"]} for p in passages if life.kind_of(p.get("path", "")) == "summary"
            for ref in life.summary_stretch(p["path"]) if 0 < ref["row"] <= len(record) and record[ref["row"] - 1]]
    if any(i["kind"] == "conversation" and int(i["id"].split(":")[1]) in {r["row"] for r in rows} for i in also):
        return []  # (a message of it holds those very words: already offered, as also holding them)
    words_of = set(life._keywords(" ".join(lines) + " " + (words or "")))
    look = [item for item in _conversation(sorted({r["row"]: r for r in rows}.values(), key=lambda r: r["row"]))
            if item["id"] not in seen]
    def shared(item: dict) -> int:
        return len(words_of & set(life._keywords(item["text"])))
    return sorted(look, key=lambda item: (-shared(item), int(item["id"].split(":")[1])))[:FROM_MOST]


def _also(words: str, passages: list[dict], messages: list[dict], now, *, issues: set[str]) -> list[dict]:
    """Other places that hold these words and the change does not name: for her to judge (name them too if they are
    about the same thing): lines of Life, and messages of the conversation (row:<n>). Never applied by
    themselves."""
    if not words:
        return []
    named = {(p["path"], p["line"]) for p in passages}
    said = {f"row:{m['row']}:{m['digest']}" for m in messages}
    found = [i for i in inspect(words, limit=16, now=now, issues=issues)
             if not i.get("unreadable") and life.holds(i["text"], words)
             and ((i["path"], i["line"]) not in named if i["kind"] != "conversation" else i["id"] not in said)]
    return [i for i in found if not i.get("now")][:5] + [i for i in found if i.get("now")][:3]


def _after_change(done: dict, old: str, about: str, passages: list[dict], messages: list[dict], now) -> dict:
    if done["ok"]:
        issues: set[str] = set()
        try:
            also = _also(old, passages, messages, now, issues=issues)
        except life.Unreadable as e:
            also = []
            issues.add(str(e))
        done["also"] = also
        done["from"] = _quietly(_came_from, passages, messages, about, also)
        if warning := life.search_notice(issues, bool(also)):
            done["warning"] = warning
    return done


STILL_LINES, STILL_SAID = 6, 8  # what the memory page offers after a forget: lines of Life, and messages
STILL_WAIT = float(os.environ.get("MEMORY_STILL_WAIT", "6"))  # s: her quick helper's look at what is offered, at most


def still_kept(what: str, named=(), *, issues: set[str] | None = None) -> list[dict]:
    """Every other place her memory still keeps that holds what was just forgotten, for the memory page to offer, one
    click each, with the same receipt and Undo: lines of Life (her standing view, his notes, summaries,
    sensitive files, originals and history: her own search reads them all), then what was said in conversation, the
    messages a new conversation picks up first (relationship.recent: before, the page never offered a message, and
    her own call opener, carried into the next chat, told her a forgotten plan existed). Found by the word match and
    the search by meaning; then her quick helper reads them and leaves out those that say nothing of it (before,
    a title, a heading and a Worker's note on another page were offered, each sharing only a word). A place that
    holds those very words is never left out, and when no helper can read them, the search's places are offered
    (which of them is the same thing is then his to judge). Raises life.Unreadable."""
    from core import helpers, relationship
    named = {_named_place(ref) for ref in named}
    judged = helpers.available()  # (with a judge, every line of a passage found by meaning is put to it: inspect)
    # (never a summary that cannot be read: nothing of it reaches her, so it keeps nothing of it)
    found = [i for i in inspect(what, whole=judged, issues=issues) if i["id"] not in named and not i.get("now")
             and i["kind"] != "other" and not i.get("unreadable")]
    carried = {row["row"] for row in life.numbered()[-relationship.RECENT_MESSAGES:]}
    said = {i["id"]: i for i in found if i["kind"] == "conversation"}
    # (the carried messages are looked at whole, never only within the look's newest few that hold a word)
    for item in _said_words(life._keywords(what), rows=carried):
        if item["id"] not in named:
            said.setdefault(item["id"], item)
    messages = sorted(said.values(), key=lambda i: (int(i["id"].split(":")[1]) not in carried, -i["score"],
                                                    -int(i["id"].split(":")[1])))
    lines = [i for i in found if i["kind"] != "conversation" and not i.get("also")]
    also, fixes = [i for i in found if i.get("also")], _corrections_on(what)
    if judged:  # (twice the room each, so a place that says nothing of it never takes the room of one that does)
        put = (fixes, lines[:2 * STILL_LINES], also[:2 * STILL_LINES], messages[:2 * STILL_SAID])
        nothing = _says_nothing(what, [i for group in put for i in group])
        if nothing is not None:  # (every place it reads as holding it, all of them: none may drop out of the forget)
            kept = [[{k: v for k, v in i.items() if k != "also"} for i in group if i["id"] not in nothing] for group in put]
            return kept[0] + sorted(kept[1] + kept[2], key=lambda i: -i["score"]) + kept[3]
    # (no helper read them: the search's own places, each passage by its one line, as many as before)
    return fixes + lines[:STILL_LINES] + messages[:STILL_SAID]


def _named_place(ref) -> str:
    """A place as the page names it (life.name_of): a summary's line named by its file is the same place."""
    ref = str(ref).strip()
    rel, _, number = ref.rpartition(":")
    if number.isdigit() and life.kind_of(rel) == "summary":
        return f"{life.name_of(rel)}:{number}"
    return ref


# What her quick helper is asked about the places a forget's search found (core/helpers.py: on this Mac on every
# profile here, since the page's own process holds no online key; listed in brain/prompts/ledger.json).
STILL_ASK = ("The user asked Viventium, their AI companion, to forget something. A search then found the places below "
             "in what Viventium keeps: each may say it, or may only share a word with it. Which of them say nothing of "
             "what was forgotten, in any words: not it, not a part of it, not an earlier or another version of the same "
             "thing? A title or a heading that names something else, or a note on another subject, says nothing of it. "
             "When unsure, a place says something of it. Answer with one JSON object and nothing else: "
             '{"nothing": [the numbers of the places that say nothing of it]}')


JUDGE_ROOM = 1500  # characters of one place her helper reads; a longer one is never left out (it may hold it further on)


def _whole(item: dict) -> str:
    """A place as her helper reads it, whole as it stands now (the page shows its first 400 characters): a message by
    its row (a Worker's result in plain words), a line of Life by its place."""
    if item.get("kind") == "conversation" and str(item.get("id", "")).startswith("row:"):
        n, rows = int(item["id"].split(":")[1]), life.record_rows()
        if 0 < n <= len(rows) and rows[n - 1]:
            text = life.row_now(n, str(rows[n - 1].get("text") or ""))
            return work_words(text) if rows[n - 1].get("role") == "worker" else text
    elif item.get("path") and item.get("line"):
        every = life._file_lines(item["path"]) or []
        if 0 < item["line"] <= len(every):
            now = life.current(every[item["line"] - 1], 0.0, None, item["path"], first=item["line"]).strip()
            return life.LEAD.sub("", now, count=1).strip() or now
    return str(item.get("text", ""))


def _says_nothing(what: str, places: list[dict]) -> set[str] | None:
    """The ids of the places her quick helper reads as saying nothing of what was forgotten, each read whole up to
    JUDGE_ROOM; never one that holds those very words, nor one longer than that. None when no helper answered, or its
    answer cannot be read: then every place found is offered."""
    from core import helpers
    if not places:
        return set()
    with life.one_pass():
        whole = [_whole(p) or p.get("text", "") for p in places]
    listed = "\n".join(f"[{n}] ({p.get('source', '')}) {life.cut(' '.join(text.split()), JUDGE_ROOM)}"
                        for n, (p, text) in enumerate(zip(places, whole), 1))
    began = time.monotonic()
    try:
        answer = helpers.ask([{"role": "system", "content": STILL_ASK},
                              {"role": "user", "content": f"What the user asked Viventium to forget:\n{what}\n\n"
                                                          f"The places the search found:\n{listed}"}],
                             max_tokens=200, wait=STILL_WAIT, json_out=True)
    except Exception:  # noqa: BLE001  (no answer: every place is offered)
        return None
    said = helpers.json_object(answer.text)
    numbers = said.get("nothing") if isinstance(said, dict) else None
    if not isinstance(numbers, list):
        logging.getLogger("viventium.memory").info("still kept: no reading of %d places (%s)", len(places),
                                                   answer.route or "no helper answered")
        return None
    out = {places[n - 1]["id"] for n in numbers if isinstance(n, int) and not isinstance(n, bool)
           and 0 < n <= len(places) and len(whole[n - 1]) <= JUDGE_ROOM and not life.holds(whole[n - 1], what.strip())}
    logging.getLogger("viventium.memory").info("still kept: %s read %d places in %.1f s, %d say nothing of it",
                                               answer.route, len(places), time.monotonic() - began, len(out))
    return out


STILL_CORRECTIONS = 3


def _corrections_on(what: str) -> list[dict]:
    """The corrections her standing note says in words (life.corrections_told) that share a word with what was just
    forgotten: in every conversation she is told each one, so a fact he forgot that a correction holds is still kept
    there (a correction written into what is kept in mind, then that line forgotten). Offered with
    their Undo, first (they reach her in every conversation). Retrieval only: his to judge."""
    words = set(life._keywords(what))
    if not words:
        return []
    out = []
    for c in life.corrections_told():
        shared = words & set(life._keywords(f'{c.get("said", "")} {c.get("words", "")}'))
        if shared:
            day = time.strftime("%-d %b %Y", time.localtime(float(c["at"])))
            out.append({"id": f"change:{c['id']}", "kind": "correction", "change": c["id"], "path": "", "line": None,
                        "text": f'Corrected: {c.get("said", "")}', "source": f"your correction, {day}",
                        "date": time.strftime("%Y-%m-%d", time.localtime(float(c["at"]))),
                        "score": round(len(shared) / len(words), 3)})
    return sorted(out, key=lambda i: -i["score"])[:STILL_CORRECTIONS]


def _look_first(about: str, what: str, now=()) -> dict:
    """No place named: nothing is kept ("Kept" was said while recall still gave both lines). The
    places that hold it, as a look gives them, for her to name and call again."""
    issues: set[str] = set()
    try:  # (never a summary that cannot be read: its reason can be a change of his, and it is no place to name)
        found = [item for item in inspect(about, limit=40, now=now, issues=issues) if not item.get("unreadable")]
    except life.Unreadable as e:
        return {"ok": False, "why": f"Nothing was changed: {e}."}
    # His own words of this turn are offered last, never left out: when nothing else holds them they are
    # the place ("My card PIN is 4411. Actually, forget that I told you my PIN."); his request alone is never all that is
    # offered while an earlier message holds the words (the bakery's opening date).
    earlier = [i for i in found if not i.get("now")]
    held = [i for i in earlier if life.holds(i["text"], about)] or earlier
    # Lines of Life and what was said, both: "what I said about it" is a message, and lines (ranked first) had pushed
    # every message out of the look (on his mind: she named the summary's lines and never his message).
    places = ([i for i in held if i["kind"] != "conversation"][:6] + [i for i in held if i["kind"] == "conversation"][:4]
              + [i for i in found if i.get("now")][:3])
    warning = life.search_notice(issues, bool(places))
    why = "Nothing was kept. Try the search again." if warning else "No matching place was found. Nothing was kept."
    if places:
        why = ("Nothing was kept yet: name the places it is about, as these show them (the file and line, or "
               "the full row:<n>:<digest> for a message), and call again.")
    return {"ok": False, "look": places, "what": what, "why": why, **({"warning": warning} if warning else {})}


def correct(old: str, new: str, passages=(), by: str = "voice", call: str = "", replaces: str = "",
            shown: dict | None = None, now=()) -> dict:
    """From now on she goes by `new` (what he says is true, in his words): every reader shows it first on the passages
    it names (as recall or a look showed them), and every model told of his Life is told it. replaces: the id of an
    earlier correction it corrects again (its places are this one's too). With no linked places, a look comes back
    first and nothing is kept. His notes are not changed. {"ok", "id", ..., "also": other places holding the old words}."""
    old, new = (old or "").strip(), (new or "").strip()
    if len(new) < 2:
        return {"ok": False, "why": "Say what is true now, in their words."}
    if old and old == new:
        return {"ok": False, "why": "That is already what it says."}
    found, messages, why = _passages(passages, shown)
    if why:
        return {"ok": False, "why": why}
    if replaces:
        try:
            earlier = next((c for c in life.in_force() if c["id"] == replaces and c["kind"] == "correct"), None)
        except life.Unreadable as e:
            return {"ok": False, "why": f"Nothing was changed: {e}."}
        if earlier is None:
            return {"ok": False, "why": f"There is no correction {replaces} still in force to correct again."}
        found += [p for p in earlier.get("passages", []) if p not in found]
        messages += [m for m in earlier.get("messages", []) if m not in messages]
        old = old or earlier.get("words", "")
    if not found and not messages:
        return _look_first(old or new, new, now)
    done = _keep({"id": _new_id(), "at": time.time(), "kind": "correct", "said": new, "words": old, "passages": found,
                  "messages": messages, "by": by, "call": call, **({"replaces": replaces} if replaces else {}),
                  **_carry(found)})
    return _after_change(done, old, old or new, found, messages, now)


def forget(what: str, passages=(), by: str = "voice", call: str = "", shown: dict | None = None, now=()) -> dict:
    """Leave out the sentences of the passages it names that hold these words (the named line,
    when its words are not in it), and of the messages it names; a whole conversation when `what` is its summary's
    reference (Memory/Conversations/…). With no place named nothing is kept: a look comes back, for her to name the
    places. His notes are not changed: deleting from them is a separate request, for a Worker."""
    what = (what or "").strip()
    root = life.life()
    named = [str(p).strip().strip("[]()").strip() for p in passages or () if str(p).strip()]
    ref = _reference(root, what) if root else ""
    if root and not ref and (files := [(p, rel) for p in named if ":" not in p and (rel := _reference(root, p))]):
        # (the conversation given as its place, by its name or its file: the summary it is, never the name as a file;
        # the real model's first call after the names came in was this, and it raised)
        ref, named = files[0][1], [p for p in named if p != files[0][0]]
    if ref:
        return _forget_summary(root, ref, by, call, named, shown)
    if len(what) < 2:
        return {"ok": False, "why": "Say what not to bring up, in their words."}
    found, messages, why = _passages(passages, shown)
    if why:
        return {"ok": False, "why": why}
    if not found and not messages:
        return _look_first(what, what, now)
    done = _keep({"id": _new_id(), "at": time.time(), "kind": "forget", "said": what, "words": what, "passages": found,
                  "messages": messages, "by": by, "call": call, **_carry(found)})
    return _after_change(done, what, what, found, messages, now)


def _reference(root: Path, what: str) -> str:
    """The summary `what` names, as its place in Life: by its name (its date and short id, life.name_of, as recall and
    the memory page name it) or by its file. "" when it names none."""
    rel = what.split(":", 1)[0].strip()
    if named := life.file_named(rel):
        return named
    if rel.startswith("Memory/Conversations/") and rel.endswith(".md") and ".." not in rel and (root / rel).is_file():
        return rel
    return ""


def _span(meta: dict) -> dict | None:
    """The messages a summary was written from: its conversation and its first and last minute."""
    import datetime as dt
    call = life.summary_call(meta.get("source_ref", ""))
    exact = re.match(r"\s*([\d.]+) to ([\d.]+)\s*$", meta.get("span", ""))
    if exact and call:  # (a newer summary says exactly which messages it covers)
        return {"call": call, "from": float(exact.group(1)), "to": float(exact.group(2))}
    try:
        start = dt.datetime.strptime(meta["started"], "%Y-%m-%d %H:%M").timestamp()
        end = dt.datetime.strptime(meta["ended"], "%Y-%m-%d %H:%M").timestamp() + 60
    except (KeyError, ValueError):
        return None
    return {"call": call, "from": start, "to": end} if call else None


def _forget_summary(root: Path, rel: str, by: str, call: str = "", passages=(), shown: dict | None = None) -> dict:
    """A whole conversation: its summary stays in Life (Light's own file, never deleted) and is skipped by every reader;
    its messages, named once now by their recorded row identities, are not brought into a new conversation, the
    night, a Worker's brief, a part's conversation or a later summary; the standing view's rebuild and the night are told, so what was learned
    from it goes too. An older summary (main's: no row identity) cannot name its messages: a look comes back with
    them first, and the forget names them (_forget_older)."""
    path = root / rel
    text = path.read_text(errors="replace")
    title = text.split("\n", 1)[0].lstrip("# ").strip()
    head = life._summary_meta_text(text)
    if life._older(head) and "rows" not in head:
        return _forget_older(rel, head, title, passages, shown, by, call)
    try:
        meta = life._summary_meta(path)
    except (life.Unreadable, OSError) as e:
        return {"ok": False, "why": f"Nothing was changed: {e}."}
    span = _span(meta)
    if "row digests" in meta:
        try:
            rows = json.loads(meta["row digests"])
            if not isinstance(rows, list) or not all(life._row_ref(row) for row in rows):
                raise ValueError("invalid references")
        except (TypeError, ValueError):
            return {"ok": False, "why": "This summary's message references cannot be read. Nothing was changed."}
    else:
        return {"ok": False, "why": "This summary's message references have no digest and are stale. Nothing was changed."}
    if some := [p for p in passages or () if not str(p).startswith("all:")]:  # (only some of its messages: those alone)
        return _forget_some(rel, title, {ref["row"] for ref in rows}, some, shown, by, call)
    return _keep({"id": _new_id(), "at": time.time(), "kind": "forget", "said": f'the conversation "{title}"', "words": "",
                  "file": rel, "title": title, "span": span, "rows": rows, "passages": [], "messages": [],
                  "by": by, "call": call, "sha": hashlib.sha256(text.encode()).hexdigest()})


def _forget_older(rel: str, head: dict, title: str, passages, shown: dict | None, by: str, call: str) -> dict:
    """An older summary forgotten whole. Its file cannot say which messages it covers, so the first call
    is a look: that conversation's messages as the record keeps them now (core/life.older_stretch: its stated
    minutes), each by its row, and one reference for all of them together ("all:<mark>", a mark of exactly those
    references). The forget then names them, all of them at once by that reference, or some by their rows; it is
    refused when the conversation changed since the look. The change names the file (so the summary is retired and
    skipped) and exactly those rows (left out everywhere). Undo brings every one of them back."""
    try:
        look, every = _older_look(rel)
    except life.Unreadable as e:
        return {"ok": False, "why": f"Nothing was changed: {e}."}
    named = [str(p).strip() for p in passages or () if str(p).strip()]
    asked = {"ok": False, "conversation": rel, "title": title, "look": look, "all": every}
    if look and not named:
        return {**asked, "why": (
            f"This older summary does not name its messages, so nothing was changed yet. These are the {len(look)} "
            f'messages of that conversation ("{title}") as the record keeps them now. To forget the whole '
            f"conversation, call again with what {life.name_of(rel)} and passages {every}; to forget only some, name "
            "those (row:<n>:<digest>).")}
    if named == [every] or not (look or named) or (look and set(named) == {item["id"] for item in look}):
        # (all of it at once, or each of its messages named, or nothing of it left to name: the file never read again)
        # Every message of its stretch, those already forgotten one by one too: an undo of one of those never brings it
        # back into a rebuild of the conversation he forgot whole.
        rows = [{"row": row["row"], "digest": row["digest"]} for row in life.older_stretch(rel)
                if row.get("role") in ("user", "assistant", "worker")]
    elif any(p.startswith("all:") for p in named):
        return {**asked, "why": ("That conversation changed since the look, so nothing was changed: these are its "
                                 f"messages now; to forget all of them, passages {every}.")}
    else:  # (only some: those messages alone, never the conversation whole)
        return _forget_some(rel, title, {row["row"] for row in life.older_stretch(rel)}, named, shown, by, call)
    record = life.record_rows()
    times = [float(record[r["row"] - 1].get("t") or 0) for r in rows]
    try:
        call_of = (_span(head) or {}).get("call", "")
    except (TypeError, ValueError, OverflowError):
        call_of = ""
    return _keep({"id": _new_id(), "at": time.time(), "kind": "forget", "said": f'the conversation "{title}"', "words": "",
                  "file": rel, "title": title, "rows": rows, "passages": [], "messages": [], "by": by, "call": call,
                  "sha": hashlib.sha256(life._file_text(life.life() / rel).encode()).hexdigest(),
                  **({"span": {"call": call_of, "from": min(times), "to": max(times)}} if times else {})})


def _forget_some(rel: str, title: str, own: set[int], named, shown: dict | None, by: str, call: str) -> dict:
    """Some messages of one conversation, named with its summary: those messages alone are forgotten (left out
    everywhere; an older summary holding them is retired and written again without them), never the conversation
    whole. A message of another conversation, or a line of a file, is refused (one message named
    with day 1's file had hidden that whole conversation, and a row of day 3 was taken as day 1's)."""
    found, messages, why = _passages(named, shown)
    if why:
        return {"ok": False, "why": why}
    if found:
        return {"ok": False, "why": ("Name that conversation's messages, as its look gives them (row:<n>:<digest>), "
                                     "not lines of a file. Nothing was changed.")}
    if not messages or any(m["row"] not in own for m in messages):
        return {"ok": False, "why": (f'Name messages of that conversation ("{title}") only, as its look gives them; '
                                     f"{'one of those is not' if messages else 'nothing named is'} one of its messages. "
                                     "Nothing was changed.")}
    count = len(messages)
    done = _keep({"id": _new_id(), "at": time.time(), "kind": "forget",
                  "said": f"what was said in {count} message{'s' if count > 1 else ''} of that conversation ({title})",
                  "words": "", "passages": [], "messages": messages, "by": by, "call": call})
    if done.get("ok") and life._his(life.life() / rel):  # (his edit of her summary is his, never rewritten)
        done["lines"] = _quietly(_his_lines, rel, messages)
    return done


def _his_lines(rel: str, messages: list[dict]) -> list[dict]:
    """The lines of a summary he edited that share words with these messages (the message was forgotten,
    and his edit still said it, while she said "Kept"): for her to name too, as the lines of his notes."""
    words = set(life._keywords(" ".join(m.get("text", "") for m in messages)))
    every = life._file_lines(rel) or []
    hits = [(len(words & set(life._keywords(line))), n, line) for n, line in enumerate(every, 1)
            if line.strip() and not line.startswith(("#", "- **")) and words & set(life._keywords(line))]
    return [{"id": f"{life.name_of(rel)}:{n}", "path": rel, "line": n, "text": line.strip(), "source": life.cite(rel)}
            for _, n, line in sorted(hits, key=lambda h: (-h[0], h[1]))[:6]]


def _older_look(rel: str) -> tuple[list[dict], str]:
    """An older summary's conversation as a look shows it, and the one reference for all of its messages."""
    look = _conversation(life.older_stretch(rel))
    return look, "all:" + hashlib.sha256(",".join(item["id"] for item in look).encode()).hexdigest()[:16]


def older_look(what: str) -> dict | None:
    """The look an older summary's forget gives, without asking for the forget (the memory page shows it first; nothing
    is changed): {look, all, title}. None when `what` is not an older summary (one of hers is forgotten whole at
    once). Raises life.Unreadable."""
    root = life.life()
    rel = _reference(root, what) if root else ""
    if not rel:
        return None
    text = (root / rel).read_text(errors="replace")
    head = life._summary_meta_text(text)
    if not (life._older(head) and "rows" not in head):
        return None
    look, every = _older_look(rel)
    return {"look": look, "all": every, "title": text.split("\n", 1)[0].lstrip("# ").strip()}


def _conversation(rows: list[dict]) -> list[dict]:
    """A conversation's messages as a look shows them, oldest first: each as it stands now, by its row (one left out is
    not shown: it is already forgotten)."""
    changes, out = life.in_force(), []
    for row in rows:
        if row.get("role") not in ("user", "assistant", "worker"):
            continue
        text = life.row_now(row["row"], str(row.get("text") or ""), changes)
        if text.strip():
            out.append(_said(row, text, 1.0))
    return out


def undo(change_id: str = "", by: str = "voice", call: str = "") -> dict:
    """The change no longer holds (the newest still in force when no id is given): nothing to put back anywhere, since
    no change ever edited a file. Which change is chosen under the list's lock, with its write: a change still being
    written is waited for, never passed over for the one before it (a second "put it back" took the next
    change down, and the PIN came back)."""
    try:
        with life.change_lock():
            entry = next((c for c in reversed(life.in_force()) if c["id"] == change_id or not change_id), None)
            if entry is None:
                return {"ok": False, "why": "There is no change of that kind to undo."}
            done = _keep({"id": _new_id(), "at": time.time(), "kind": "undo", "of": entry["id"], "by": by, "call": call})
    except life.Unreadable as e:
        return {"ok": False, "why": f"Nothing was changed: {e}."}
    return {**done, "of": entry} if done["ok"] else done


def changes(limit: int = 30) -> list[dict]:
    """What was corrected and forgotten, newest first, each saying whether it still holds, and where the lines it
    names stand now: "moved" when one was edited since (it applies to the lines of that file holding its words),
    "gone" when one is no longer there at all. Raises life.Unreadable."""
    rows = life.ledger()
    undone = {r.get("of") for r in rows if r.get("kind") == "undo"}
    out = []
    for row in reversed(rows):
        if row.get("kind") not in ("correct", "forget"):
            continue
        out.append({"id": row["id"], "at": row["at"], "kind": row["kind"], "by": row.get("by", ""),
                    "said": row.get("said", ""), "words": row.get("words", ""), "title": row.get("title", ""),
                    "places": len(row.get("passages", [])) + len(row.get("messages", [])), "undone": row["id"] in undone,
                    "where": _standing_of(row)})
        if len(out) == limit:
            break
    return out


def _standing_of(change: dict) -> str:
    """Where a change's named lines stand now, said truly (an edited line was said to be gone while it
    showed again): "" all as named; "moved" one edited since, its words still in that file and applied there; "edited"
    one edited since so that its words are no longer in it: that line shows again, as it is now, and needs forgetting
    or correcting once more; "gone" one no longer there at all."""
    state = ""
    if any(not life.matches(ref) for ref in change.get("messages", []) + change.get("rows", [])):
        return "stale"
    for passage in change.get("passages", []):
        how, _ = life.placed(passage)
        if how == "exact":
            continue
        lines = life._file_lines(passage.get("path", "")) or []
        words = change.get("words", "")
        if how == "moved" and words and any(life.holds(line, words) for line in lines):
            state = state or "moved"
        elif how == "moved" and any(_alike(line, passage.get("text", "")) for line in lines):
            state = "edited" if state != "gone" else state
        else:
            return "gone"
    return state


def _alike(line: str, named: str) -> bool:
    """A line that is most of a named line's words (an edit of it, not a different note): for what the page says."""
    theirs = {w for w in re.findall(r"\w{3,}", named.casefold())}
    if not theirs:
        return False
    return len(theirs & set(re.findall(r"\w{3,}", line.casefold()))) / len(theirs) >= 0.6


def inspect(about: str, limit: int = 40, now=(), whole: bool = False, *, issues: set[str] | None = None) -> list[dict]:
    """Every place in her memory that bears on `about`, as it stands now, item by item: her standing view, saved
    notes, conversation summaries, sensitive files, then originals and what was said in conversation. Each item:
    {id (a place a change names: name:line for a line of a Life file, a summary named by its date and short id,
    life.name_of; row:<n>:<digest> for a message, its row in the record), kind, path (its place in Life), line,
    source, date, text, score}. The word match (every line holding a word of it) and the nearest by meaning; it reads,
    it never changes. A passage found by meaning is offered by its own lines, never by its title, a heading or a
    summary's bookkeeping ("Planning the autumn trip" and "Unresolved questions" were offered as places
    still keeping a fact): by its first line of words, unless the word match found a line of it already; whole: by
    every line of words in it (for a judge of which say it: still_kept). now: the rows of his own words in this turn
    (the request being made): each holding a word of it comes after everything else, marked "now", never left out
    ("My PIN is 4411. Actually, forget that." was refused as held nowhere)."""
    root = life.life()
    if not root or not about.strip():
        return []
    with life.one_pass():  # (a look reads the change list, the record and each summary once)
        return _inspect(root, about, limit, set(now), whole, issues)


def _worded(rel: str, number: int, line: str) -> bool:
    """A line that says something of its own: not empty, not a title or a heading (a passage's label), not a summary's
    bookkeeping, not an empty section's "none" (Light's summary format)."""
    bare = life.LEAD.sub("", line.strip(), count=1).strip()
    return bool(bare) and not life.HEADING.match(line) and not (life.kind_of(rel) == "core" and life.core_title(line)) \
        and not life.bookkeeping(rel, number, line) and bare.casefold() not in ("none", "none.") \
        and not line.startswith(("- **row digests:**", "- **rows:**"))


def _inspect(root: Path, about: str, limit: int, now: set[int], whole: bool = False,
             issues: set[str] | None = None) -> list[dict]:
    words, items, changes_now, also = life._keywords(about), {}, life.in_force(), set()
    gone = life.skipped(changes_now)
    if words:
        found = life.rg(["-i", "-n", "-w", "--no-ignore", "-g", "*.md", "-g", "*.txt", "--max-count", "40",
                         *[part for word in words for part in ("-e", word)], str(root)], issues=issues).splitlines()
        for raw in found:
            path, _, rest = raw.partition(":")
            number, _, text = rest.partition(":")
            if not number.isdigit():
                continue
            rel = str(Path(path).relative_to(root))
            low = text.casefold()
            score = sum(1 for w in words if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low)) / len(words)
            items[(rel, int(number))] = score
    for hit in nearest(about, k=8, timeout=2.0, spans=True):
        score, rel, line, end = hit[0], hit[1], hit[2], hit[4] if len(hit) > 4 else hit[2]
        if score < DEEP_NEAR:
            continue
        every = life._file_lines(rel) or []
        own = [n for n in range(line, min(end, len(every)) + 1) if _worded(rel, n, every[n - 1])]
        if not own:
            continue
        covered = any((rel, n) in items for n in own)  # (a line of it the words found stands for it)
        if not whole:
            if not covered:
                items[(rel, own[0])] = score
            continue
        for n in own:  # (every line of it; those beyond its one line above are "also": put to a judge, else not shown)
            if (rel, n) not in items:
                items[(rel, n)] = score
                if covered or n != own[0]:
                    also.add((rel, n))
    out = []
    for (rel, line), score in items.items():
        kind = life.kind_of(rel)
        if kind == "other" or rel in gone or life.superseded(rel):
            continue
        if issue := life.source(rel, root).get("unreadable"):
            out.append({"id": life.name_of(rel, root), **_place(root, rel), "text": f"This summary cannot be read: {issue}.",
                        "unreadable": issue, "score": round(score, 3)})
            continue
        every = life._file_lines(rel)
        if every is None:
            life._search_problem("a matching file could not be read", issues)
            continue
        if not 0 < line <= len(every):
            continue  # the line is no longer there
        raw = every[line - 1]  # the line as it is in the file now
        if kind == "core" and (life.core_title(raw) or life.HEADING.match(raw)):
            continue  # (a title of what is kept in mind is the runtime's, never a place to change)
        if life.bookkeeping(rel, line, raw) or raw.startswith(("- **row digests:**", "- **rows:**")):
            continue  # (a summary's own bookkeeping says nothing it keeps of him)
        text = life.current(raw, 0.0, changes_now, rel, first=line)
        if not text.strip():
            continue
        bare = life.LEAD.sub("", text.strip(), count=1).strip() or text.strip()  # (its words, without a list mark)
        place = _place(root, rel, line)
        if head := life.HEADING.match(raw):  # (a title or a heading its words found: said to be one, never alone)
            place["source"] = (("the title of " if len(head.group(1)) == 1 else "a heading in ")
                               + ("a " if kind == "summary" else "") + place["source"])
        out.append({"id": f"{life.name_of(rel, root)}:{line}", **place, "text": life.cut(bare, 400),
                    "mark": life.line_mark(raw), "score": round(score, 3), **({"also": True} if (rel, line) in also else {})})
    said = _said_words(words, now)
    out += [i for i in said if not i.get("now")][:10]
    out.sort(key=lambda i: (-i["score"], ORDER.get(i["kind"], 9), -(_stamp(i["date"]))))
    # (the lines "also" put to a judge never take the room of what a look gives: they come after it)
    return ([i for i in out if not i.get("also")][:limit] + [i for i in out if i.get("also")]
            + [i for i in said if i.get("now")])


def _stamp(date: str) -> float:
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(date).timestamp()
    except ValueError:
        return 0.0


def _said_words(words: list[str], now=(), rows: set[int] | None = None) -> list[dict]:
    """What was said in conversation that holds these words, newest first, as it stands now (never edited), each a place
    a change names by its row (row:<n>). His own words of this turn (`now`) come last, oldest first, marked "now":
    never counted against the others' room. rows: only these rows of the record, every one of them that holds a word
    (the messages a new conversation picks up: still_kept)."""
    if not words:
        return []
    out, mine, changes = [], [], life.in_force()
    first = min(now) if now else 0
    for row in reversed(life.numbered()):
        if rows is not None:
            if row["row"] not in rows:
                continue
        elif len(out) == 20 and (not now or row["row"] < first):
            break
        this_turn = row["row"] in now
        if row.get("role") not in ("user", "assistant", "worker") or (rows is None and len(out) == 20 and not this_turn):
            continue
        text = life.row_now(row["row"], str(row.get("text") or ""), changes)
        if not text.strip():
            continue
        if row.get("role") == "worker":  # (a Worker's result by its plain words: its own form never matches a word)
            text = work_words(text)
        score = sum(1 for w in words if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text.casefold())) / len(words)
        if not score:
            continue
        if this_turn:
            mine.append({**_said(row, text, score * 0.9), "now": True, "source": "you said it just now, in this very request"})
        else:
            out.append(_said(row, text, score * 0.9))
    return out + mine[::-1]


def _said(row: dict, text: str, score: float) -> dict:
    """One message as a look shows it: its full reference (row:<n>:<digest>), who said it, where and when, its words as
    they stand now; a Worker's result as a result of background work, in plain words (work_words)."""
    import datetime as dt
    who = {"user": "you said", "assistant": "Viventium said", "worker": "a result of background work"}.get(
        row.get("role"), "said")
    where = {"telegram": "on Telegram", "typed": "in the chat", "call": "on a call"}.get(row.get("channel"), "")
    when = dt.datetime.fromtimestamp(float(row.get("t") or 0))
    return {"id": f"row:{row['row']}:{row['digest']}", "mark": row["digest"], "kind": "conversation", "path": "",
            "line": None, "source": f"{who} {where}, {when:%-d %b %Y}".replace("  ", " "),
            "date": when.date().isoformat(), "score": round(score, 3),
            "text": life.cut(work_words(text) if row.get("role") == "worker" else text, 400)}


# A Worker's result as her record keeps it (brain/queen._result and Workers._failed write it): 'The background work for
# "<his request>" (job <id>) finished: <what it found>[ Files it made or changed, on this Mac: <paths> (a Worker cannot
# send anything to their chat).]', or "needs their answer to go on: …", "ended as <state>: …", "could not start (…).".
_WORK = re.compile(r'The background work for "(?P<asked>.*)" (?:\(job [^)]*\) )?(?P<how>finished: |needs their answer to '
                   r'go on: |ended as (?P<state>[\w-]+): |could not start\b)(?P<rest>.*)\Z', re.S)
_MADE = re.compile(r"\s*Files it made or changed, on this Mac: (?P<files>.*?) \(a Worker cannot send anything to their "
                   r"chat\)\.\s*\Z", re.S)
_LOCAL = re.compile(r"\[([^\]]*)\]\(https?://(?:127\.0\.0\.1|localhost)[:/][^)]*\)|https?://(?:127\.0\.0\.1|localhost)[:/]\S*")


def work_words(text: str) -> str:
    """A Worker's result in plain words, as the memory page and her looks show it: what was asked and what came of it,
    the names of the files it made, never its job id, an address on this Mac or a path ('The background
    work for "Summarize the page at http://127.0.0.1:8791/..." (job call_...) finished' was offered on his page)."""
    def plain(words: str) -> str:
        return " ".join(_LOCAL.sub(lambda m: m.group(1) or "", words).split())
    m = _WORK.match((text or "").strip())
    if not m:
        return plain(text or "")
    rest, files = m.group("rest"), []
    if made := _MADE.search(rest):
        files = [Path(f.strip()).name for f in made.group("files").split(",") if f.strip()]
        rest = rest[:made.start()]
    how = m.group("how")
    came = (f"Found: {plain(rest)}" if how.startswith("finished") else f"It asks: {plain(rest)}" if how.startswith("needs")
            else f"It ended as {m.group('state')}: {plain(rest)}" if m.group("state") else "It could not start.")
    return (f"Asked: “{plain(m.group('asked'))}”. {came}" + (f" It made {', '.join(files)}." if files else "")).strip()


LOOK_PAGE = 30  # messages of one conversation her look lists (a 240-turn call was 60,803 characters)


def told(receipt: dict) -> str:
    """A change's receipt as she reads it, to say in her own words: what she will do from now on, where it was noted,
    what else holds the same words, that their own notes are not changed, and how to undo."""
    def where(places: list[dict], most: int = 5) -> str:
        return "; ".join(f"{p['id']} ({life.theirs(p['source'])}): {p['text'][:160]}" if p.get("id") else
                         f"{life.theirs(life.cite(p['path']))} ({life.name_of(p['path'])}:{p['line']})"
                         for p in places[:most])  # (a summary by its date and short id, never its file: life.name_of)

    if receipt.get("conversation") and not receipt.get("ok"):  # (an older conversation's look: a page of its messages)
        look = receipt.get("look", [])
        more = (f"\n(The first {LOOK_PAGE} of its {len(look)} messages are shown; passages {receipt['all']} names every "
                "one of them.)" if len(look) > LOOK_PAGE else "")
        return receipt["why"] + "".join(f"\n- {p['id']} ({life.theirs(p['source'])}): {life.cut(p['text'], 160)}"
                                        for p in look[:LOOK_PAGE]) + more
    warning = f" {receipt['warning']}" if receipt.get("warning") else ""
    if receipt.get("look") is not None and not receipt.get("ok"):  # (every place of the look, for her to name)
        return receipt["why"] + (" Where it is: " + where(receipt["look"], len(receipt["look"])) + "."
                                 if receipt["look"] else "") + warning
    if not receipt.get("ok"):
        return receipt.get("why", "That could not be changed.")

    tail = (" Their own notes are not changed by this. Tell them in a few words what you will do from now on, and that "
            f'"put it back" undoes it. Change id {receipt["id"]}.')
    if "of" in receipt:  # an undo
        was = receipt["of"]
        if was["kind"] == "correct":
            return (f'Put back: you no longer go by "{was.get("said")}"; what was there before holds again. Tell them in '
                    "a few words.")
        return (f'Put back: you may bring up {was.get("said") if was.get("file") else chr(34) + was.get("said", "") + chr(34)} '
                "again. Tell them in a few words.")
    if receipt.get("file"):
        return (f'Kept: you will not bring up anything from the conversation "{receipt["title"]}" again. Its summary stays '
                "in their Life, and you no longer read it." + tail)
    if receipt.get("lines"):  # (some messages of a summary he edited: his edit still says it)
        return ("Noted for what was said in that message, but their own edited copy of that conversation's summary "
                "still says it, and is read as it is: it is not forgotten yet. Name its lines too, now, in another "
                f"forget with what and these places, before you tell them it is forgotten: {where(receipt['lines'])}.")
    if receipt.get("already"):
        tail = " It was already noted, the same way: nothing more was needed." + tail
    count = len(receipt["passages"]) + len(receipt.get("messages", []))
    named = (f" Noted on {count} place(s)" + (f": {where(receipt['passages'])}" if receipt["passages"] else "") + "."
             if count else "")
    also = (" Also holding those words, not named (name them too if they are about the same thing, with the change id "
            f"as replaces for a correction): {where(receipt['also'], len(receipt['also']))}." if receipt.get("also") else "")
    if receipt.get("from"):  # (a summary's line, in its own words: the message that said it is still there)
        also += (" That is a line of a summary of a conversation, in the summary's own words: the message it came from is "
                 "still in what was said, unchanged, and would be summarized again from. These may be it (name the ones "
                 "that said it too, now, by their full row:<n>:<digest>"
                 + (", with the change id as replaces" if receipt["kind"] == "correct" else "")
                 + f"): {where(receipt['from'], len(receipt['from']))}.")
    if receipt["kind"] == "correct":
        was = f' (instead of "{receipt["words"]}")' if receipt.get("words") else ""
        return f'Kept: from now on you go by "{receipt["said"]}"{was}.' + named + also + warning + tail
    return (f'Kept: leave out "{receipt["said"]}" at the named places.' + named + also + warning
            + " If they want it deleted from their own notes, that is a separate request, for a Worker (hand_off_to)."
            + tail)


def status() -> dict:
    """What her memory runs on now, each part with its own state (they fail on their own): the Life folder; the
    search by meaning (its index, its model); the conversation record and what a new conversation carries; the
    standing view and when it was written; the change list."""
    import datetime as dt
    import socket
    from urllib.parse import urlsplit
    from core import relationship
    root = life.life()
    core_file = root / "Views" / life.CORE_NAME if root else None
    try:
        record = len(life.record_rows())
    except OSError:
        record = 0
    parts = urlsplit(EMBED_URL)
    try:
        with socket.create_connection((parts.hostname or "127.0.0.1", parts.port or 80), timeout=0.3):
            model = True
    except OSError:
        model = False
    index = stats() if root else {"index": False}
    built = life.core_applied(core_file) if core_file and core_file.exists() else 0  # (whole, or a section since)
    return {"life": bool(root), "index": index, "meaning": bool(model and index.get("passages")), "model": model,
            "record": record, "carried": relationship.RECENT_MESSAGES,
            "core": dt.datetime.fromtimestamp(built).isoformat(timespec="minutes") if built else "",
            "core_due": bool(root and life.core_is_stale()) if built else False, **_list_state()}


def _list_state() -> dict:
    try:
        return {"changes": len([c for c in life.ledger() if c.get("kind") in ("correct", "forget")])}
    except life.Unreadable as e:
        return {"changes": 0, "unreadable": str(e)}


def stats() -> dict:
    if not INDEX.exists():
        return {"index": False}
    db = _open()
    out = {"files": db.execute("SELECT count(*) FROM files").fetchone()[0],
           "passages": db.execute("SELECT count(*) FROM chunks").fetchone()[0],
           "model": (db.execute("SELECT value FROM meta WHERE key='model'").fetchone() or [""])[0],
           "bytes": INDEX.stat().st_size}
    db.close()
    return out


if __name__ == "__main__":  # python -m core.memory refresh | stats | search "<query>"
    import sys
    if sys.argv[1] == "refresh":
        print(json.dumps(refresh()))
    elif sys.argv[1] == "stats":
        print(json.dumps(stats()))
    elif sys.argv[1] == "search":
        hits = nearest(" ".join(sys.argv[2:]), k=6)
        print("\n\n".join(f"[{path}:{line}] ({score:.2f})\n{text[:500]}" for score, path, line, text in hits)
              or "Nothing found by meaning. Is the index built (python -m core.memory refresh)?")
