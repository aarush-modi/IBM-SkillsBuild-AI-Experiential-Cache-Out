"""BLE band sink stub (DESIGN §9): shows where the band would plug in. Never sends.

The band is a design concept only. available() is always False, so the dispatcher moves
straight on to the next sink. Do not add a real BLE connection here unless asked.
"""

from __future__ import annotations

from app.contracts import Alert


class BleBandSink:
    name = "band"

    async def available(self) -> bool:
        return False

    async def send(self, alert: Alert) -> bool:
        return False
