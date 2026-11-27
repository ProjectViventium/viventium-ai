"""Native CLI connection results. Human output never proves a sign-in."""
from enum import Enum


class Connection(str, Enum):
    CONNECTED = "connected"
    SIGNED_OUT = "signed_out"
    UNAVAILABLE = "unavailable"


def connection(harness: str, exit_code: int) -> Connection:
    # Grok Build's `models` lists models, not an authenticated account. It has no supported
    # sign-in status contract. Its Worker uses Light's separate, structured sign-in instead.
    if harness not in ("claude", "claude-code", "codex", "codex-cli"):
        return Connection.UNAVAILABLE
    return {0: Connection.CONNECTED, 1: Connection.SIGNED_OUT}.get(exit_code, Connection.UNAVAILABLE)
