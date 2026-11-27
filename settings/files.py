"""The files you sent her, as the settings page lists them: what core/attachments.py keeps whole on this Mac, one
folder a day in her state's inbox (state/inbox/YYYY-MM-DD/<name>), newest first. Each stays 30 days; after that it is
removed, unless a job still open or your Life still names it (core/attachments.prune). You can remove one sooner here.

Only that inbox is ever read or changed: a file is named by its day and its name, and nothing outside the inbox, no
link and no folder can be removed through it. A backup never holds these files, only their place in the conversation.
"""
import datetime as dt
import re
from pathlib import Path

from settings import store

KEEP_DAYS = 30  # (core/attachments.KEEP_DAYS: the rule is said here, kept there)
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
SHOWN = 200  # the newest ones listed (the count says how many there are in all; the page says when it lists fewer)


def inbox() -> Path:
    return store.state_file().parent / "inbox"


def _size(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


def _kept() -> list[tuple[str, Path]]:
    """(day, file) for every file kept, newest day first, then by name. Links and folders are never listed."""
    try:
        days = sorted((d for d in inbox().iterdir() if d.is_dir() and not d.is_symlink() and DAY.fullmatch(d.name)), reverse=True)
    except OSError:
        return []
    found = []
    for day in days:
        try:
            found += [(day.name, f) for f in sorted(day.iterdir()) if f.is_file() and not f.is_symlink()]
        except OSError:
            continue
    return found


def listed(today: dt.date | None = None) -> dict:
    """What the page shows: the newest files with their size, the day each came and the day it goes; how many there are
    and how much room they take; and the rule, in words."""
    today = today or dt.date.today()
    rows, total, kept = [], 0, _kept()
    for day, file in kept:
        try:
            size = file.stat().st_size
        except OSError:
            continue
        total += size
        if len(rows) < SHOWN:
            came = dt.date.fromisoformat(day)
            goes = came + dt.timedelta(days=KEEP_DAYS)
            rows.append({"id": f"{day}/{file.name}", "name": file.name, "size": _size(size), "came": day,
                         "goes": goes.isoformat() if goes > today else ""})  # ("": past its 30 days, still in use)
    return {"files": rows, "count": len(kept), "size": _size(total) if kept else "", "days": KEEP_DAYS}


def remove(file_id: str) -> str:
    """Remove one file you sent, now. Returns "" or why not, in plain words. Only a file directly in a day's folder of
    the inbox: never a link, a folder, or anything outside it."""
    day, _, name = str(file_id).partition("/")
    if not DAY.fullmatch(day) or not name or "/" in name or name in (".", "..") or name.startswith("."):
        return "That file is not one you sent."
    folder = inbox() / day
    path = folder / name
    try:
        if folder.is_symlink() or not folder.is_dir() or path.is_symlink() or not path.is_file():
            return "That file is already gone."
        if path.resolve().parent != folder.resolve() or folder.resolve().parent != inbox().resolve():
            return "That file is not one you sent."
        path.unlink()
        if not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        return "It could not be removed."
    return ""
