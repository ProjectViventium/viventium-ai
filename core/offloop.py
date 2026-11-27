"""Ordered, disposable status and telemetry work; never conversation history or cleanup."""
import asyncio
import contextvars
import logging
import queue
import threading
from concurrent.futures import Future


class OrderedIO:
    """One lazy daemon per process: submission order survives caller cancellation.

    close() drops queued work. The current operation may finish, but never delays process exit.
    Critical history and shutdown operations must run outside this disposable queue.
    """

    def __init__(self):
        self.pending = queue.Queue()
        self.thread = None
        self.closed = False
        self.lock = threading.Lock()

    def submit(self, function, /, *args, **kwargs):
        future = Future()
        future.add_done_callback(self._report)
        with self.lock:
            if self.closed:
                future.cancel()
                return future
            self.pending.put((future, contextvars.copy_context(), function, args, kwargs))
            if self.thread is None:
                self.thread = threading.Thread(target=self._work, name="call-files", daemon=True)
                self.thread.start()
        return future

    def _work(self):
        while (work := self.pending.get()) is not None:
            future, context, function, args, kwargs = work
            if self.closed:
                future.cancel()
                continue
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(context.run(function, *args, **kwargs))
            except BaseException as error:
                future.set_exception(error)

    def close(self):
        """Called on the submitting loop at hang-up, without waiting for stale disk work."""
        with self.lock:
            if self.closed:
                return
            self.closed = True
            while True:
                try:
                    self.pending.get_nowait()[0].cancel()
                except queue.Empty:
                    break
            self.pending.put(None)

    @staticmethod
    def _report(future):
        if not future.cancelled() and (error := future.exception()) is not None:
            logging.getLogger(__name__).error("call file work failed", exc_info=error)

    async def run(self, function, /, *args, **kwargs):
        # Cancelling a caller must not let a later status overtake an accepted status.
        return await asyncio.shield(asyncio.wrap_future(self.submit(function, *args, **kwargs)))

    async def drain(self):
        await self.run(lambda: None)
