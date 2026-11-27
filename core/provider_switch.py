"""Current provider switches for Light's running consumers."""
import os
import subprocess
from pathlib import Path

from speech import live

_off: dict[Path, tuple[tuple, frozenset[str]]] = {}


def turned_off(name: str, *, marker: Path | None = None, timeout: float = 2) -> bool:
    """A Settings marker wins over the current profile. An unreadable profile fails closed."""
    marker = marker or live.home() / "logs" / f"{name}.off"
    root = marker.parent.parent
    try:
        if marker.exists():
            return True
        stamp = live.stamp(root)
        if not any(modified for _, modified in stamp[1:]):
            return name in os.environ.get("KEYS_OFF", "").split()
        if any(modified and not os.access(path, os.R_OK) for path, modified in stamp[1:]):
            return True
        cached_stamp, names = _off.get(root, (None, frozenset()))
        if stamp != cached_stamp:
            values = live.read(("KEYS_OFF",), whole=True, root=root, timeout=timeout)
            if values is None or stamp != live.stamp(root):
                return True
            names = frozenset(values["KEYS_OFF"].split())
            _off[root] = stamp, names
        return marker.exists() or name in names
    except (OSError, ValueError, subprocess.SubprocessError):
        return True
