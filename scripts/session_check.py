"""Developer check: run a whole session on the webcam (DESIGN §6 to §8).

Usage: python scripts/session_check.py [--camera N] [--save]
Needs a saved calibration first: python scripts/calibrate_check.py --save
Shows the focus state, alert countdowns and posture. Alerts are delivered for real, as a ping
and a desktop notification (macOS asks for notification permission the first time), and are
also printed in the terminal. With --save, the session, its events (including which sink
delivered each alert) and posture samples are stored in the app database (no images).
Keys: p pause/resume, b break/resume, s snooze/unsnooze, q or Esc end the session.
The camera is released while paused or on a break.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import Future
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.alerts.dispatcher import Dispatcher  # noqa: E402
from app.alerts.runner import AlertRunner  # noqa: E402
from app.contracts import Alert  # noqa: E402
from app.logic.calibration import Calibration, OutdatedCalibration  # noqa: E402
from app.logic.events import EventRecord  # noqa: E402
from app.logic.session import SessionLogic, SessionUpdate  # noqa: E402
from app.storage import settings as settings_mod  # noqa: E402
from app.storage.db import Database  # noqa: E402
from app.storage.recorder import SessionRecorder  # noqa: E402
from app.vision.capture import Camera, CameraError  # noqa: E402
from app.vision.overlay import draw_overlay, posture_line_colors  # noqa: E402
from app.vision.pipeline import VisionPipeline  # noqa: E402
from scripts.camera_check import put_lines  # noqa: E402

WINDOW = "FocusBand session check (q to end)"
SHOW_ALERT_S = 5.0  # dev-tool display time for the last alert
KEYS = "p pause  b break  s snooze  q end"


def mmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def session_lines(u: SessionUpdate, focus_reset_s: float, last_alert: str | None) -> list[str]:
    f = u.focus
    lines = [f"{f.state.upper()}  {f.label or ''}  session {mmss(f.t)}  focused {mmss(f.focus_seconds)}"]
    if f.state == "pending" and f.alert_in_s is not None:
        lines.append(f"alert in {f.alert_in_s:.0f}s unless you refocus ({f.focus_run_s:.0f}/{focus_reset_s:.0f}s)")
    elif f.state == "distracted":
        nxt = "off" if f.next_repeat_in_s is None else f"in {f.next_repeat_in_s:.0f}s"
        lines.append(f"next reminder {nxt} (repeats {f.repeats}), refocus {f.focus_run_s:.0f}/{focus_reset_s:.0f}s")
    if f.snoozed_for_s > 0:
        lines.append(f"Snoozed: alerts muted for {mmss(f.snoozed_for_s)}")
    p = u.posture
    score = "-" if p.score is None else f"{p.score:.0f}"
    lines.append(f"posture {score}" + (f"  {p.tip}" if p.tip else ""))
    if last_alert:
        lines.append(last_alert)
    lines.append(KEYS)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--camera", type=int, help="camera index (default: from settings.json)")
    parser.add_argument("--save", action="store_true", help="store the session in the app database")
    args = parser.parse_args()

    s = settings_mod.load()
    if args.camera is not None:
        s["camera_index"] = args.camera
    db = Database()
    saved = db.latest_calibration()
    if saved is None:
        print("No saved calibration. Run: python scripts/calibrate_check.py --save")
        return 1
    try:
        cal = Calibration.from_dict(saved)
    except OutdatedCalibration:
        print("Your saved calibration is from an older version. Run: python scripts/calibrate_check.py --save")
        return 1

    print("Loading models...")
    pipeline = VisionPipeline.from_settings(s)
    wall_start = time.time()
    logic = SessionLogic(s, cal, wall_start)
    rec = SessionRecorder(db, wall_start) if args.save else None
    cam = Camera.from_settings(s)
    runner = AlertRunner(Dispatcher.from_settings(s))
    try:
        runner.prepare(timeout_s=60)  # macOS shows its notification permission prompt once
    except TimeoutError:
        print("No answer to the notification prompt; pings still play.")
    in_flight: list[tuple[Future[str | None], Alert, int | None]] = []

    def store(events: list[EventRecord]) -> list[int]:
        return rec.events(events) if rec is not None else []

    def collect_deliveries() -> None:
        for item in [x for x in in_flight if x[0].done()]:
            in_flight.remove(item)
            future, alert, event_id = item
            sink = future.result()
            print(f"   {alert.kind}: {alert.label} delivered by {sink or 'nothing'}", flush=True)
            if sink and event_id is not None:
                db.set_alert_sink(event_id, sink)

    last: SessionUpdate | None = None
    alert_text, alert_until = None, 0.0
    try:
        cam.open()
        while True:
            if logic.paused:
                cam.close()  # never keep the camera on while paused
                reason = logic.focus.pause_reason
                img = np.zeros((s["vision"]["capture_height"], s["vision"]["capture_width"], 3), dtype=np.uint8)
                put_lines(img, [f"Paused ({reason}). Camera off.", "Press p or b to resume, q to end"])
                cv2.imshow(WINDOW, img)
                k = cv2.waitKey(100) & 0xFF
                if k in (ord("p"), ord("b")):
                    store(logic.resume())
                    cam.open()
                elif k in (ord("q"), 27):
                    break
                continue

            frame = cam.read()
            if frame is not None:
                features, preview = pipeline.process(frame)
                last = u = logic.update(features)
                ids = store(u.events)
                alert_ids: list[int | None] = [i for i, e in zip(ids, u.events) if e.kind == "alert"]
                if rec is not None and u.sample is not None:
                    rec.sample(u.sample)
                for n, a in enumerate(u.alerts):
                    alert_text = f"ALERT {a.kind}: {a.label} (pattern {a.pattern})"
                    alert_until = time.monotonic() + SHOW_ALERT_S
                    print(f"{mmss(features.t)} {alert_text}", flush=True)
                    in_flight.append((runner.submit(a), a, alert_ids[n] if n < len(alert_ids) else None))
                img = draw_overlay(preview, line_colors=posture_line_colors(u.posture.past_threshold))
                shown = alert_text if time.monotonic() < alert_until else None
                put_lines(img, session_lines(u, s["focus_reset_s"], shown))
                cv2.imshow(WINDOW, img)
            collect_deliveries()

            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), 27):
                break
            if k == ord("p"):
                store(logic.pause("pause"))
            elif k == ord("b"):
                store(logic.pause("break"))
            elif k == ord("s"):
                store(logic.unsnooze() if last and last.focus.snoozed_for_s > 0 else logic.snooze())
    except CameraError as e:
        print(e)
        return 1
    finally:
        store(logic.end())
        if rec is not None:
            rec.finish(logic.last_t, logic.focus.focus_seconds)
            print(f"Session {rec.session_id} saved to {db.path}")
        time.sleep(0.5)  # let a last alert finish
        collect_deliveries()
        runner.close()
        cam.close()
        cv2.destroyAllWindows()
        pipeline.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
