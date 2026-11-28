"""Where a choice is kept. Two places, each with one job.

1. What a profile runs on: one small marked block at the end of the private, untracked files vx already reads
   last (profiles/<profile>.local.env; profiles/machine.local.env for this Mac). The tracked profiles stay the
   defaults; lines you wrote by hand above the block are never touched; a choice equal to the default removes
   itself. Values are read the way vx reads them, by the shell, so the page can never disagree with what starts.
2. What only she and the page need (the options you last chose for each place, your sentence for her Workers,
   how she behaves on a call): one JSON file in her state folder. Free text never goes into a file the shell
   reads.
"""
import fcntl
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("VX_SETTINGS_ROOT") or Path(__file__).resolve().parents[1])
BEGIN = "# >>> settings page: her choices (managed; write your own lines above this one)"
END = "# <<< settings page"


def state_file() -> Path:
    return Path(os.environ.get("VX_STATE") or ROOT / "state") / "settings.json"


def clean_env() -> dict:
    """What a fresh terminal would have. The page's server was started by vx with a whole profile exported; a
    restart that inherited it would keep the old profile's lines the new one does not set."""
    keep = ("HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "PATH")
    return {k: os.environ[k] for k in keep if k in os.environ}


def private_open(path: Path, mode: str = "w"):
    """open() for a file of the settings package's own (her logs, her state): his alone from creation (0600, an older
    one closed too), never through a link, its folder 0700 when made. (core/state.private_file asks the file to lie in
    her own folders, which a test's temporary root is not.)"""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if mode.startswith("a") else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, mode)


def private_write(path: Path, text: str) -> None:
    with private_open(path) as handle:
        handle.write(text)


def read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def write(path: Path, text: str) -> None:
    """Whole or not at all, keeping the file's own permissions (0600 when new). An empty text removes the file."""
    if not text:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


# -- 1. The marked block in a private profile file --

def split(text: str) -> tuple[str, dict]:
    """A private file's own lines, and the page's block at its end (if any)."""
    if BEGIN not in text:
        return text, {}
    head, _, rest = text.partition(BEGIN)
    block = {}
    for line in rest.partition(END)[0].splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            block[key.strip()] = value.strip().strip('"')
    return head.rstrip("\n") + ("\n" if head.strip() else ""), block


def join(head: str, block: dict) -> str:
    if not block:
        return head
    for key, value in block.items():  # only what a catalog entry can say: never free text in a file the shell reads
        if not key.replace("_", "").isalnum() or any(c in str(value) for c in '"`$\\\n'):
            raise ValueError(f"not a setting the page may write: {key}")
    lines = "\n".join(f'{key}="{value}"' for key, value in sorted(block.items()))
    return (head + ("\n" if head and not head.endswith("\n\n") else "")) + f"{BEGIN}\n{lines}\n{END}\n"


def files(profile: str) -> tuple[Path, Path, Path]:
    folder = ROOT / "profiles"
    return folder / f"{profile}.env", folder / "machine.local.env", folder / f"{profile}.local.env"


def shell_values(texts: list[str], keys: list[str]) -> dict:
    """What these files, sourced in order, leave set: bash's own answer (quotes, comments, $HOME and all)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for i, text in enumerate(texts):
            path = Path(tmp) / f"{i}.env"
            path.write_text(text)
            paths.append(str(path))
        script = 'set -a; for f in "$@"; do . "$f"; done; for k in %s; do printf "%%s=%%s\\0" "$k" "${!k-}"; done' % " ".join(keys)
        out = subprocess.run(["/bin/bash", "-c", script, "_", *paths], env=clean_env(), capture_output=True, text=True, timeout=15)
    return dict(item.split("=", 1) for item in out.stdout.split("\0") if "=" in item)


def assigned(profile: str, keys: list[str]) -> set:
    """The keys his own lines set in this profile's private files (machine.local.env and its own, above the page's
    blocks): one set empty as much as one with a value, as bash reads them. (values() cannot tell an empty line from
    none: both read "".)"""
    base, machine, own = files(profile)
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for i, text in enumerate((split(read(machine))[0], split(read(own))[0])):
            path = Path(tmp) / f"{i}.env"
            path.write_text(text)
            paths.append(str(path))
        script = 'set -a; for f in "$@"; do . "$f"; done; for k in %s; do [ -n "${!k+set}" ] && printf "%%s\\0" "$k"; done; true' % " ".join(keys)
        out = subprocess.run(["/bin/bash", "-c", script, "_", *paths], env=clean_env(), capture_output=True, text=True, timeout=15)
    return {k for k in out.stdout.split("\0") if k}


def values(profile: str, keys: list[str], blocks: bool = True) -> dict:
    """A profile's settings as vx loads them; blocks=False leaves the page's own choices out (the defaults)."""
    base, machine, own = files(profile)
    texts = [read(base), read(machine), read(own)]
    if not blocks:
        texts = [texts[0], split(texts[1])[0], split(texts[2])[0]]
    context = ["SMALL_MAC_TIER", "KEYS_OFF", "XAI_API_KEY_ITEM"] if "TTS" in keys else []
    values = shell_values(texts, list(dict.fromkeys([*keys, *context])))
    if values.get("TTS") == "auto":
        from speech.selection import resolve
        values = resolve(values)
    return {key: values.get(key, "") for key in keys}


def block(profile: str) -> dict:
    return split(read(files(profile)[2]))[1]


def machine_block() -> dict:
    return split(read(files("local")[1]))[1]


def save_block(path: Path, block: dict) -> None:
    write(path, join(split(read(path))[0], block))


# -- 2. Her own small memory of your choices --

def remembered() -> dict:
    try:
        saved = json.loads(state_file().read_text())
        return saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(change) -> dict:
    """Read, change and save in one step (the page saves one small thing at a time), one writer at a time: the page, the
    menu bar's panel and her agent each write from their own process, and a change decided on what it read (the newest
    call mode wins) must not be overwritten by one that read before it."""
    path = state_file()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = remembered()
        change(saved)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
        with os.fdopen(fd, "w") as handle:
            json.dump(saved, handle, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    return saved
