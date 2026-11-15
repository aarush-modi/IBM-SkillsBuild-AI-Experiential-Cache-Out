"""Developer check: live posture score, per-issue penalties, tip and alert timing (DESIGN §7).

Usage: python scripts/posture_check.py [--camera N]
Needs a saved calibration first: python scripts/calibrate_check.py --save
Skeleton lines turn amber for issues past their threshold. Seconds while you're away or
looking away are not scored. "ALERT" shows when a posture alert would be sent; nothing is
actually sent. Press q or Esc to quit. Nothing is saved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.logic.calibration import Calibration, OutdatedCalibration  # noqa: E402
from app.logic.detectors import Detectors  # noqa: E402
from app.logic.posture import ISSUES, PostureTracker, PostureUpdate  # noqa: E402
from app.storage import settings as settings_mod  # noqa: E402
from app.storage.db import Database  # noqa: E402
from app.vision.capture import Camera, CameraError  # noqa: E402
from app.vision.overlay import draw_overlay, posture_line_colors  # noqa: E402
from app.vision.pipeline import VisionPipeline  # noqa: E402
from scripts.camera_check import put_lines  # noqa: E402

WINDOW = "FocusBand posture check (q to quit)"
SHOW_ALERT_S = 5.0  # dev-tool display time for the ALERT line

SHORT = {"slouching": "slouch", "leaning_in": "lean", "neck_down": "neck", "head_tilt": "tilt",
         "uneven_shoulders": "shoulders"}


def posture_lines(u: PostureUpdate, s: dict[str, Any], alert_shown_until: float) -> list[str]:
    p = s["posture"]
    score = "not scored" if u.score is None else f"{u.score:.0f}"
    pens = "  ".join(
        f"{SHORT[i]} {u.penalties[i]:.2f}" + ("!" if i in u.past_threshold else "")
        for i in ISSUES
    ) if u.penalties is not None else "away or looking away: not scored"
    lines = [
        f"Posture score {score}  (bad under {p['bad_score']})",
        pens,
        f"bad seconds {u.bad_seconds}/{p['bad_window_s']} (need {p['bad_ratio'] * p['bad_window_s']:.0f})"
        f"  {'BAD' if u.bad else 'ok'}",
    ]
    if u.bad:
        lines.append(f"bad for {u.bad_for_s:.0f}s / {s['posture_threshold_s']}s until alert")
        lines.append(f"Tip: {u.tip}")
    if u.t < alert_shown_until:
        lines.append(f"ALERT: posture ({u.worst_issue})")
    return lines


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
    try:
        cal = Calibration.from_dict(saved)
    except OutdatedCalibration:
        print("Your saved calibration is from an older version. Run: python scripts/calibrate_check.py --save")
        return 1
    detectors = Detectors(s, cal)
    posture = PostureTracker(s, cal.baseline)

    print("Loading models...")
    pipeline = VisionPipeline.from_settings(s)
    alert_until = -1.0
    try:
        with Camera.from_settings(s) as cam:
            while True:
                frame = cam.read()
                if frame is not None:
                    features, preview = pipeline.process(frame)
                    state = detectors.update(features)
                    u = posture.update(features, state, distraction_alert_active=False)
                    if u.alert:
                        alert_until = u.t + SHOW_ALERT_S
                        print(f"{u.t:.0f}s posture alert: {u.worst_issue}")
                    if u.sample is not None:
                        score = "-" if u.sample.score is None else f"{u.sample.score:.0f}"
                        print(f"sample t={u.sample.t}s score={score} worst={u.sample.worst_issue}")
                    img = draw_overlay(preview, line_colors=posture_line_colors(u.past_threshold))
                    put_lines(img, posture_lines(u, s, alert_until))
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
