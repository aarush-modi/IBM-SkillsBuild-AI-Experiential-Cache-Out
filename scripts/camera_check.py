"""Developer check: open the camera with the app's settings and show the mirrored feed with FPS.

Usage: python scripts/camera_check.py [--camera N] [--features]
With --features, also runs the full vision pipeline (MediaPipe + YOLO) and shows the
skeleton, hands, object boxes, live FrameFeatures values and model time per frame.
Press q or Esc to quit. Nothing is saved to disk.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import numpy.typing as npt  # noqa: E402

from app.contracts import FrameFeatures  # noqa: E402
from app.storage import settings as settings_mod  # noqa: E402
from app.vision.capture import Camera, CameraError, list_cameras  # noqa: E402

WINDOW = "FocusBand camera check (q to quit)"


def _fmt(v: float | None, unit: str = "") -> str:
    return "-" if v is None else f"{v:+.2f}{unit}"


def feature_lines(f: FrameFeatures) -> list[str]:
    grasp = ",".join(("grasp" if h.grasp else "open") + ("/kb" if h.near_keyboard else "") for h in f.hands)
    return [
        f"present {f.person_present}  shoulder vis {_fmt(f.shoulder_visibility)}",
        f"yaw {_fmt(f.head_yaw, 'd')}  pitch {_fmt(f.head_pitch, 'd')}  roll {_fmt(f.head_roll, 'd')}",
        f"shoulder w {_fmt(f.shoulder_width)}  angle {_fmt(f.shoulder_angle, 'd')}",
        f"nose-shoulder {_fmt(f.nose_to_shoulder_y)}  face w {_fmt(f.face_width)}",
        f"hands {len(f.hands)} [{grasp}]  objects {', '.join(d.cls for d in f.objects) or '-'}",
    ]


FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.5
LINE_H = 20
PAD = 8


def put_lines(img: npt.NDArray[np.uint8], lines: list[str]) -> None:
    """Text on a translucent dark panel in the top-left corner, so it reads on any background."""
    if not lines:
        return
    width = max(cv2.getTextSize(t, FONT, FONT_SCALE, 1)[0][0] for t in lines)
    x0, y0 = 6, 6
    x1 = min(img.shape[1], x0 + width + 2 * PAD)
    y1 = min(img.shape[0], y0 + LINE_H * len(lines) + PAD)
    panel = img[y0:y1, x0:x1]
    panel[:] = (panel * 0.45).astype(np.uint8)  # darken in place, about 55% black
    for n, text in enumerate(lines):
        y = y0 + PAD + 10 + LINE_H * n
        cv2.putText(img, text, (x0 + PAD, y), FONT, FONT_SCALE, (235, 235, 235), 1, cv2.LINE_AA)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--camera", type=int, help="camera index (default: from settings.json)")
    parser.add_argument("--features", action="store_true", help="run the vision pipeline and show features")
    args = parser.parse_args()

    s = settings_mod.load()
    if args.camera is not None:
        s["camera_index"] = args.camera
    print("Cameras found:", list_cameras() or "none")

    pipeline = None
    if args.features:
        from app.vision.overlay import draw_overlay
        from app.vision.pipeline import VisionPipeline

        print("Loading models...")
        pipeline = VisionPipeline.from_settings(s)  # before the camera opens, per DESIGN §5

    try:
        with Camera.from_settings(s) as cam:
            frames, t0, fps, avg_ms = 0, time.monotonic(), 0.0, 0.0
            while True:
                frame = cam.read()  # raises CameraError if the camera stops responding
                if frame is not None:
                    frames += 1
                    if (elapsed := time.monotonic() - t0) >= 1.0:
                        fps, frames, t0 = frames / elapsed, 0, time.monotonic()
                    if pipeline is not None:
                        features, preview = pipeline.process(frame)
                        avg_ms = preview.process_ms if avg_ms == 0 else 0.9 * avg_ms + 0.1 * preview.process_ms
                        img = draw_overlay(preview)
                        put_lines(img, [f"{fps:.1f} fps  models {avg_ms:.0f} ms/frame"] + feature_lines(features))
                    else:
                        img = frame.image.copy()
                        put_lines(img, [f"{fps:.1f} fps"])
                    cv2.imshow(WINDOW, img)
                # Always poll keys, even when no frame arrived, so q/Esc keep working.
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except CameraError as e:
        print(e)
        return 1
    finally:
        cv2.destroyAllWindows()
        if pipeline is not None:
            pipeline.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
