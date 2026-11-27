"""Where Light keeps its runtime state on this Mac (untracked): the conversation, jobs, schedules,
the Telegram owner and Feelings. Tests run with VX_STATE set to their own folder, so a test call
never lands in your history or moves her feelings. Importing this module changes nothing on disk.

Her state is his alone:
- `python -m core.state` (./vx up runs it before anything starts) makes her folders private at every start: her state
  and the logs that go with it (state/ and logs/ of this checkout, or VX_STATE and VX_LOGS); folders 0700, files 0600,
  the owner's own bits kept. Her state is looked through whole each time (a file a writer left open is closed at the
  next start); her logs' own files too, and the folders inside them when they are open. Each folder is closed last, so
  a pass cut short is done again at the next start.
- private_dir() and private_file() are how a writer makes a folder or a file of hers: 0700 and 0600 from the start,
  never through a link. log_file() is where a run's own log lines go (never his for a state that is not his).
- Never touched: anything through a link; a file that also has another name (it keeps its mode, behind folders only he
  can open); his home, a folder above it or above this checkout; a folder that holds his Life or lies inside it.

refuse_live() is the first line of every test and probe, before anything is written: a test given or inheriting his
Workers' xPerfect state (./vx loads it) gets a stand-in of its own, and a test whose state or Life would be his live
state or his real Life (wherever it is: the default place, profiles/*.local.env, or inside or around the folder it
was given) is stopped.

LIVE_PORTS and live_places() name his live Light's own ports and folders in one place, for what must keep off them
(tests/sandbox.py: every test's guard).
"""
import fcntl
import functools
import json
import logging
import os
import shlex
import stat
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path(os.environ.get("VX_STATE") or ROOT / "state")
HOME = Path.home()
OWNER_LIFE = HOME / "Documents" / "Viventium" / "Life"  # where ./vx finds his Life unless told otherwise


CALL_LIVE = STATE_ROOT / "core" / "call-live"  # touched every 20 s while a call is on (call/agent.py)
# Who holds it: one mark for each who made it live (a room's agent, by its room: hold_call; the call page starting a
# call, as "page", made by the page itself: call/ui/app/api/token ready.ts), so a room that ends clears it only when no
# one else holds it.
CALL_HOLDERS = STATE_ROOT / "core" / "call-live.d"
CALL_LOCK = STATE_ROOT / "core" / "call-live.lock"  # (held while a mark is made or the shared one is cleared)


