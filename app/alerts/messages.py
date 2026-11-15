"""Notification title and text for an Alert (DESIGN §9). Short, and nothing personal."""

from __future__ import annotations

from app.contracts import PATTERN_ESCALATED, Alert
from app.logic.posture import TIPS

DISTRACTION_TEXT: dict[str, str] = {
    "phone": "Phone in hand for a while. Put it away and get back to it.",
    "desk_object": "Fiddling with something on the desk. Back to work?",
    "looking_away": "You've been looking away from the screen. Back to it?",
    "window": "Gazing out the window. Back to work?",
    "away": "You've been away from your desk. Pause the session if you're on a break.",
}


def title(alert: Alert) -> str:
    if alert.kind == "posture":
        return "FocusBand: posture"
    if alert.kind == "test":
        return "FocusBand: test alert"
    return "FocusBand: still distracted" if alert.pattern == PATTERN_ESCALATED else "FocusBand: distraction"


def body(alert: Alert) -> str:
    if alert.kind == "posture":
        return next((tip for issue, tip in TIPS.items() if issue == alert.label), "Check your posture.")
    if alert.kind == "test":
        return "Alerts are working: this is the sound and notification you'll get."
    return DISTRACTION_TEXT.get(alert.label, "You seem distracted. Back to it?")
