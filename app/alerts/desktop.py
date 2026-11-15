"""Desktop sink (DESIGN §9): a ping plus a desktop notification.

The ping plays first and doesn't depend on notification permission, so the user hears an
alert even if notifications are blocked or in Do Not Disturb. The notification itself is
silent, so the two sounds never overlap.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from desktop_notifier import DesktopNotifier, Urgency

from app.alerts import messages, sounds
from app.contracts import Alert

log = logging.getLogger(__name__)


class DesktopSink:
    name = "desktop"

    def __init__(
        self,
        ping: bool = True,
        notifier: Any = None,
        player: Callable[[int], bool] = sounds.play,
    ) -> None:
        self.ping = ping
        self._notifier = notifier if notifier is not None else DesktopNotifier(app_name="FocusBand")
        self._play = player

    async def prepare(self) -> bool:
        """Ask for notification permission (macOS shows its prompt the first time).
        Call once before a session; returns whether notifications are allowed."""
        try:
            return bool(await self._notifier.request_authorisation())
        except Exception as e:  # a notification backend problem must not stop the session
            log.warning("Notification permission request failed: %s", e)
            return False

    async def available(self) -> bool:
        return True  # the last sink: the ping works even without notification permission

    async def send(self, alert: Alert) -> bool:
        pinged = self.ping and self._play(alert.pattern)
        try:
            await self._notifier.send(
                title=messages.title(alert),
                message=messages.body(alert),
                urgency=Urgency.Normal,
                sound=None,
            )
            return True
        except Exception as e:
            log.warning("Desktop notification failed: %s", e)
            return pinged
