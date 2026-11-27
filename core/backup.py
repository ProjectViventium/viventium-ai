"""./vx backup and ./vx restore: what makes this Viventium yours, copied out of the project and checked.

    python -m core.backup save               a new backup; prints where it is
    python -m core.backup list               the backups there are, newest first
    python -m core.backup restore [NAME] [--yes]   put one back (the newest, or by name); says first what changes

What is kept: the state folder (the conversation, what you are owed, reminders, Feelings, what the settings page
keeps, who Telegram answers) and your private profile lines (profiles/*.local.env), with the profile it last ran
and the connected bot's name.
What never is: your Life folder (it is yours and is read in place: back it up as you do your documents), the
Keychain (a key never leaves it), models, logs, and what is rebuilt from Life (state/memory: the index).

A backup is a dated folder under ~/Library/Application Support/Viventium Light/backups/ with a manifest of
every file's SHA-256. It is kept only if every copied file reads back identical to what was read; the last
KEEP are kept, with a separate KEEP for before-restore copies. Restore checks paths and hashes first,
saves what is there now, and leaves a durable marker until every file is back. The next start finishes
an interrupted restore, or rolls back to that safety copy. vx refuses to restore while Viventium is running.
"""
import datetime as dt
import fcntl
import functools
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home() / "Library" / "Application Support" / "Viventium Light" / "backups"
KEEP = 7
MANIFEST = "manifest.json"
# Inside state/: rebuilt from Life or only about this moment, so never kept. Files he sent (inbox) stay only on this
# Mac, for 30 days (core/attachments.py); a backup keeps their references in the conversation, never the files.
SKIP_FOLDERS = ("memory", "installs", "inbox")
# ...and what must not come back from a backup: Sleep's and Dreaming's own copies of his Life (N, state/core/night-copies:
# made again each night), and the phone's keys (state/core/phone: a restore makes the phone pair again, G).
SKIP_PATHS = ("core/night-copies/", "core/phone/root.key", "core/phone/doors.key", "core/call-live.d/")  # (and who holds a call)
SKIP_NAMES = ("call-live",)
SKIP_ENDINGS = (".lock", ".tmp")
ALSO = ("logs/profile", "logs/telegram-bot.json")  # which profile it last ran; the connected bot's name
UNDO = "before-restore"  # the name a restore gives to what it saved first
RESTORING = "restore-in-progress.json"  # in logs/, outside the files a backup can replace


def home() -> Path:
    return Path(os.environ.get("VX_BACKUPS") or HOME)


def _base(root: Path, top: str) -> Path:
    if root.resolve() == ROOT.resolve() and top in ("state", "logs"):
        return Path(os.environ.get("VX_" + top.upper()) or root / top).absolute()
    return (root / top).absolute()


def _path(base: Path, rel: str) -> Path:
    """No links in the root or the path below it, including dangling links and hard-linked files."""
    at = base
    for part in (None, *rel.split("/")):
        at = at / part if part else at
        try:
            info = at.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise OSError(f"Restore refuses a link: {at}")
    return at


def _allowed(rel: str) -> bool:
    if not isinstance(rel, str) or "\\" in rel or "\0" in rel:
        return False
    parts = rel.split("/")
    if len(parts) < 2 or any(p in ("", ".", "..") for p in parts):
        return False
    top, *inside = parts
    if top == "state":
        where = "/".join(inside)
        return (inside[0] not in SKIP_FOLDERS and inside[-1] not in SKIP_NAMES
                and not inside[-1].endswith(SKIP_ENDINGS)
                and not any(where == skip or where.startswith(skip) for skip in SKIP_PATHS))
    return rel in ALSO or (top == "profiles" and len(inside) == 1 and inside[0].endswith(".local.env"))


def place(root: Path, rel: str) -> Path:
    """Where a kept file lives. Its name in a backup is always state/..., logs/... or profiles/...; state and logs are
    where this instance keeps them (VX_STATE, VX_LOGS: core/state.py), so a backup of an instance with its own state is
    of that state, never the checkout's (with VX_STATE set, a save kept the default state and said it worked)."""
    if not _allowed(rel) and rel != "state/":
        raise OSError(f"This backup names a file outside Light's backup scope: {rel}")
    top, _, rest = rel.partition("/")
    return _path(_base(root, top), rest)


