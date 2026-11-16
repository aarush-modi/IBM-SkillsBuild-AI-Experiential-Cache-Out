# FocusBand

A desktop app for Windows and macOS that watches you through your webcam during a work session and lets you know, with a short sound and a notification, when you've been distracted for a minute or your posture has slipped for a couple of minutes.

Everything runs on your computer. No video is saved, and nothing is sent anywhere.

- **Distractions:** phone in hand, looking away (or out of the window), fiddling with objects on the desk, and being away from the desk.
- **Posture:** slouching, leaning in, neck bent down, head tilt and uneven shoulders, all judged against your own calibrated posture.
- **Sessions:** live preview with a skeleton overlay, Pause, Break, Snooze, an optional Pomodoro timer, an end-of-session report and a 7- or 30-day dashboard.

The full design is in [docs/DESIGN.md](docs/DESIGN.md).

## Requirements

- Python 3.12 or 3.13.
- A webcam at the top of your screen, facing you, with your head and both shoulders in view.
- macOS 13 or later on Apple Silicon, or Windows 10/11. MediaPipe has no build for Intel Macs.

## Set up and run

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/download_models.py    # about 22 MB; checked against pinned SHA-256 hashes
python -m app.main
```

The first run shows a consent screen, then a 15-second calibration: sit the way you'd like to work. On macOS, allow camera access for your terminal or editor, and allow notifications when asked.

## Using it

1. **Start session** on the Home page. Tick **Pomodoro** for 25-minute focus blocks with 5-minute breaks.
2. If you're distracted for a minute, you get a ping and a notification. Look back at your screen for 5 seconds to clear it.
3. **Pause** or **Break** turns the camera off. **Snooze** silences alerts for 10 minutes.
4. **End session** shows your report. The **Dashboard** on Home shows the last 7 or 30 days.
5. **Settings** has the timings, alert sound, camera choice, data retention and **Delete my data**.

## Developer tools

All are run from the project folder, inside the virtual environment.

| Command | What it does |
| --- | --- |
| `pytest tests/unit` | Unit tests, about 10 s; no camera or models needed |
| `mypy` | Strict type check |
| `python scripts/camera_check.py [--features]` | Live camera feed; with `--features`, the vision pipeline's output |
| `python scripts/calibrate_check.py [--save]` | Calibration in an OpenCV window |
| `python scripts/detect_check.py` | The four distraction detectors, live |
| `python scripts/posture_check.py` | Posture score, penalties and tips, live |
| `python scripts/session_check.py [--save]` | A whole session with real alerts |
| `python scripts/alert_check.py [--all]` | The alert pings and notifications, no camera needed |
| `FOCUSBAND_DEV_RECORDER=1 python scripts/record_clip.py NAME --behaviour phone` | Record a consented test clip into `tests/clips/` (see DESIGN §12) |
| `python tests/eval.py` | Score the detectors on the recorded clips against the acceptance criteria |
| `python scripts/build_app.py` | Build the packaged app for this OS (see below) |

## Building the app

```bash
pip install -r requirements.txt
python scripts/download_models.py
python scripts/build_app.py
```

Build on each operating system for that system. macOS produces `dist/FocusBand.app`; Windows produces `dist/FocusBand/FocusBand.exe`. The script bundles the models, checks the result with `--smoke-test` (loads the models without opening the camera) and, on macOS, signs the app ad hoc.

The app is not notarised, so the first time you open it on macOS, right-click it and choose **Open**. It is large (about 1.1 GB on macOS), mostly because of PyTorch, which the object detector depends on.

## Privacy

- Frames are processed in memory and never written to disk. The only exception is the developer clip recorder, which runs only with `FOCUSBAND_DEV_RECORDER=1`.
- The app makes no network requests while it runs. The only download is the one-off model download script.
- Session times, events, posture scores and your calibration are kept in a small SQLite file in your user folder (`~/Library/Application Support/FocusBand` on macOS, `%APPDATA%\FocusBand` on Windows). **Settings → Delete my data** removes it all.

## Licences

The object detector is Ultralytics YOLO26n, licensed AGPL-3.0, which is fine for this school project. A commercial product would need an Ultralytics licence.
