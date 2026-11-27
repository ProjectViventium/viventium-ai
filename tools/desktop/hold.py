"""One Worker at a time at the user's screen, mouse and keyboard (computer use). Jobs run side by side, so two Workers
could otherwise click and type into the same desktop at once. Pages in their Chrome through the browser tools are not
computer use: each Worker drives its own pages there, side by side, with no hold.

    tools/desktop/hold take [--for SECONDS] [--wait SECONDS]   wait its turn, then hold the desktop (again: keep it longer)
    tools/desktop/hold give                                    let it go (only its holder can)
    tools/desktop/hold -- COMMAND ...                          hold it for one command (AppleScript, a click tool), then let go
    tools/desktop/hold                                         who holds it now

The holder is this Worker: the folder it works in, and its own long-lived process. A hold ends when it is given back, when
its time is up (2 minutes unless asked for more, at most 15), or when its holder's process is gone: a Worker that died
never blocks the next. One small file (VX_DESKTOP_LOCK, else Light's own folder in Application Support), changed only
under a lock of its own. Plain standard library: any Worker's shell runs it.
"""
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LOCK = Path(os.environ.get("VX_DESKTOP_LOCK") or Path.home() / "Library" / "Application Support" / "Viventium Light" / "desktop.json")
LEASE, LONGEST, WAIT = 120.0, 900.0, 600.0  # s: a hold's time, the longest one, the longest wait for a turn
SHELLS = {"sh", "bash", "zsh", "dash", "fish", "env", "login", "timeout", "nohup", "xargs", "sudo"}


def _ps(pid: int, field: str) -> str:
    try:
        return subprocess.run(["ps", "-o", f"{field}=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def worker_process() -> int:
    """The process that stands for this Worker: the nearest ancestor that is not a shell running the command (its harness,
    alive while the Worker works). 0 when it cannot be told: the hold then ends only by time or by give."""
    pid = os.getppid()
    for _ in range(6):
        if pid <= 1:
            return 0
        if Path(_ps(pid, "comm")).name not in SHELLS:
            return pid
        try:
            pid = int(_ps(pid, "ppid") or 0)
        except ValueError:
            return 0
    return 0


def alive(pid: int) -> bool:
    if pid <= 0:
        return True  # (not known: its time decides)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _held(record: dict, now: float) -> bool:
    return bool(record) and now < float(record.get("until", 0)) and alive(int(record.get("pid", 0)))


class _Guard:
    """The lease file's own lock: one change at a time across every Worker."""

    def __enter__(self):
        LOCK.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.handle = open(LOCK.with_suffix(".lock"), "a")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        try:
            self.record = json.loads(LOCK.read_text()) if LOCK.exists() else {}
        except (OSError, ValueError):
            self.record = {}
        return self

    def write(self, record: dict) -> None:
        temp = LOCK.with_suffix(".tmp")
        temp.write_text(json.dumps(record))
        temp.replace(LOCK)
        self.record = record

    def __exit__(self, *exc):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def take(seconds: float = LEASE, wait: float = WAIT, owner: str = "", pid: int | None = None) -> dict | None:
    """Hold the desktop for `seconds` once it is free (or keep it, when this Worker holds it); None if the wait ran out."""
    owner, pid = owner or os.getcwd(), worker_process() if pid is None else pid
    seconds, deadline = max(1.0, min(seconds, LONGEST)), time.monotonic() + max(0.0, wait)
    while True:
        with _Guard() as guard:
            now, held = time.time(), guard.record
            mine = _held(held, now) and held.get("owner") == owner
            if mine or not _held(held, now):
                record = {"owner": owner, "pid": pid, "since": held["since"] if mine else now, "until": now + seconds}
                guard.write(record)
                return record
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.25)


def give(owner: str = "") -> bool:
    """Let the desktop go; only its holder can (True), anyone else changes nothing (False)."""
    owner = owner or os.getcwd()
    with _Guard() as guard:
        if guard.record.get("owner") != owner:
            return not _held(guard.record, time.time())  # (nothing to give: fine when nobody holds it)
        guard.write({})
        return True


def holder() -> dict:
    with _Guard() as guard:
        return guard.record if _held(guard.record, time.time()) else {}


def brief(command: str = "") -> str:
    """The line a Worker's brief carries (with the full path of this tool)."""
    command = command or str(Path(__file__).resolve().with_name("hold"))
    return (f"Desktop hold, for computer use only (their screen, mouse and keyboard): run {command} take before the first "
            f"step (it waits its turn; you hold it 2 minutes, run it again to keep it), and {command} give as soon as you are "
            "done. Pages in their Chrome through the browser tools need no hold.")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--"] and len(argv) > 1:  # (one command, held; let go whatever happens)
        record = take(LEASE, WAIT, pid=os.getpid())
        if record is None:
            print("The desktop is busy with another job; try again in a moment.", file=sys.stderr)
            return 75
        try:
            return subprocess.run(argv[1:]).returncode
        finally:
            give()
    if argv[:1] == ["take"]:
        seconds = float(argv[argv.index("--for") + 1]) if "--for" in argv else LEASE
        wait = float(argv[argv.index("--wait") + 1]) if "--wait" in argv else WAIT
        record = take(seconds, wait)
        if record is None:
            held = holder()
            print(f"The desktop is busy with another job (since {time.strftime('%H:%M:%S', time.localtime(held.get('since', 0)))}); "
                  "try again later.", file=sys.stderr)
            return 75
        print(f"The desktop is yours until {time.strftime('%H:%M:%S', time.localtime(record['until']))}.")
        return 0
    if argv[:1] == ["give"]:
        if give():
            print("The desktop is free.")
            return 0
        print("The desktop is held by another job; only it can give it back.", file=sys.stderr)
        return 1
    held = holder()
    print(f"Held by {held['owner']} until {time.strftime('%H:%M:%S', time.localtime(held['until']))}." if held else "Free.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
