"""Runs the alert dispatcher on its own asyncio loop in a background thread.

Synchronous code (the logic loop, the check scripts) calls submit() and carries on; the
returned future resolves to the sink name that delivered the alert, or None. Results are
read back on the caller's thread, so the database is only ever touched there.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from types import TracebackType

from app.alerts.dispatcher import Dispatcher
from app.contracts import Alert


class AlertRunner:
    def __init__(self, dispatcher: Dispatcher) -> None:
        self.dispatcher = dispatcher
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="alerts", daemon=True)
        self._thread.start()

    def prepare(self, timeout_s: float | None = None) -> None:
        """Ask sinks for permissions (e.g. the macOS notification prompt). Blocks until done."""
        asyncio.run_coroutine_threadsafe(self.dispatcher.prepare(), self._loop).result(timeout_s)

    def submit(self, alert: Alert) -> Future[str | None]:
        return asyncio.run_coroutine_threadsafe(self.dispatcher.dispatch(alert), self._loop)

    def close(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        if not self._loop.is_running():
            self._loop.close()

    def __enter__(self) -> AlertRunner:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
