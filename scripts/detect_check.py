"""Developer check: run the four distraction detectors live on the webcam (DESIGN §6).

Usage: python scripts/detect_check.py [--camera N]
Needs a saved calibration first: python scripts/calibrate_check.py --save
Shows each detector's raw signal (this frame) and smoothed state, the current label, the
away clock and the head turn from your baseline. No alerts are sent: the 60 s hold and
alerting belong to the state machine (section 8). Press q or Esc to quit. Nothing is saved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.contracts import FrameFeatures  # noqa: E402
from app.logic.calibration import Calibration  # noqa: E402
from app.logic.detectors import DetectorState, Detectors, RawSignals  # noqa: E402
from app.storage import settings as settings_mod  # noqa: E402
from app.storage.db import Database  # noqa: E402
from app.vision.capture import Camera, CameraError  # noqa: E402
from app.vision.overlay import draw_overlay  # noqa: E402
from app.vision.pipeline import VisionPipeline  # noqa: E402
from scripts.camera_check import put_lines  # noqa: E402

WINDOW = "FocusBand detector check (q to quit)"


def _mark(raw: bool, on: bool) -> str:
    return ("ON " if on else "off") + (" (now)" if raw and not on else "")


def detector_lines(f: FrameFeatures, raw: RawSignals, state: DetectorState, cal: Calibration, away_s: float) -> list[str]:
    b = cal.baseline
    yaw = "-" if f.head_yaw is None else f"{f.head_yaw - b.head_yaw:+.0f}d"
    pitch = "-" if f.head_pitch is None else f"{f.head_pitch - b.head_pitch:+.0f}d"
    window = "window " + ("yes" if state.window else "no") if cal.window_yaw is not None else "window not calibrated"
    return [
        f"Distraction: {state.label or 'none (focused)'}",
        f"phone       {_mark(raw.phone, state.phone)}",
        f"desk object {_mark(raw.desk_object, state.desk_object)}",
        f"looking away {_mark(raw.looking_away, state.looking_away)}  {window}",
        f"away        {'ON ' if state.away else 'off'}  absent {state.away_for_s:.0f}s / {away_s:.0f}s",
        f"head turn {yaw}  pitch {pitch} from baseline  hands {len(f.hands)}"
        f" ({', '.join('grasp' if h.grasp else 'open' for h in f.hands) or '-'})",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--camera", type=int, help="camera index (default: from settings.json)")
    args = parser.parse_args()

    s = settings_mod.load()
    if args.camera is not None:
        s["camera_index"] = args.camera
    with Database() as db:
        saved = db.latest_calibration()
    if saved is None:
        print("No saved calibration. Run: python scripts/calibrate_check.py --save")
        return 1
    cal = Calibration.from_dict(saved)
    detectors = Detectors(s, cal)

    print("Loading models...")
    pipeline = VisionPipeline.from_settings(s)
    try:
        with Camera.from_settings(s) as cam:
            while True:
                frame = cam.read()
                if frame is not None:
                    features, preview = pipeline.process(frame)
                    state = detectors.update(features)
                    assert detectors.last_raw is not None
                    img = draw_overlay(preview)
                    if features.face_bbox is not None:
                        h, w = img.shape[:2]
                        x0, y0, x1, y1 = features.face_bbox
                        cv2.rectangle(img, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (200, 200, 200), 1)
                    put_lines(img, detector_lines(features, detectors.last_raw, state, cal, s["away_detect_s"]))
                    cv2.imshow(WINDOW, img)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except CameraError as e:
        print(e)
        return 1
    finally:
        cv2.destroyAllWindows()
        pipeline.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
