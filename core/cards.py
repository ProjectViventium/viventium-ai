"""Plain prompt files with a few facts on top, and the small file that keeps what you changed.

What comes with Light is text anyone can read and edit (brain/subconscious/, brain/routines/): a short head of
`key: value` lines between two `---`, then the words. What you change on a page is kept in her state folder, one
JSON file per page, and only where it differs from what came with Light: a choice put back to the default leaves
the file, so a later improvement to a default reaches you.
"""
import json
import os
import tempfile
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / "brain"
YES = {"yes": True, "no": False}


def read(path: Path) -> tuple[dict, str]:
    """A file's head (its facts) and its body (its words)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text.strip()
    head, _, body = text[4:].partition("\n---\n")
    facts = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            value = value.strip()
            facts[key.strip()] = YES.get(value, value)
    return facts, body.strip()


def parts(body: str, names: tuple[str, ...]) -> dict:
    """The words under each `## Name` heading, by name in lower case with underscores."""
    out, name = {}, None
    wanted = {f"## {n}": n.lower().replace(" ", "_") for n in names}
    for line in body.splitlines():
        if line.strip() in wanted:
            name = wanted[line.strip()]
            out[name] = []
        elif name:
            out[name].append(line)
    return {n: "\n".join(lines).strip() for n, lines in out.items()}


def state_file(page: str) -> Path:
    return Path(os.environ.get("VX_STATE") or Path(__file__).resolve().parents[1] / "state") / f"{page}.json"


def kept(page: str) -> dict:
    try:
        saved = json.loads(state_file(page).read_text())
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def keep(page: str, change) -> dict:
    """Read, change and save in one step, whole or not at all (0600, like her other state)."""
    saved = kept(page)
    change(saved)
    path = state_file(page)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{page}-")
    with os.fdopen(fd, "w") as handle:
        json.dump(saved, handle, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return saved


def differing(default: dict, now: dict, fields: tuple[str, ...]) -> dict:
    """Only what was changed from what came with Light."""
    return {f: now[f] for f in fields if f in now and now[f] != default.get(f)}