def _call_lock():
    """The one lock every room's agent takes to mark or clear call-live: a room clearing it never misses a mark another
    room made while it looked. (The call page marks without it, in its own order: release_call.)"""
    import contextlib
    import fcntl

    @contextlib.contextmanager
    def held():
        with closed_file(CALL_LOCK, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    return held()


def _holder(holder: str) -> Path:
    import hashlib
    return CALL_HOLDERS / hashlib.sha256(holder.encode()).hexdigest()[:16]  # (a room's name never becomes a path)


def hold_call(holder: str) -> None:
    """A room's agent: someone is talking with her there now (call_live, for about a minute). Its own mark, then the
    shared one every reader reads."""
    with _call_lock():
        for mark in (_holder(holder), CALL_LIVE):
            closed_file(mark, "a").close()
            os.utime(mark)


def release_call(holder: str) -> None:
    """A room's agent, when its room ends: its own mark goes, and the shared one too when no one else holds it now (no
    other room in its minute, no page starting a call). Closing a typed page never lifts the guard another page's call
    holds (every room used to delete it). Rooms mark and clear under one lock; the call page marks
    without it (call/ui/app/api/token ready.ts), its own mark always before the shared one, so a page that marked
    itself after this look gets the shared mark back here."""
    mine = _holder(holder)
    if not mine.exists():
        return  # (never held: nothing of its own to clear)
    with _call_lock():  # (its look at the others and its clearing are one step for every room)
        mine.unlink(missing_ok=True)
        if _held():
            return
        CALL_LIVE.unlink(missing_ok=True)
        if _held():  # (a page marked itself meanwhile: its shared mark, cleared just now, comes back)
            closed_file(CALL_LIVE, "a").close()
            os.utime(CALL_LIVE)


def _held() -> bool:
    """Whether anyone holds call-live now (a mark in its minute); marks past their minute are cleared on the way."""
    import time
    for mark in CALL_HOLDERS.iterdir() if CALL_HOLDERS.is_dir() else []:
        try:
            if time.time() - mark.stat().st_mtime < 60:
                return True
            mark.unlink()  # (a room whose agent died holding it: its minute is over)
        except OSError:
            continue
    return False


def call_live() -> bool:
    """Whether someone is on a call now. Heavy background model work (her core view, chat summaries) waits
    for the call to end: on the local profile one GPU serves her voice and that work."""
    import time
    try:
        return time.time() - CALL_LIVE.stat().st_mtime < 60
    except OSError:
        return False


def setting(name: str, default=None):
    """One of the settings the page keeps in her state (settings/store.py): how she behaves on a call, your
    sentence for her Workers. Read when it is needed, so a change takes effect without a restart."""
    import json
    try:
        return json.loads((STATE_ROOT / "settings.json").read_text()).get(name, default)
    except (OSError, ValueError, AttributeError):
        return default


def setting_all() -> dict:
    """All of the settings the page keeps in her state, as they are now ({} when there are none yet)."""
    import json
    try:
        saved = json.loads((STATE_ROOT / "settings.json").read_text())
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


# -- Never a test on his own, and never his home or his Life (only looks) --

def _checkouts() -> list[Path]:
    """This checkout, and the one it is a git worktree of (where his own Light runs), if it is one."""
    found = [ROOT]
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        common = ""
    if common and Path(common).name == ".git" and Path(common).parent.resolve() != ROOT.resolve():
        found.append(Path(common).parent)
    return found


def _lives(checkouts: list[Path]) -> list[Path]:
    """His real Life: the default, and any LIFE a checkout's private settings name (profiles/*.local.env, as ./vx
    reads them). Private settings that cannot be read could name it: OSError, and the callers refuse."""
    found = [OWNER_LIFE]
    for checkout in checkouts:
        try:
            names = sorted(n for n in os.listdir(checkout / "profiles") if n.endswith(".local.env"))
        except FileNotFoundError:
            continue  # (no private settings there)
        for name in names:
            lines = (checkout / "profiles" / name).read_text().splitlines()
            for line in lines:
                try:
                    words = shlex.split(line, comments=True)
                except ValueError:
                    continue
                found += [Path(os.path.expanduser(os.path.expandvars(w[5:]))) for w in words if w.startswith("LIFE=") and w[5:]]
    return found


def _real(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(path))).resolve()


def _within(path: Path, places: list[Path]) -> bool:
    real = _real(path)
    return any(real == _real(p) or _real(p) in real.parents for p in places)


def _touches(path: Path, places: list[Path]) -> bool:
    """path is one of places, lies inside one, or holds one."""
    real = _real(path)
    return any(real == p or p in real.parents or real in p.parents for p in map(_real, places))


def _live_xperfect(path: Path, checkouts: list[Path]) -> bool:
    real = _real(path)
    return any(_real(c / "brain") in real.parents and real.relative_to(_real(c / "brain")).parts[0].startswith("state-")
               for c in checkouts)


def live_reason() -> str:
    """Why this process must not run as a test here ("" when it may): its state would be his live state (every
    checkout's state/: a test passing on it in a worktree would write into his history when run in his own checkout),
    or its state, its Life or its Workers' state is his real Life, lies in it or holds it, or its Workers' state is his
    live xPerfect state. Writes nothing."""
    checkouts = _checkouts()
    try:
        lives = _lives(checkouts)
    except OSError as error:
        return f"his private settings could not be read ({error.filename}), so his Life cannot be told apart"
    for state in {STATE_ROOT, Path(os.environ.get("VX_STATE") or STATE_ROOT)}:
        if _within(state, [c / "state" for c in checkouts]):
            return f"its state would be his live state ({state}); set VX_STATE to a folder of its own"
        if _touches(state, lives):
            return f"its state folder is his real Life, lies in it or holds it ({state}); set VX_STATE to a folder of its own"
    life = os.environ.get("LIFE")
    if life and _touches(Path(life), lives):
        return f"LIFE is his real Life folder, lies in it or holds it ({life}); use a copy of tests/fixtures/life"
    for name in ("XPERFECT_STATE", "XPERFECT_LOCAL_STATE"):
        value = os.environ.get(name)
        if value and _live_xperfect(Path(value), checkouts):
            return f"{name} is his Workers' live xPerfect state ({value})"
        if value and _touches(Path(value), lives):
            return f"{name} is his real Life, lies in it or holds it ({value})"
    return ""


