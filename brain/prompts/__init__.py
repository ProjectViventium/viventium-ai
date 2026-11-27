"""The prompt ledger (ledger.json beside this file): every text she is given, and the one in force for each.

A text ships as a file in brain/ (its front matter is metadata); a text you change is kept in state/prompts/, owner-only,
and is the one in force from her next turn (each reader asks here every time it builds what she is told). No
database, no history, no workbench (the requirement: the simplest possible version of a prompt workbench, its texts
saved in a file like a JSON and shown editable in Light's own page, and nothing more complex than that).

    text(id)               the text in force: yours when you changed it and it still passes check(), else the shipped
                           file's (a text of yours that no longer passes, cut short by hand, emptied, renamed inside or
                           of a shape an update changed, is set aside: never her silence)
    check(id, words)       why a text cannot be given to her (ValueError, in plain words), else nothing: a placeholder
                           its reader fills is kept (the entry's "fills"), format fields are only the ones its reader
                           gives (the entry's "format", read with Python's own format parser), a JSON text keeps its
                           shape with words in every place, and its real reader takes it (the capsule is built with it)
    save(id, words, expected=None)  yours, kept, when it passes check(); `expected` is the revision the editor started
                           from (refused when the text changed since); the text in force again writes nothing
    revision(id)           a fingerprint of the text in force
    entries()              the ledger as a page shows it: each prompt with its text in force, the shipped one, whether
                           it is yours, its revision, what its reader fills, and why a text of yours is set aside
    version()              changes whenever a text of yours is saved or removed (a conversation composes her
                           instructions again on it)
"""
import hashlib
import fcntl
import json
import os
import string
import threading
from contextvars import ContextVar
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAIN = HERE.parent
LEDGER = HERE / "ledger.json"
LIMIT = 20_000  # characters a text of yours may have (the longest shipped one is about 6,000)
_cache: list = [None, None]  # (the ledger file's mtime, its contents)
_trying: ContextVar[dict[str, str]] = ContextVar("prompt_check", default={})
_save_lock = threading.RLock()
_set_aside: dict[str, str] = {}  # a text of his that no longer passes check() -> why (read by entries())


def _ledger() -> dict:
    mtime = LEDGER.stat().st_mtime_ns
    if _cache[0] != mtime:
        _cache[:] = [mtime, json.loads(LEDGER.read_text(encoding="utf-8"))]
    return _cache[1]


def entry(prompt_id: str) -> dict:
    found = next((p for p in _ledger()["prompts"] if p["id"] == prompt_id), None)
    if found is None:
        raise ValueError(f"No prompt {prompt_id!r} in the ledger.")
    return found


def body(raw: str) -> str:
    """A prompt file's text without its front matter."""
    if raw.startswith("---\n") and "\n---\n" in raw[4:]:
        raw = raw[4:].split("\n---\n", 1)[1]
    return raw.strip()


def shipped(prompt_id: str) -> str:
    return body((BRAIN / f"{prompt_id}.md").read_text(encoding="utf-8"))


def _yours(prompt_id: str) -> Path:
    import core.state as state  # (read when asked: a test or a probe moves her state)
    return state.STATE_ROOT / "prompts" / f"{prompt_id}.md"


def text(prompt_id: str) -> str:
    """The text in force for this prompt: yours when there is one that still passes check(), else the one that ships."""
    if prompt_id in _trying.get():
        return _trying.get()[prompt_id]
    try:
        words = _yours(prompt_id).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        _set_aside.pop(prompt_id, None)
        return shipped(prompt_id)
    except (OSError, UnicodeError) as why:
        detail = "Saved text is not valid UTF-8" if isinstance(why, UnicodeError) else "Saved text could not be read"
        _set_aside[prompt_id] = f"{detail} ({type(why).__name__}). Using the shipped text."
        return shipped(prompt_id)
    try:
        if not entry(prompt_id).get("through_ledger"):
            raise ValueError("this text is not read through the ledger")
        check(prompt_id, words)
    except ValueError as why:
        _set_aside[prompt_id] = str(why)
        return shipped(prompt_id)
    _set_aside.pop(prompt_id, None)
    return words


def revision(prompt_id: str) -> str:
    return hashlib.sha256(text(prompt_id).encode()).hexdigest()[:12]


def _shape(value):
    """A JSON text's shape: its keys all the way down (the values are words, free to change)."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return type(value).__name__ if not isinstance(value, str) else "text"


def _filled(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _filled(item)
    else:
        yield bool(str(value).strip())


def _format_ok(words: str, allowed: list[str], where: str) -> None:
    """A text its reader passes to str.format: only the named fields it gives, plain (no position, attribute, index,
    conversion or format), and every other brace doubled. Read with Python's own parser, then formatted for real."""
    try:
        parsed = list(string.Formatter().parse(words))
    except ValueError:
        raise ValueError(f"A brace in {where} is not closed: write {{{{ or }}}} for a brace of its own.") from None
    for _, field, spec, conversion in parsed:
        if field is None:
            continue
        if field not in allowed or spec or conversion:
            allowed_said = ", ".join("{" + name + "}" for name in allowed)
            raise ValueError(f"{where} can be given only {allowed_said}: write {{{{ or }}}} for a brace of its own.")
    try:
        words.format(**{name: name for name in allowed})
    except (ValueError, KeyError, IndexError, AttributeError):
        raise ValueError(f"{where} cannot be filled in as it is.") from None