def files(root: Path) -> list[str]:
    """Every file that is kept, as its name in a backup (state/..., profiles/..., logs/...). Links are never followed."""
    found = []
    state = place(root, "state/")
    for path in sorted(state.rglob("*")) if state.is_dir() else []:
        inside = path.relative_to(state).parts
        where = "/".join(inside)
        if (path.is_symlink() or not path.is_file() or inside[0] in SKIP_FOLDERS or path.name in SKIP_NAMES
                or path.name.endswith(SKIP_ENDINGS) or any(where == skip or where.startswith(skip) for skip in SKIP_PATHS)):
            continue
        found.append("state/" + where)
    profiles = _path(_base(root, "profiles"), "")
    found += ["profiles/" + p.name for p in sorted(profiles.glob("*.local.env")) if p.is_file() and not p.is_symlink()]
    found += [name for name in ALSO if place(root, name).is_file() and not place(root, name).is_symlink()]
    return found


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sync(folder: Path) -> None:
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _marker(root: Path) -> Path:
    """Keep legacy markers readable, but never adopt or overwrite another instance's marker."""
    base = _base(root, "logs")
    for found in sorted(base.glob("restore-in-progress*.json")):
        marker = _path(base, found.name)
        try:
            if _belongs(json.loads(marker.read_text())["roots"], root, state_only=True):
                return marker
        except (OSError, ValueError, KeyError, TypeError):
            return marker  # uncertain ownership: keep normal writers stopped
        else:
            from core.state import closed_file
            notice = _path(base, f"restore-foreign-{_identity(root)}-{digest(str(marker.resolve()).encode())[:16]}.noted")
            try:
                with closed_file(notice, "x"):
                    pass
            except FileExistsError:
                pass
            else:
                with closed_file(_path(base, "app.log"), "a") as log:
                    log.write("Ignored a restore marker for different state folders; left it untouched.\n")
    available = _path(base, RESTORING)
    n = 0
    while available.exists():
        n += 1
        available = _path(base, f"restore-in-progress-{_identity(root)}-{n}.json")
    return available


def pending(root: Path = ROOT) -> bool:
    return _marker(root).exists()


def _identity(root: Path) -> str:
    return digest(json.dumps(_roots(root), sort_keys=True).encode())[:16]


def problem(root: Path = ROOT) -> str:
    marker = _marker(root)
    if marker.exists():
        try:
            failure = json.loads(marker.read_text()).get("failure")
            if isinstance(failure, str) and failure:
                return failure
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    file = _path(_base(root, "logs"), "blocked")
    prefix = f"restore {_identity(root)} "
    text = file.read_text().strip() if file.exists() else ""
    return text[len(prefix):] if text.startswith(prefix) else ""


def _blocked(root: Path, error: Exception) -> None:
    from core.state import closed_file
    reason = str(error).replace("\n", " ").strip().rstrip(".")
    said = f"{reason}. Restore is incomplete; backup copies were kept. Choose another backup in Settings."
    marker = _marker(root)
    try:
        record = json.loads(marker.read_text())
        record["failure"] = said
    except (OSError, ValueError, TypeError):
        pass
    else:
        _record(root, record)  # failure belongs to this instance even if another shares logs/blocked
    with closed_file(_path(_base(root, "logs"), "blocked"), "w") as out:
        out.write(f"restore {_identity(root)} {said}\n")


def recovery_view(root: Path = ROOT) -> dict:
    """Read-only repair view. No profile, model, sign-in or normal state writer is needed."""
    waiting = pending(root)
    copies = []
    if waiting:
        for p in backups():
            if not damaged(p) and not _incomplete(p):
                copies.append({"name": p.name, "made": _when(p)})
    return {"pending": waiting,
            "reason": (problem(root) or "Restore is incomplete. Choose a backup to finish it.") if waiting else "",
            "backups": copies}


def _undo(folder: Path) -> bool:
    return folder.name.endswith(UNDO) or UNDO + "_" in folder.name


