"""Her voice as the settings page last set it, also while she is already talking. Before, a voice chosen during a
call was not heard until long after, which felt like a bug: a voice choice waited for the call to end and then
restarted all of her (2.5 minutes once). Now a call and Telegram read the voice from the profile files themselves,
the way ./vx does, when one of them changes: the next sentence she says is in the new voice, and nothing restarts.
"""
import asyncio
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("TTS", "TTS_VOICE", "TTS_FALLBACK", "TTS_FALLBACK_VOICE", "TTS_MODEL", "TTS_URL", "TTS_STREAM",
        "TTS_STREAM_SECONDS", "TTS_TAGS")


def home() -> Path:
    """Where this process's profile lives: its settings root (VX_SETTINGS_ROOT, as the settings page and ./vx give it:
    the bench gives its own), else this checkout. Never another runtime's: a bench's agent once read this checkout's
    marker and spoke with the live profile's voice (every bench Hybrid run spoke Chatterbox, not Eve)."""
    return Path(os.environ.get("VX_SETTINGS_ROOT") or ROOT)


def files(root: Path | None = None) -> list[Path]:
    """The profile's three files, in the order ./vx reads them (load_profile): later ones win."""
    root = root or home()
    marker = root / "logs" / "profile"
    profile = (marker.read_text().strip() if marker.exists() else "") or os.environ.get("PROFILE", "local")
    folder = root / "profiles"
    return [folder / f"{profile}.env", folder / "machine.local.env", folder / f"{profile}.local.env"]


def stamp(root: Path | None = None) -> tuple:
    """What the voice was last read from: a change to any of the files (or to the profile) is a new stamp."""
    root = root or home()
    marker = root / "logs" / "profile"
    from core.downloads import home as downloads_home
    return tuple((str(f), f.stat().st_mtime_ns if f.exists() else 0)
                 for f in [marker, *files(root), downloads_home() / "voice.json"])


def read(keys: tuple = KEYS, whole: bool = False, *, root: Path | None = None, timeout: float = 5) -> dict[str, str] | None:
    """The voice settings the profile gives now (or these keys of it: KEYS_OFF, brain/queen), sourced as ./vx sources
    them ("" for one it leaves unset). whole: None unless every file was read to its end (one that exits early, or that
    bash could not finish, says nothing for certain)."""
    script = ('set -a; for f in "$@"; do [ -f "$f" ] && source "$f"; done; '
              'for k in ' + " ".join(keys) + '; do printf "%s=%s\\0" "$k" "${!k}"; done; printf "__read_whole__\\0"')
    out = subprocess.run(["/bin/bash", "-c", script, "voice", *map(str, files(root))], capture_output=True, text=True,
                         env={"HOME": os.environ.get("HOME", ""), "PATH": "/usr/bin:/bin"}, timeout=timeout).stdout
    if whole and not out.endswith("__read_whole__\0"):
        return None
    values = dict(part.split("=", 1) for part in out.split("\0") if "=" in part)
    if values.get("TTS") == "auto":
        from speech.selection import resolve
        context = read(("SMALL_MAC_TIER", "KEYS_OFF", "XAI_API_KEY_ITEM"), root=root, timeout=timeout)
        values = resolve({**context, **values})
    return {key: values.get(key, "") for key in keys}


def apply(values: dict[str, str]) -> bool:
    """This process speaks with these settings from now on. Whether anything changed."""
    changed = False
    for key, value in values.items():
        if os.environ.get(key, "") != value:
            changed = True
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    return changed


def now() -> bool:
    """Read and apply at once (a call starting, a voice note about to be made). Whether it changed."""
    try:
        return apply(read())
    except (OSError, subprocess.SubprocessError):
        return False


async def follow(changed, every: float = 1.0) -> None:
    """Calls `await changed(values)` whenever the voice the profile gives is not the one this process speaks with."""
    last = await asyncio.to_thread(stamp)
    while True:
        await asyncio.sleep(every)
        stamp_now = await asyncio.to_thread(stamp)
        if stamp_now == last:
            continue
        download_changed = stamp_now[-1] != last[-1]
        last = stamp_now
        try:
            values = await asyncio.to_thread(read)
        except (OSError, subprocess.SubprocessError):
            continue
        if apply(values) or (download_changed and "mlx_local" in (values.get("TTS"), values.get("TTS_FALLBACK"))):
            await changed(values)