_STAND_IN: list[Path] = []


def isolate_workers() -> None:
    """A test never reaches his Workers: an xPerfect state of his (a checkout's brain/state-*) that it was given or
    inherited (./vx loads one into every test it runs) becomes a stand-in of its own, at an address that answers
    nothing. Nothing of his is read or written."""
    checkouts = _checkouts()
    for state, api in (("XPERFECT_STATE", "XPERFECT_API"), ("XPERFECT_LOCAL_STATE", "XPERFECT_LOCAL_API")):
        value = os.environ.get(state)
        if value and _live_xperfect(Path(value), checkouts):
            if not _STAND_IN:
                import json
                import tempfile
                stand_in = Path(tempfile.mkdtemp(prefix="vx-test-xperfect-"))
                (stand_in / "secrets.json").write_text(json.dumps({"api_token": "test", "mcp_token": "test", "link_secret": "test"}))
                (stand_in / "config.json").write_text(json.dumps({"env": {}, "models": {}, "ports": {}}))
                _STAND_IN.append(stand_in)
            os.environ[state], os.environ[api] = str(_STAND_IN[0]), "http://xperfect.test.invalid"


def refuse_live() -> None:
    """The first line of every test and probe, after it sets its own VX_STATE (and LIFE), before anything is written:
    his Workers' state, given or inherited, becomes a stand-in (isolate_workers); then the test stops right there if
    its state or Life would be his live state or his real Life (live_reason)."""
    isolate_workers()
    if why := live_reason():
        raise SystemExit(f"Refusing to run: {why}.")


# -- His live Light's own ports and folders, named once (only looks) --

# The ports vx starts his Light's parts on (vx: start, serve_model, xp_ports; call/livekit.yaml; call/phone.py for the
# phone's two doors). A test, a probe, an eval or the bench never listens on one, and reaches one only when the person
# running it names that part (tests/sandbox.py). tests/hygiene_test.py fails when vx and this table differ.
LIVE_PORTS = {"ui": 3400, "livekit": 7880, "livekit-tcp": 7881, "livekit-udp": 7882, "agent": 8870, "doorbell": 8869,
              "stt": 8930, "tts": 8940, "model": 11435, "worker-model": 11436, "embed-model": 11437,
              "xperfect": 8866, "xperfect-mcp": 8867, "xperfect-ui": 8880,
              "xperfect-local": 8876, "xperfect-local-mcp": 8877, "xperfect-local-ui": 8890,
              "phone-page": 3443, "phone-call": 7443}


def live_places() -> tuple[list[Path], list[Path]]:
    """His live Light's own folders, for what must never write into them (tests/sandbox.py), as (closed, files only):
    closed, with everything below them: every checkout's state/, its Workers' xPerfect states (brain/state-*) and its
    private settings (profiles/), his Life wherever it is, his backups, and, from a worktree, the logs of the checkout
    his Light runs from. Files only: this checkout's own logs/, where a run keeps its folders (logs/tests, logs/bench)
    beside his live log files, which are his. Private settings that cannot be read raise OSError (his Life cannot be
    told apart): the caller refuses."""
    checkouts = _checkouts()
    closed = _lives(checkouts) + [HOME / "Library" / "Application Support" / "Viventium Light"]
    for checkout in checkouts:
        closed += [checkout / "state", checkout / "profiles", checkout / "brain" / "state-cloud", checkout / "brain" / "state-local"]
        closed += sorted((checkout / "brain").glob("state-*"))
    closed += [checkout / "logs" for checkout in checkouts[1:]]
    return closed, [checkouts[0] / "logs"]


