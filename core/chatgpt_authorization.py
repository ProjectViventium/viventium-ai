"""Admission for one attended ChatGPT plan turn."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps

from core import chatgpt_sign_in as sign_in


class Purpose(StrEnum):
    TURN = "turn"
    FIRST_GREETING = "first_greeting"
    LIVE_GREETING = "live_greeting"
    GREETING = "greeting"
    ROUNDS = "rounds"
    HELPERS = "helpers"
    COORDINATOR = "coordinator"
    WORKERS = "workers"


ATTENDED = (Purpose.TURN, Purpose.FIRST_GREETING, Purpose.LIVE_GREETING)


@dataclass(frozen=True)
class Admission:
    purpose: Purpose
    account: str = ""
    session: str = ""
    revision: str = ""
    denied: str = ""


def capture(purpose, *, attended=False):
    """Only the attended entry points can admit work. Helpers borrow the turn."""
    if not attended or purpose not in ATTENDED:
        return Admission(purpose, denied="authorization_required")
    try:
        account, kept = sign_in.connection._selected(sign_in.connection._read())
        return Admission(purpose, account, kept["session"], kept.get("revision", ""))
    except sign_in.SignInError as error:
        return Admission(purpose, denied=sign_in.stop_state(error))
    except (OSError, ValueError):
        return Admission(purpose, denied="unavailable")


def require(approval, purposes):
    if (not isinstance(approval, Admission) or not isinstance(approval.purpose, Purpose)
            or approval.purpose not in ATTENDED or approval.purpose not in purposes):
        raise sign_in.NotSignedIn("authorization_required")
    if approval.denied:
        raise sign_in.NotSignedIn(approval.denied)
    try:
        account, kept = sign_in.connection._selected(sign_in.connection._read())
    except (OSError, ValueError):
        raise sign_in.NotSignedIn("unavailable") from None
    if (account, kept["session"], kept.get("revision", "")) != (approval.account, approval.session, approval.revision):
        raise sign_in.NotSignedIn("stale_session")
    return approval


current = ContextVar("chatgpt_plan_admission", default=None)


@contextmanager
def use(approval):
    mark = current.set(approval)
    try:
        yield
    finally:
        current.reset(mark)


def unattended(run):
    """Background tasks can inherit the caller's context. Clear its admission."""
    @wraps(run)
    async def work(*args, **kwargs):
        with use(None):
            return await run(*args, **kwargs)
    return work
