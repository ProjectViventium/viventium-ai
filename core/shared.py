"""Programs Light shares with main Viventium on this Mac: the Codex and Claude CLIs its Workers run.

Light never changes them. A shared CLI's permissions can change under it (an execute permission lost,
0755 to 0600, breaks the other runtime until it is put back), and the cause may never be known. So `./vx up`, `setup`,
`test` and `test-sound` record their mode and file id (logs/shared-programs.txt, one "mode inode path"
line each) and say loudly if one changed; while Light runs, Telegram's clock checks every 20 s and logs
the first time it sees a change (logs/shared.log), so a change can be matched to what ran then. A
permission is never put back by Light (that would change another runtime's programs).

    python3 core/shared.py      (standard library only: it runs before Light's own Python exists)
"""
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "logs" / "shared-programs.txt"
LOG = ROOT / "logs" / "shared.log"
NAMES = ("codex", "claude")
_seen: set[str] = set()


def now() -> list[str]:
    """ "mode inode path" for the real files behind the shared CLIs (on PATH and in ~/.local/bin)."""
    found = set()
    for name in NAMES:
        for candidate in (shutil.which(name), Path.home() / ".local" / "bin" / name):
            if candidate and Path(candidate).exists():
                found.add(os.path.realpath(candidate))
    lines = []
    for path in sorted(found):
        st = os.stat(path)
        lines.append(f"{st.st_mode & 0o7777:o} {st.st_ino} {path}")
    return lines


def changes() -> list[str]:
    """What changed since it was recorded: "was: …" and "now: …" lines ([] when nothing did)."""
    try:
        recorded = [line for line in RECORD.read_text().splitlines() if line.strip()]
    except OSError:
        return []
    current = now()
    return [f"was: {line}" for line in recorded if line not in current] + [f"now: {line}" for line in current if line not in recorded]


def check() -> list[str]:
    """Log a change the first time it is seen (never repairs it); returns it."""
    found = changes()
    if found and "\n".join(found) not in _seen:
        _seen.add("\n".join(found))
        from core.state import closed_file
        with closed_file(LOG, "a") as out:
            out.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} a shared program changed while Light ran (left as is):\n  "
                      + "\n  ".join(found) + "\n")
    return found


if __name__ == "__main__":
    found = changes()
    print("  shared programs: " + ("; ".join(found) if found else "unchanged"))
    sys.exit(1 if found else 0)
