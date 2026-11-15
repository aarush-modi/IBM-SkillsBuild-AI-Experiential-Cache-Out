"""Developer check: run the calibration steps on the webcam, then show live values
relative to the new baseline. A stand-in for the Qt wizard (DESIGN §7 and §10).

Usage: python scripts/calibrate_check.py [--camera N] [--save]
If a calibration is already saved, it first runs the camera-moved check against it.
With --save, the new calibration is stored in the app database (values only, no images).
Keys: r retry a failed step, s skip the window step, q or Esc quit. Nothing else is saved.
The terminal bell rings when each step finishes.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.contracts import FrameFeatures  # noqa: E402
from app.logic import calibration as C  # noqa: E402
from app.storage import settings as settings_mod  # noqa: E402
from app.storage.db import Database  # noqa: E402
from app.vision.capture import Camera, CameraError  # noqa: E402
from app.vision.overlay import draw_overlay  # noqa: E402
from app.vision.pipeline import VisionPipeline  # noqa: E402
from scripts.camera_check import put_lines  # noqa: E402

WINDOW = "FocusBand calibration check (q to quit)"
GET_READY_S = 3.0  # dev-tool countdown before each step
SHOW_RESULT_S = 2.0
WRAP = 52  # characters per overlay line at 640 px wide

INSTRUCTIONS = {
    "shift": "Sit as you normally do: checking whether the camera moved",
    "upright": "Sit tall, shoulders back, look at your screen",
    "window": "Turn your head toward your window (s to skip)",
}


def _d(v: float | None, base: float, unit: str = "d") -> str:
    return "-" if v is None else f"{v - base:+.1f}{unit}"


def _pct(v: float | None, base: float) -> str:
    return "-" if v is None or base == 0 else f"{100 * (v - base) / base:+.0f}%"


def live_lines(f: FrameFeatures, cal: C.Calibration) -> list[str]:
    b = cal.baseline
    window = f"{cal.window_yaw - b.head_yaw:+.0f}d" if cal.window_yaw is not None else "skipped"
    return [
        "Calibrated. Change from baseline:",
        f"yaw {_d(f.head_yaw, b.head_yaw)}  pitch {_d(f.head_pitch, b.head_pitch)}  roll {_d(f.head_roll, b.head_roll)}",
        f"nose-shoulder gap {_pct(f.nose_to_shoulder_y, b.nose_to_shoulder_y)}  face width {_pct(f.face_width, b.face_width)}",
        f"shoulder angle {_d(f.shoulder_angle, b.shoulder_angle)}  window at {window}",
    ]


class Wizard:
    """Steps through shift check (if any) -> upright -> window -> live."""

    def __init__(self, settings: dict[str, Any], existing: C.Calibration | None) -> None:
        self.s = settings
        self.existing = existing
        self.phases = (["shift"] if existing else []) + ["upright", "window"]
        self.index = 0
        self.baseline: C.Baseline | None = None
        self.window_yaw: float | None = None
        self.last: FrameFeatures | None = None
        self.calibration: C.Calibration | None = None
        self._begin()

    @property
    def phase(self) -> str:
        return self.phases[self.index] if self.index < len(self.phases) else "live"

    def _begin(self) -> None:
        self.step: C._Step[Any] | None = None
        self.result: C.StepResult[Any] | None = None
        self.ready_until = time.monotonic() + GET_READY_S
        self.result_at = 0.0

    def _new_step(self) -> C._Step[Any]:
        if self.phase == "shift":
            assert self.existing is not None
            return C.CameraShiftCheck(self.s, self.existing.baseline)
        if self.phase == "upright":
            return C.UprightStep(self.s)
        assert self.phase == "window" and self.baseline is not None
        return C.WindowStep(self.s, self.baseline)

    def _advance(self) -> None:
        self.index += 1
        if self.phase == "live":
            assert self.baseline is not None
            self.calibration = C.Calibration(self.baseline, self.window_yaw)
        else:
            self._begin()

    def feed(self, f: FrameFeatures) -> None:
        self.last = f
        if self.phase == "live" or self.result is not None:
            if self.result is not None and self.result.passed and time.monotonic() - self.result_at > SHOW_RESULT_S:
                self._advance()
            elif self.phase == "shift" and self.result is not None and time.monotonic() - self.result_at > SHOW_RESULT_S:
                self._advance()  # inconclusive shift check: carry on anyway
            return
        if time.monotonic() < self.ready_until:
            return
        if self.step is None:
            self.step = self._new_step()
        self.step.add(f)
        if self.step.done():
            self.result = self.step.result()
            self.result_at = time.monotonic()
            print("\a", end="", flush=True)  # terminal bell: done, no need to look at the screen
            if self.result.passed:
                if self.phase == "upright":
                    self.baseline = self.result.value
                elif self.phase == "window":
                    self.window_yaw = self.result.value

    def key(self, k: int) -> None:
        if self.result is not None and not self.result.passed and k == ord("r"):
            self._begin()
        elif self.phase == "window" and k == ord("s"):
            self.window_yaw = None
            self._advance()

    def turn_line(self) -> str:
        """Live head turn from the screen baseline, so a failing window step can be diagnosed."""
        needed = self.s["detectors"]["look_yaw_deg"]
        yaw = self.last.head_yaw if self.last else None
        if yaw is None or self.baseline is None:
            return f"Head turn now: no face found (needs over {needed:.0f}d)"
        return f"Head turn now: {yaw - self.baseline.head_yaw:+.0f}d from screen (needs over {needed:.0f}d)"

    def lines(self) -> list[str]:
        p = self.phase
        head = f"Step {self.index + 1}/{len(self.phases)}: {INSTRUCTIONS[p]}"
        if p == "window":
            return self._lines(p, head) + [self.turn_line()]
        return self._lines(p, head)

    def _lines(self, p: str, head: str) -> list[str]:
        if self.result is not None:
            if p == "shift":
                moved = self.result.value
                msg = ("Camera seems to have MOVED: recalibrate" if moved else "Camera position OK") \
                    if self.result.passed else f"Couldn't tell: {self.result.reason}"
                return [head, *textwrap.wrap(msg, WRAP)]
            if self.result.passed:
                return [head, "PASS"]
            retry = textwrap.wrap(f"RETRY: {self.result.reason}", WRAP)
            return [head, *retry, "Press r to retry" + (", s to skip" if p == "window" else "")]
        if time.monotonic() < self.ready_until:
            return [head, f"Starting in {self.ready_until - time.monotonic():.0f}..."]
        if isinstance(self.step, C.WindowStep) and self.step.waiting:
            return [head, "Turn your head toward the window and hold it"]
        progress = self.step.progress if self.step else 0.0
        return [head, f"Hold still... {progress * 100:.0f}%"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--camera", type=int, help="camera index (default: from settings.json)")
    parser.add_argument("--save", action="store_true", help="store the new calibration in the app database")
    args = parser.parse_args()

    s = settings_mod.load()
    if args.camera is not None:
        s["camera_index"] = args.camera

    db = Database()
    saved = db.latest_calibration()
    try:
        existing = C.Calibration.from_dict(saved) if saved else None
    except C.OutdatedCalibration:
        existing = None  # older version: skip the camera-moved check; this run replaces it
        print("Saved calibration is from an older version; this run replaces it (use --save).")
    print("Loading models...")
    pipeline = VisionPipeline.from_settings(s)
    wizard = Wizard(s, existing)
    stored = False

    try:
        with Camera.from_settings(s) as cam:
            while True:
                frame = cam.read()
                if frame is not None:
                    features, preview = pipeline.process(frame)
                    wizard.feed(features)
                    img = draw_overlay(preview)
                    cal = wizard.calibration
                    if cal is not None:
                        if args.save and not stored:
                            db.save_calibration(cal.to_dict())
                            stored = True
                            print("Calibration saved to", db.path)
                        put_lines(img, live_lines(features, cal))
                    else:
                        put_lines(img, wizard.lines())
                    cv2.imshow(WINDOW, img)
                k = cv2.waitKey(1) & 0xFF
                if k in (ord("q"), 27):
                    break
                wizard.key(k)
    except CameraError as e:
        print(e)
        return 1
    finally:
        cv2.destroyAllWindows()
        pipeline.close()
        db.close()
    if wizard.calibration is not None and not args.save:
        print("Not saved (run with --save to store it).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
