"""Light's credential source for a trusted attended Worker supervisor."""
import json
from pathlib import Path

from core import grok_sign_in, provider_switch


def credential(off: Path, *, cached_for: int | None) -> tuple[bytes, bytes]:
    """Prepare or issue access under Light's existing per-user refresh lock."""
    timeout = 0.2 if cached_for is not None else 2
    if provider_switch.turned_off("grok_mind", marker=off, timeout=timeout):
        return b'O', b''
    try:
        # Background requests never wait for rotation or for a prompt.
        access = grok_sign_in.token(cached_for=cached_for)
        expires_in = grok_sign_in.remaining_lifetime(access)
        if expires_in < 5:
            return b'R', b''
    except grok_sign_in.NotSignedIn:
        return b'S', b''
    except (grok_sign_in.Unavailable, OSError, ValueError):
        return b'R', b''
    if provider_switch.turned_off("grok_mind", marker=off, timeout=timeout):
        return b'O', b''
    return b'K', json.dumps({"access_token": access, "expires_in": expires_in}).encode()