def _exclusive(action):
    """Serialize save, restore and startup recovery within this instance (not a shared backup bank)."""
    @functools.wraps(action)
    def run(root: Path = ROOT, *args, **kwargs):
        from core.state import closed_file
        lock = _path(_base(root, "logs"), RESTORING + ".lock")
        with closed_file(lock, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            return action(root, *args, **kwargs)
    return run


@_exclusive
def save(root: Path = ROOT, tag: str = "", *, protect: tuple[Path, ...] = ()) -> Path:
    """A new backup. Each file is read once, written, and read back: the copy must be what was read."""
    from core.state import closed_file
    marker = _marker(root)
    if marker.exists():
        # Keeping the current mixed state is a way out, not permission to start normal writers.
        try:
            record = json.loads(marker.read_text())
            protect = (*protect, Path(record["source"]), Path(record["before"]))
        except (ValueError, KeyError, TypeError):
            pass
        tag = tag or UNDO + "_incomplete"
    base = _path(home().absolute(), "")
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    name = stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S") + (f"_{tag}" if tag else "")
    for n in range(2, 100):  # (two in one second: the later one says so)
        if not (base / name).exists():
            break
        name = f"{stamp}_{n}"
    work = base / (name + ".partial")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(mode=0o700)
    listed = {}
    for rel in files(root):
        data = place(root, rel).read_bytes()
        copy = work / rel
        with closed_file(copy, "wb") as out:  # (0600, its folders 0700: core/state.py)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        if digest(copy.read_bytes()) != digest(data):
            shutil.rmtree(work, ignore_errors=True)
            raise OSError(f"The copy of {rel} did not read back the same. Nothing was kept; try again.")
        listed[rel] = {"sha256": digest(data), "bytes": len(data)}
    with closed_file(work / MANIFEST, "w") as out:
        out.write(json.dumps({"made": dt.datetime.now().isoformat(timespec="seconds"), "files": listed,
                              "incomplete": marker.exists()}, indent=1))
        out.flush()
        os.fsync(out.fileno())
    final = base / name
    work.rename(final)  # (whole, or not there)
    _sync(base)
    protected = {p.resolve() for p in (*protect, final)}
    for safety in (False, True):  # a safety copy never evicts a user's good backup
        pool = [p for p in backups() if _undo(p) == safety]
        eligible = [p for p in reversed(pool) if p.resolve() not in protected]
        for old in eligible[:max(0, len(pool) - KEEP)]:
            shutil.rmtree(old, ignore_errors=True)
    for left in base.glob("*.partial"):  # (a backup that was interrupted)
        if left.resolve() not in protected:
            shutil.rmtree(left, ignore_errors=True)
    return final


def backups() -> list[Path]:
    """Whole backups, newest first."""
    base = _path(home().absolute(), "")
    return sorted((p for p in base.iterdir() if not p.is_symlink() and not p.name.endswith(".partial")
                   and p.is_dir() and (p / MANIFEST).is_file()), reverse=True) if base.is_dir() else []


def manifest(folder: Path) -> dict:
    listed = json.loads(_path(folder, MANIFEST).read_text())["files"]
    if not isinstance(listed, dict):
        raise OSError("This backup's manifest is not a file list.")
    for rel, was in listed.items():
        if (not _allowed(rel) or not isinstance(was, dict) or not isinstance(was.get("sha256"), str)
                or len(was["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in was["sha256"])
                or type(was.get("bytes")) is not int or was["bytes"] < 0):
            raise OSError(f"This backup has an unsafe or invalid entry: {rel}")
    return listed


def _incomplete(folder: Path) -> bool:
    return json.loads(_path(folder, MANIFEST).read_text()).get("incomplete") is True


def damaged(folder: Path) -> list[str]:
    """The files of a backup that are missing or no longer what its manifest says ([] when it is whole)."""
    try:
        listed = manifest(folder)
    except (OSError, ValueError, KeyError, TypeError):
        return [MANIFEST]
    bad = []
    for rel, was in listed.items():
        try:
            copy = _path(folder, rel)
            if not copy.is_file() or copy.stat().st_size != was["bytes"] or digest(copy.read_bytes()) != was["sha256"]:
                bad.append(rel)
        except OSError:
            bad.append(rel)
    return bad


def plan(root: Path, folder: Path) -> dict:
    """What a restore would do to the project: files replaced, files brought back, files taken away (they are
    in the kind of place a backup keeps, and this backup does not have them), and files already the same."""
    listed, now = manifest(folder), files(root)
    for rel in listed:
        target = place(root, rel)  # check every destination before reading one or making a safety copy
        if target.exists() and not target.is_file():
            raise OSError(f"Restore needs a regular file here, but found something else: {rel}")
    same = [rel for rel in listed if place(root, rel).is_file() and digest(place(root, rel).read_bytes()) == listed[rel]["sha256"]]
    todo = {"replace": [rel for rel in listed if place(root, rel).is_file() and rel not in same],
            "bring_back": [rel for rel in listed if not place(root, rel).is_file()],
            "take_away": [rel for rel in now if rel not in listed], "same": same}
    for rel in todo["replace"] + todo["bring_back"]:
        target = place(root, rel)
        _path(target.parent, target.name + ".restoring.tmp")
    return todo


def _apply(root: Path, folder: Path) -> None:
    """Idempotent: a second pass finishes replacements and deletions left by an interrupted pass."""
    from core.state import closed_file
    listed, todo = manifest(folder), plan(root, folder)
    for rel in todo["replace"] + todo["bring_back"]:
        target = place(root, rel)
        tmp = target.with_name(target.name + ".restoring.tmp")
        _path(target.parent, tmp.name)
        data = _path(folder, rel).read_bytes()
        if digest(data) != listed[rel]["sha256"]:
            raise OSError(f"{rel} changed in the backup. Restore remains pending.")
        with closed_file(tmp, "wb") as out:  # (what comes back is his alone, like the folders made for it)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        tmp.replace(target)
        _sync(target.parent)
        if digest(target.read_bytes()) != listed[rel]["sha256"]:
            raise OSError(f"{rel} did not come back whole. Restore remains pending.")
    for rel in todo["take_away"]:
        target = place(root, rel)
        target.unlink(missing_ok=True)
        _sync(target.parent)


def _roots(root: Path) -> dict:
    return {top: str(_base(root, top).resolve()) for top in ("state", "profiles", "logs")}


def _belongs(roots: dict, root: Path, *, state_only: bool = False) -> bool:
    if not isinstance(roots, dict) or any(not isinstance(roots.get(top), str) or not Path(roots[top]).is_absolute()
                                          for top in ("state", "profiles", "logs")):
        raise ValueError("The restore marker does not name its state folders")
    recorded = {top: str(Path(roots[top]).resolve()) for top in ("state", "profiles", "logs")}
    current = _roots(root)
    # Shared state must stay gated, but recovery may only apply the original owner's profiles.
    return recorded["state"] == current["state"] if state_only else recorded == current


def _record(root: Path, record: dict) -> None:
    from core.state import closed_file
    marker = _marker(root)
    temp = _path(marker.parent, marker.name + ".tmp")
    with closed_file(temp, "w") as out:
        json.dump(record, out)
        out.flush()
        os.fsync(out.fileno())
    temp.replace(marker)
    _sync(marker.parent)


def _complete(root: Path) -> None:
    marker = _marker(root)
    marker.unlink()
    _sync(marker.parent)
    if problem(root):
        _path(_base(root, "logs"), "blocked").unlink()
        _sync(marker.parent)


@_exclusive
def recover(root: Path = ROOT) -> str:
    """Before startup: finish the selected copy, or durably choose the safety copy if the source was lost."""
    marker = _marker(root)
    if not marker.exists():
        return ""
    try:
        record = json.loads(marker.read_text())
        if not _belongs(record["roots"], root):
            raise OSError("The interrupted restore belongs to different state folders")
        folder = Path(record["source"])
        if damaged(folder) or _incomplete(folder):
            folder = Path(record["before"])
            if damaged(folder) or _incomplete(folder):
                raise OSError("Both restore copies are damaged or incomplete")
            record["source"] = str(folder)
            _record(root, record)  # a second interruption must continue the same rollback
        _apply(root, folder)
        _complete(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        _blocked(root, error)
        raise
    return f"Recovered interrupted restore from {folder.name}."


@_exclusive
def restore(root: Path, folder: Path) -> Path:
    """Validate first, keep the selected backup and safety copy, then mark the restore until it is whole."""
    if bad := damaged(folder):
        raise OSError("This backup is damaged and was not used: " + ", ".join(bad[:5]))
    if _incomplete(folder):
        raise OSError("This copy keeps incomplete files. Choose a complete backup to restart Viventium")
    plan(root, folder)
    before = save.__wrapped__(root, tag=UNDO, protect=(folder,))  # already under the same lock
    _record(root, {"source": str(folder.absolute()), "before": str(before.absolute()), "roots": _roots(root)})
    try:
        _apply(root, folder)
        _complete(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        _blocked(root, error)
        raise
    return before


def _when(folder: Path) -> str:
    try:
        made = json.loads(_path(folder, MANIFEST).read_text())["made"]
        return made.replace("T", " ") if isinstance(made, str) else folder.name
    except (OSError, ValueError, KeyError, TypeError):
        return folder.name


def main(argv: list[str]) -> int:
    action = argv[0] if argv else ""
    if action == "pending":
        try:
            return 0 if pending() else 1
        except (OSError, ValueError, KeyError, TypeError):
            return 0  # an unreadable guard must never start normal writers
    if action == "blocked":
        return 0 if pending() and problem() else 1
    if action == "status":
        print(json.dumps(recovery_view()))
        return 0
    if action == "doctor":
        print(problem() or "Restore is incomplete. Choose another backup in Settings.")
        print("Normal work stays paused. Settings can save the current files or restore a checked backup.")
        return 1
    if action == "reason":
        print(problem() or "Restore is incomplete. Choose a backup in Settings.")
        return 0
    if action == "recover":
        if said := recover():
            print(said)
        return 0
    if action == "save":
        made = save()
        print(f"Backed up {len(manifest(made))} files, each checked: {made}")
        print("Not in it, on purpose: your Life folder, your keys (they stay in the Keychain), models and logs.")
        return 0
    if action == "list":
        found = backups()
        for folder in found:
            undo = "   (what was there before a restore)" if UNDO in folder.name else ""
            incomplete = "   (incomplete files; kept for recovery only)" if _incomplete(folder) else ""
            print(f"{folder.name}   {_when(folder)}   {len(manifest(folder))} files{undo}{incomplete}")
        if not found:
            print("No backups yet. Make one: ./vx backup")
        return 0
    if action == "restore":
        names = [a for a in argv[1:] if not a.startswith("--")]
        found = backups()
        # No name: the newest one you made. (What a restore saved first is its undo: ask for it by name.)
        yours = [f for f in found if not _undo(f)]
        folder = next((f for f in found if f.name == names[0]), None) if names else (yours[0] if yours else None)
        if folder is None:
            print("No such backup. See them: ./vx backup list" if names else "No backups yet. Make one: ./vx backup")
            return 1
        if bad := damaged(folder):
            print(f"The backup {folder.name} is damaged and was not used: " + ", ".join(bad[:5]))
            return 1
        if _incomplete(folder):
            raise OSError("This copy keeps incomplete files. Choose a complete backup to restart Viventium")
        todo = plan(ROOT, folder)
        if not pending() and not (todo["replace"] or todo["bring_back"] or todo["take_away"]):
            print(f"Everything is already as it was in {folder.name} ({_when(folder)}). Nothing to do.")
            return 0
        print(f"Restoring the backup from {_when(folder)} will:")
        for title, key in (("replace", "replace"), ("bring back", "bring_back"), ("take away (not in that backup)", "take_away")):
            for rel in todo[key]:
                print(f"  {title}: {rel}")
        print("What is there now is saved first as its own backup, so this can be undone.")
        if "--yes" not in argv:
            if not sys.stdin.isatty():
                print("Not done: nobody is here to say yes. Run it in a terminal, or add --yes.")
                return 1
            if input("Go ahead? Type yes: ").strip().lower() != "yes":
                print("Not done.")
                return 1
        before = restore(ROOT, folder)
        print(f"Restored. To undo: ./vx restore {before.name}")
        print("Start Viventium again: ./vx up")
        return 0
    print("python -m core.backup save | list | restore [NAME] [--yes]")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Backup/restore stopped: {error}")
        sys.exit(1)
