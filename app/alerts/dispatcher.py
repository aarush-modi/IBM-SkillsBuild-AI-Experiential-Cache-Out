"""Sends each alert to the first sink that takes it (DESIGN §9).

Priority: band stub (never available) -> desktop (ping + notification). A sink that raises,
returns False or takes longer than alerts.sink_timeout_s is skipped. Everything stays on the
computer: no sink sends anything over the network.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from app.contracts import Alert, AlertSink

log = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, sinks: Sequence[AlertSink], timeout_s: float) -> None:
        self.sinks = list(sinks)
        self.timeout_s = timeout_s

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> Dispatcher:
        from app.alerts.ble_band import BleBandSink
        from app.alerts.desktop import DesktopSink

        a = settings["alerts"]
        return cls([BleBandSink(), DesktopSink(ping=a["ping"])], a["sink_timeout_s"])

    async def prepare(self) -> None:
        """Let sinks ask for permissions before the session starts (not timed)."""
        for sink in self.sinks:
            prepare = getattr(sink, "prepare", None)
            if prepare is not None:
                await prepare()

    async def dispatch(self, alert: Alert) -> str | None:
        """Deliver `alert`; returns the name of the sink that took it, or None."""
        for sink in self.sinks:
            try:
                if await asyncio.wait_for(self._try(sink, alert), self.timeout_s):
                    return sink.name
            except TimeoutError:
                log.warning("Alert sink %s took over %.1f s; skipped", sink.name, self.timeout_s)
            except Exception as e:
                log.warning("Alert sink %s failed: %s", sink.name, e)
        log.error("No alert sink delivered %s: %s", alert.kind, alert.label)
        return None

    @staticmethod
    async def _try(sink: AlertSink, alert: Alert) -> bool:
        return await sink.available() and await sink.send(alert)
