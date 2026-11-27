"""Recorded causality only: a native user message id, carried by its own asynchronous tasks."""
from contextlib import contextmanager
from contextvars import ContextVar

current: ContextVar[str] = ContextVar("brain_trace_turn", default="")


@contextmanager
def turn(message_id: str):
    token = current.set(message_id)
    try:
        yield
    finally:
        current.reset(token)


def fields(values: dict) -> dict:
    if source := current.get():
        values.setdefault("turn_id", source)
    return values
