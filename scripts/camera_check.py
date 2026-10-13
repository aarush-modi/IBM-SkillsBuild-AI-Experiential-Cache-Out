"""Developer check: open the camera with the app's settings and show the mirrored feed with FPS.

Usage: python scripts/camera_check.py [--camera N]
Press q or Esc to quit. Nothing is saved to disk.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.storage import settings as settings_mod  # noqa: E402
from app.vision.capture import Camera, CameraError, list_cameras  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--camera", type=int, help="camera index (default: from settings.json)")
    args = parser.parse_args()

    s = settings_mod.load()
    if args.camera is not None:
        s["camera_index"] = args.camera
    print("Cameras found:", list_cameras() or "none")

    try:
        with Camera.from_settings(s) as cam:
            frames, t0, fps = 0, time.monotonic(), 0.0
            while True:
                frame = cam.read()
                if frame is None:
                    continue
                frames += 1
                if (elapsed := time.monotonic() - t0) >= 1.0:
                    fps, frames, t0 = frames / elapsed, 0, time.monotonic()
                img = frame.image.copy()
                cv2.putText(img, f"{fps:.1f} fps", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.imshow("FocusBand camera check (q to quit)", img)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except CameraError as e:
        print(e)
        return 1
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