@functools.lru_cache(maxsize=32)
def _unsafe(folder: str) -> str:
    """Why Light must never make this folder private ("" when it may): his home or a folder above it, this checkout
    or a folder above it, or a folder that holds his Life or lies inside it. Only looks; asked once per folder."""
    real = _real(Path(folder))
    for guarded, what in ((HOME, "his home"), (ROOT, "this checkout")):
        if real == _real(guarded) or real in _real(guarded).parents:
            return f"it is {what} or a folder above it"
    try:
        lives = _lives(_checkouts()) + ([Path(os.environ["LIFE"])] if os.environ.get("LIFE") else [])  # (this run's too)
    except OSError as error:
        return f"his private settings could not be read ({error.filename})"
    for life in map(_real, lives):
        if real == life or real in life.parents or life in real.parents:
            return "it holds his Life or lies inside it"
    return ""


# -- His alone --

log = logging.getLogger("state")
_NOFOLLOW = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}


def _roots() -> list[Path]:
    """Her own folders: her state, this checkout's logs, and the logs a run names for itself (the bench's, a test's)."""
    found = [STATE_ROOT, ROOT / "logs"]
    if os.environ.get("VX_LOGS"):
        found.append(Path(os.environ["VX_LOGS"]))
    if os.environ.get("VX_SETTINGS_ROOT"):
        found.append(Path(os.environ["VX_SETTINGS_ROOT"]) / "logs")
    return [Path(os.path.abspath(p)) for p in found]


def _own_folders() -> list[Path]:
    """What one start makes private: her state, and the logs that go with it (this checkout's logs/ beside its state/,
    or VX_LOGS when a run names its own, the bench). A test's own state alone otherwise."""
    folders = [STATE_ROOT]
    if os.environ.get("VX_LOGS"):
        folders.append(Path(os.environ["VX_LOGS"]))
    elif not os.environ.get("VX_STATE"):
        folders.append(ROOT / "logs")
    return folders


def private(folder: Path, whole: bool = True) -> bool:
    """Make one of her folders his alone, and say whether it is: made 0700 if it is missing; everything in it that is
    open to others loses every permission of the group and of others, the folder itself last (a pass cut short is
    done again next time). Looked through whole at every start (her state: a file a writer left open is closed at the
    next start). whole=False, for her logs (many thousands of files) once the folder itself is closed: only what is
    directly in it, each open folder there closed without going in (closed, it shuts in what it holds).
    Refused, and said once: an unsafe folder (_unsafe), a link, a disk that cannot keep it."""
    if why := _unsafe(str(folder)):
        log.warning("Viventium left %s as it is: %s.", folder, why)
        return False
    try:
        top = os.lstat(folder)
    except FileNotFoundError:
        Path(folder).mkdir(mode=0o700, parents=True, exist_ok=True)
        top = os.lstat(folder)  # (what was made, or made meanwhile: checked like any folder, never taken on trust)
    if not stat.S_ISDIR(top.st_mode):
        log.warning("Viventium left %s as it is: it is a link or not a folder, so it cannot be made private.", folder)
        return False
    failed = 0
    for path, st in _inside(folder, deep=whole or bool(stat.S_IMODE(top.st_mode) & 0o077)):
        mode = stat.S_IMODE(st.st_mode)
        if mode & 0o077:
            try:
                os.chmod(path, mode & 0o700, **_NOFOLLOW)
            except OSError:
                failed += 1
    if stat.S_IMODE(top.st_mode) & 0o077:
        try:
            os.chmod(folder, stat.S_IMODE(top.st_mode) & 0o700)
        except OSError:
            pass
    if failed:
        log.warning("Viventium could not close %d of the files in %s to others (the folder still shuts them in).", failed, folder)
    if stat.S_IMODE(os.lstat(folder).st_mode) & 0o077:
        log.warning("Viventium could not make %s private on this disk: other accounts on this Mac may read it.", folder)
        return False
    return True


