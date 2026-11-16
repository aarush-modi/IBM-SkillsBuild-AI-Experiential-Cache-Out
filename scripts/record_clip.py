"""Developer-only clip recorder for replay evaluation (DESIGN §12). Off unless
FOCUSBAND_DEV_RECORDER=1 is set: this is the only code that writes camera frames to disk.

Usage:
  FOCUSBAND_DEV_RECORDER=1 python scripts/record_clip.py NAME --behaviour phone [--seconds 180]

Records exactly what the app sees (mirrored, capture size) into the git-ignored tests/clips/
as NAME.mp4. Sit upright facing the screen for the first 15 s: eval.py calibrates from that.
Press Space to mark when the behaviour starts and again when it stops; each interval is
appended to tests/clips/labels.csv. Press q or Esc to stop early. Only record people who have
agreed to it, keep clips off shared drives, and delete them after the project.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from app.storage import settings as settings_mod  # noqa: E402
from app.vision.capture import Camera, CameraError  # noqa: E402
from scripts.camera_check import put_lines  # noqa: E402

FLAG = "FOCUSBAND_DEV_RECORDER"
CLIPS_DIR = Path(__file__).resolve().parents[1] / "tests" / "clips"
LABELS = CLIPS_DIR / "labels.csv"
BEHAVIOURS = ("phone", "looking_away", "window", "desk_object", "away", "slouching", "leaning_in",
              "focused", "window_calibration")
CALIBRATION_S = 15.0  # matches eval.py: the upright opening of every clip
COUNTDOWN_S = 3.0
WINDOW = "FocusBand clip recorder (Space marks the behaviour, q stops)"


def append_label(clip: str, behaviour: str, start: float, end: float) -> None:
    new = not LABELS.exists()
    with LABELS.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["clip", "behaviour", "start_s", "end_s"])
        w.writerow([clip, behaviour, f"{start:.1f}", f"{end:.1f}"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="clip file name without extension, e.g. alex_phone_daylight")
    parser.add_argument("--behaviour", required=True, choices=BEHAVIOURS, help="what Space marks")
    parser.add_argument("--seconds", type=float, default=180.0, help="clip length (default 180)")
    parser.add_argument("--camera", type=int, help="camera index (default: from settings.json)")
    args = parser.parse_args()

    if os.environ.get(FLAG) != "1":
        print(f"Recording is off. It writes camera video to disk, so it only runs with {FLAG}=1 set.")
        return 2
    answer = input("Has everyone who will be in view agreed to be recorded for testing? [y/N] ")
    if answer.strip().lower() not in ("y", "yes"):
        print("Not recording.")
        return 1

    s = settings_mod.load()
    if args.camera is not None:
        s["camera_index"] = args.camera
    v = s["vision"]
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLIPS_DIR / f"{args.name}.mp4"
    if path.exists():
        print(f"{path} already exists; choose another name.")
        return 1

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), v["capture_fps"],
                             (v["capture_width"], v["capture_height"]))
    marked_from: float | None = None
    marks = 0
    try:
        with Camera.from_settings(s) as cam:
            t_start = time.monotonic() + COUNTDOWN_S
            first_ts: int | None = None
            while True:
                frame = cam.read()
                now = time.monotonic()
                k = cv2.waitKey(1) & 0xFF
                if frame is None:
                    continue
                show = frame.image.copy()
                if now < t_start:
                    put_lines(show, [f"Recording starts in {t_start - now:.0f}...",
                                     "Sit upright and look at the screen"])
                    cv2.imshow(WINDOW, show)
                    continue
                if first_ts is None:
                    first_ts = frame.timestamp_ms
                t = (frame.timestamp_ms - first_ts) / 1000
                writer.write(frame.image)  # the clean frame; prompts are only on the preview
                if k == ord(" ") and t >= CALIBRATION_S:
                    if marked_from is None:
                        marked_from = t
                    else:
                        append_label(args.name, args.behaviour, marked_from, t)
                        marks += 1
                        marked_from = None
                if t < CALIBRATION_S:
                    lines = [f"Calibration: sit upright, look at the screen ({CALIBRATION_S - t:.0f}s)"]
                else:
                    state = f"MARKING {args.behaviour} since {marked_from:.0f}s" if marked_from is not None \
                        else f"Space = start {args.behaviour}"
                    lines = [f"REC {t:.0f}/{args.seconds:.0f}s", state]
                put_lines(show, lines)
                cv2.imshow(WINDOW, show)
                if t >= args.seconds or k in (ord("q"), 27):
                    if marked_from is not None:
                        append_label(args.name, args.behaviour, marked_from, t)
                        marks += 1
                    break
    except CameraError as e:
        print(e)
        return 1
    finally:
        writer.release()
        cv2.destroyAllWindows()
    print(f"Saved {path} with {marks} labelled {args.behaviour} interval(s) in {LABELS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