def check(prompt_id: str, words: str) -> None:
    """Why this text cannot be given to her, as a ValueError in plain words; nothing when it can."""
    found, words = entry(prompt_id), (words or "").strip()
    if not words:
        raise ValueError("That would leave this text empty.")
    if len(words) > LIMIT:
        raise ValueError(f"That is longer than {LIMIT:,} characters.")
    ships = shipped(prompt_id)
    for token in found.get("fills", []):
        if token in ships and token not in words:
            raise ValueError(f"Keep {token}: it is filled in each time this text is given.")
    try:
        shape = _shape(json.loads(ships))
    except ValueError:
        shape = None
    if shape is not None:
        try:
            mine = json.loads(words)
        except ValueError:
            raise ValueError("This text is JSON: keep it JSON, with the same names in the same places.") from None
        if _shape(mine) != shape or not all(_filled(mine)):
            raise ValueError("Keep the same names in the same places, each with words in it.")
        for key, allowed in found.get("format", {}).items():
            _format_ok(str(mine.get(key, "")), allowed, f'"{key}"')
    else:
        for key, allowed in found.get("format", {}).items():
            _format_ok(words, allowed, "This text")
    if reader := READERS.get(prompt_id):
        token = _trying.set({**_trying.get(), prompt_id: words})
        try:
            reader()
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001 (its real reader could not take it: never given to her)
            raise ValueError(f"This text could not be given as it is ({type(e).__name__}).") from None
        finally:
            _trying.reset(token)


def _capsule_reader() -> None:
    """The capsule built with this wording, as each turn builds it (every level of every band)."""
    import datetime as dt
    from brain import feelings_kernel as kernel
    now = dt.datetime.now(dt.timezone.utc)
    kernel.policy()
    for value in (0, 30, 50, 70, 100):
        text_now, _ = kernel.render_capsule(True, kernel.materialize({b.id: {"current": value} for b in kernel.BANDS}, now))
        if not text_now:
            raise ValueError("The feeling note would be empty with this text.")


def _manners_reader() -> None:
    """Each personality's note built with this wording."""
    from brain import feelings_kernel as kernel
    for profile in json.loads(text("prompts/feelings/personalities"))["manners"]:
        kernel.manner(profile)


READERS = {"prompts/feelings/capsule_policy": _capsule_reader, "prompts/feelings/personalities": _manners_reader}


def save(prompt_id: str, words: str, expected: str | None = None) -> str:
    """Keep your text for this prompt (in force from her next turn); nothing, or the shipped text, takes yours away.
    `expected`: the revision the editor started from; refused when the text in force changed since."""
    from core.state import private_file
    # One lock for validation, revision comparison and replacement, across threads and processes.
    with _save_lock, private_file(_yours(".save").with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _save(prompt_id, words, expected)


def _save(prompt_id: str, words: str, expected: str | None) -> str:
    found = entry(prompt_id)
    if not found.get("through_ledger"):
        raise ValueError(f"This one is changed on {found['edited_on']}." if found.get("edited_on") else
                         f"This one cannot be changed here yet: {found['reader']} does not read the ledger.")
    if expected is not None and expected != revision(prompt_id):
        raise ValueError("This text changed since you opened it: look at it again before you save.")
    words = (words or "").strip()
    ships, mine = shipped(prompt_id), _yours(prompt_id)
    if not words or words == ships:
        if mine.exists():
            mine.unlink()
            return "Back to the text that comes with Viventium."
        return "Unchanged."
    if words == text(prompt_id) and mine.exists():
        return "Unchanged."
    check(prompt_id, words)
    from core.state import private_file
    tmp = mine.with_name(f".{mine.name}.{os.getpid()}.tmp")
    with private_file(tmp, "w", encoding="utf-8") as f:
        f.write(words + "\n")
    os.replace(tmp, mine)
    return "Kept. She uses it from her next turn."


def entries() -> list[dict]:
    """The ledger as a page shows it, each prompt with its texts."""
    out = []
    for found in _ledger()["prompts"]:
        item = dict(found)
        path = BRAIN / f"{found['id']}.md"
        if path.is_file():
            ships = shipped(found["id"])
            now = text(found["id"]) if found.get("through_ledger") else ships
            item.update(text=now, shipped=ships, yours=now != ships, revision=hashlib.sha256(now.encode()).hexdigest()[:12],
                        file=str(path.relative_to(BRAIN.parent)), set_aside=_set_aside.get(found["id"], ""),
                        fills=[*found.get("fills", []), *("{" + name + "}" for names in found.get("format", {}).values()
                                                         for name in names)])
        out.append(item)
    return out


def version() -> str:
    """A fingerprint of the texts of yours: it changes whenever one is saved or removed."""
    import core.state as state
    folder = state.STATE_ROOT / "prompts"
    seen = []
    for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        try:
            st = path.stat()
            seen.append(f"{path.relative_to(folder)}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            seen.append(f"{path.relative_to(folder)}:unreadable")
    return hashlib.sha256("\n".join(seen).encode()).hexdigest()[:16]