def _inside(folder: Path, deep: bool = True):
    """Every folder and file in it, as (path, lstat): links are neither followed nor listed, nor a file with
    other names. deep=False: only what is directly in it."""
    stack = [str(folder)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        if deep:
                            stack.append(entry.path)
                        yield entry.path, st
                    elif stat.S_ISREG(st.st_mode) and st.st_nlink == 1:
                        yield entry.path, st
        except OSError:
            continue


def make_private() -> bool:
    """Her folders, private, at a start (./vx up, before anything else runs): her state looked through whole, the logs
    that go with it by what is directly in them (see private())."""
    return all([private(folder, whole=n == 0) for n, folder in enumerate(_own_folders())])


def closed_dir(path) -> Path:
    """A folder of hers, made if it is missing, every folder made on the way 0700 from the start. Only the mode: for
    a writer that private_dir() cannot serve (a file a run places itself, a test's state beside its Life)."""
    path = Path(path)
    if path.is_dir():
        return path  # (the usual case, one look)
    for folder in reversed([p for p in (path, *path.parents) if not p.exists()]):
        try:
            os.mkdir(folder, 0o700)
        except FileExistsError:
            pass  # (made by another process meanwhile)
    return path


def _closed(path, flags):
    return os.open(path, flags, 0o600)


def closed_file(path, mode: str = "w", **kwargs):
    """open() for a file of hers: 0600 when it is made (never open to others for a moment), closed to others when it
    was open, its folders 0700 when made (closed_dir). Only the mode: private_file() also refuses links and what is
    outside her folders, and is the one to use where it can be asked. A file reached through a link, or one that also
    has another name, keeps its mode (as at a start: _inside)."""
    closed_dir(Path(path).parent)
    f = open(path, mode, opener=_closed, **kwargs)
    try:
        st = os.fstat(f.fileno())
        if mode.strip("bt+") != "r" and stat.S_IMODE(st.st_mode) & 0o077 and stat.S_ISREG(st.st_mode) \
                and st.st_nlink == 1 and not stat.S_ISLNK(os.lstat(path).st_mode):
            os.fchmod(f.fileno(), stat.S_IMODE(st.st_mode) & 0o700)
    except OSError:
        pass  # (a disk that will not keep it closed: its folder still shuts it in)
    return f


def logs() -> Path:
    """The logs that go with the state in use: the folder a run names for itself (VX_LOGS: the bench's), inside a
    test's own state (VX_STATE), else this checkout's logs/ (his live Light's). Never his logs for a state that is
    not his (a bench's Feelings reactor once wrote its lines into his; her greeting, night and memory lines
    did too)."""
    if os.environ.get("VX_LOGS"):
        return Path(os.environ["VX_LOGS"])
    return STATE_ROOT / "logs" if os.environ.get("VX_STATE") else ROOT / "logs"


def log_file(name: str):
    """One of this run's own logs (logs()), opened to add to, his alone from the start (closed_file): what a part of
    hers started in its own process writes its lines into."""
    return closed_file(logs() / name, "a")


OPTIONAL_FAILURES_FILE = "optional-write-failures.json"
OPTIONAL_FAILURES = {
    "thought": "could not save a Subconscious thought",
    "thought_trim": "could not trim saved Subconscious thoughts",
    "run_history": "could not save the Subconscious run history",
    "history_view": "could not save the conversation history view",
    "summary": "could not save a conversation summary",
    "summary_index": "could not save the conversation summary index",
    "summary_mark": "could not save the conversation summary mark",
}


def recent_optional_failures(path: Path, hour: int) -> dict:
    """At most 24 hourly buckets. Each contains only counts for fixed failure kinds."""
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: {kind: count for kind, count in counts.items()
                  if kind in OPTIONAL_FAILURES and type(count) is int and count > 0}
            for h in range(hour - 23, hour + 1)
            if isinstance(counts := data.get(key := str(h)), dict)}


