"""Data passed between threads (DESIGN §5 and §9). Stdlib only, so app/logic can import it.

Keep in sync with docs/DESIGN.md and the "Key contracts" block in CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

# Normalized image coordinates (0 to 1): x_min, y_min, x_max, y_max.
BBox = tuple[float, float, float, float]

AlertKind = Literal["distraction", "posture", "test"]

# Vibration pattern IDs (DESIGN §9).
PATTERN_DISTRACTION = 1
PATTERN_POSTURE = 2
PATTERN_ESCALATED = 3
PATTERN_TEST = 4


@dataclass(frozen=True)
class HandInfo:
    bbox: BBox
    grasp: bool          # fingertips curled toward the palm
    near_keyboard: bool  # inside the calibrated work zone


@dataclass(frozen=True)
class Detection:
    cls: str             # COCO class name, e.g. "cell phone"
    confidence: float
    bbox: BBox


@dataclass(frozen=True)
class FrameFeatures:
    t: float                      # seconds since session start
    person_present: bool
    head_yaw: float | None        # degrees, 0 = facing camera
    head_pitch: float | None      # degrees, negative = looking down
    head_roll: float | None
    shoulder_width: float | None  # normalized image units
    shoulder_angle: float | None  # degrees from horizontal
    nose_to_shoulder_y: float | None  # vertical gap, divided by shoulder width
    face_width: float | None      # proxy for distance to screen
    hands: list[HandInfo]
    objects: list[Detection]


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    label: str        # e.g. "phone", "window", "slouching"
    pattern: int      # vibration pattern ID
    created_at: float


class AlertSink(Protocol):
    name: str

    async def available(self) -> bool: ...

    async def send(self, alert: Alert) -> bool: ...  # False = try the next sink
