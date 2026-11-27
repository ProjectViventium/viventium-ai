"""One-time owner enrollment from this Mac's Settings, for the connected Telegram bot."""
import asyncio
import fcntl
import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager, contextmanager

from core import jobs
from core.state import STATE_ROOT, private_file

OWNER = STATE_ROOT / "core" / "telegram.json"
START = "/start approve_"


@contextmanager
def _drained(path):
    """Caller holds the owner record's lock: new sends wait while existing requests finish."""
    with private_file(path.with_suffix(".sending.lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


@asynccontextmanager
async def sending(path):
    """Cross-process lease, from the ownership check through the HTTP request's end.

    The record lock is only an entry gate. A writer keeps it while draining sends, so new
    requests cannot extend its wait. Never block the channel's event loop on a file lock.
    """
    with private_file(path.with_suffix(".sending.lock"), "a") as lease:
        with private_file(path.with_suffix(".lock"), "a") as gate:
            while True:
                try:
                    fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(.01)
            fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        yield


def enrolled(owner: dict, bot: str, chat: int | None, sender: int | None) -> bool:
    return (bool(bot) and owner.get("approval_bot") == bot and type(chat) is int and type(sender) is int
            and type(owner.get("chat")) is int and type(owner.get("owner")) is int
            and owner.get("chat") == chat and owner.get("owner") == sender)


def read(path=None) -> dict:
    try:
        owner = json.loads((path or OWNER).read_text())
    except (OSError, ValueError):
        return {}
    return owner if isinstance(owner, dict) else {}


def owns(owner: dict, bot: str, chat: int | None, sender: int | None) -> bool:
    """Owners from before Mac pairing keep their chat. A recorded bot must match."""
    return (bool(bot) and owner.get("approval_bot", bot) == bot
            and type(chat) is int and type(sender) is int
            and type(owner.get("chat")) is int and type(owner.get("owner")) is int
            and (owner["chat"], owner["owner"]) == (chat, sender))


def paired(bot: str) -> bool:
    owner = read()
    return owns(owner, bot, owner.get("chat"), owner.get("owner"))


def revoke() -> None:
    """Only Settings on the Mac can forget the owner and any outstanding code."""
    with jobs._locked(OWNER) as owner:
        with _drained(OWNER):
            for key in ("owner", "chat", "approval_bot", "approval_pair"):
                owner.pop(key, None)
            owner["ownership_revision"] = secrets.token_hex(16)


def ready(bot: str) -> bool:
    owner = read()
    return enrolled(owner, bot, owner.get("chat"), owner.get("owner"))


def begin(bot: str) -> str:
    code = secrets.token_urlsafe(18)
    with jobs._locked(OWNER) as owner:
        owner["approval_pair"] = {"bot": bot, "digest": hashlib.sha256(code.encode()).hexdigest(),
                                  "until": time.time() + 300}
    return code


def pairing_link(bot: str, username: str) -> str:
    return f"https://t.me/{username.lstrip('@')}?start=approve_{begin(bot)}"


def finish(path, bot: str, chat: int, sender: int, code: str) -> bool:
    if not bot or type(chat) is not int or type(sender) is not int or len(code) != 24:
        return False
    digest = hashlib.sha256(code.encode()).hexdigest()
    try:
        with jobs._locked(path) as owner:
            if not isinstance(owner, dict):
                return False
            pair = owner.get("approval_pair") or {}
            if (not isinstance(pair, dict) or pair.get("bot") != bot
                    or not isinstance(pair.get("until"), (int, float)) or not pair["until"] > time.time()
                    or not isinstance(pair.get("digest"), str) or not pair["digest"].isascii()
                    or not hmac.compare_digest(pair["digest"], digest)
                    or (owner.get("owner") is not None
                        and (owner.get("chat"), owner.get("owner")) != (chat, sender))):
                return False
            with _drained(path):
                owner.pop("approval_pair", None)
                owner.update(owner=sender, chat=chat, approval_bot=bot, ownership_revision=secrets.token_hex(16))
            return True
    except (OSError, ValueError):
        return False