def optional_write_failed(kind: str) -> None:
    """Count an optional write failure without saving any paths, error text or saved content."""
    if kind not in OPTIONAL_FAILURES:
        return
    path = logs() / OPTIONAL_FAILURES_FILE
    try:
        with closed_file(path.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            hour = int(time.time() // 3600)
            data = recent_optional_failures(path, hour)
            counts = data.setdefault(str(hour), {})
            counts[kind] = counts.get(kind, 0) + 1
            temp = path.with_suffix(".tmp")
            with closed_file(temp, "w") as out:
                json.dump(data, out)
            temp.replace(path)
    except OSError:
        log.warning("%s", OPTIONAL_FAILURES[kind])


def private_dir(path) -> Path:
    """A folder of hers, his alone, made if it is missing: every folder from her root down to it is a real folder
    (a link refuses), made 0700 when missing and closed to others when open. Refuses (OSError) a path outside her
    folders, an unsafe root and a disk that will not keep a folder closed, so the write that wanted it does not happen."""
    path = Path(os.path.abspath(path))
    root = max((r for r in _roots() if path == r or r in path.parents), key=lambda r: len(r.parts), default=None)
    if root is None:
        raise PermissionError(f"{path} is not one of Viventium's own folders")
    if why := _unsafe(str(root)):
        raise PermissionError(f"Viventium will not keep its state in {root}: {why}")
    at = root
    for part in (None, *path.relative_to(root).parts):
        at = at / part if part else at
        if not os.path.lexists(at):
            if at == root:  # (the folders above her root are not hers: made as they would be anyway)
                at.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.mkdir(at, 0o700)
            except FileExistsError:
                pass  # (made by another process meanwhile: looked at below)
        st = os.lstat(at)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise PermissionError(f"{at} is a link or not a folder: Viventium will not write through it")
        if stat.S_IMODE(st.st_mode) & 0o077:
            os.chmod(at, stat.S_IMODE(st.st_mode) & 0o700, **_NOFOLLOW)
            if stat.S_IMODE(os.lstat(at).st_mode) & 0o077:
                raise PermissionError(f"{at} cannot be kept private on this disk: Viventium will not write there")
    return path


def private_file(path, mode: str = "w", **kwargs):
    """open() for a file of hers: made 0600 when new and closed to others when open; never through a link, nor
    into a file that also has another name (OSError: the write does not happen); its folder from private_dir()."""
    path = Path(os.path.abspath(path))
    private_dir(path.parent)
    kind = mode.replace("b", "").replace("t", "").replace("+", "")
    flags = {"r": os.O_RDONLY, "w": os.O_WRONLY | os.O_CREAT, "a": os.O_WRONLY | os.O_CREAT | os.O_APPEND,
             "x": os.O_WRONLY | os.O_CREAT | os.O_EXCL}[kind]
    if "+" in mode:
        flags = (flags & ~os.O_WRONLY) | os.O_RDWR
    fd = os.open(path, flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        st = os.fstat(fd)
        if kind != "r":
            if st.st_nlink > 1:
                raise PermissionError(f"{path} also has another name: Viventium will not write through it")
            if stat.S_IMODE(st.st_mode) & 0o077:
                os.fchmod(fd, stat.S_IMODE(st.st_mode) & 0o700)
                if stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
                    raise PermissionError(f"{path} cannot be kept private on this disk: Viventium will not write it")
            if kind == "w":
                os.ftruncate(fd, 0)
        return os.fdopen(fd, mode, **kwargs)
    except BaseException:
        os.close(fd)
        raise


if __name__ == "__main__":  # ./vx up and restart, before anything of hers starts or stops: a folder of hers that cannot
    # be made his alone (a link, his home or Life, a disk that will not keep it) stops them, with what was said above
    logging.basicConfig(level=logging.WARNING, format="  %(message)s")
    try:
        ok = make_private()
    except Exception as error:  # noqa: BLE001
        log.warning("Viventium could not make its folders private (%s).", type(error).__name__)
        ok = False
    raise SystemExit(0 if ok else 1)
