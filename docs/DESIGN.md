# FocusBand — Software Design Document

Last updated Oct 12, 2026

## 1. Overview

FocusBand (working name) is a Python desktop app for Windows and macOS. It watches the user through their webcam during a study or work session, detects distraction and poor posture entirely on-device, and alerts them after 1 minute of sustained distraction — on their Apple Watch, or with a desktop notification. The team builds it with IBM Bob as the AI development platform; Bob is a dev tool here, not part of the running app.

**Goals for the 2-week build**

- Detect four distractions: phone use, looking away (including out the window), handling desk objects, and being away from the desk.
- Score posture against a personal calibrated baseline and coach the user with buzzes, on-screen tips, a live skeleton overlay and an end-of-session report.
- Deliver each alert to the best available device: a paired Apple Watch, or a desktop notification when no watch is paired.
- Present the custom BLE band as a designed concept: its protocol is specified (section 9) and a stub sink shows where it plugs in, but it does not need to work.
- Keep all video on the user's computer.

**Non-goals**

- Supervisor, employer or parent monitoring; the user is the only person who sees their data.
- A working band. The hardware team designs and presents it, but there is no firmware and the desktop app never connects to it.
- Medical or ergonomic diagnosis; posture tips are general guidance.
- A phone app, beyond what the watch route needs.

**Priorities**

| Priority | Scope | Why this tier |
| --- | --- | --- |
| P0, must ship | Webcam pipeline, four distraction detectors, posture scoring, calibration, session timer, live overlay, on-screen tips, desktop notifications | The core demo works with no wrist device at all |
| P1, should ship | End-of-session report, stats history dashboard, band stub sink | The report and dashboard reuse stored events; the band stub is small and shows the band design |
| P2, after the freeze | Apple Watch alerts via ntfy — **required for the final demo** | The desktop publishes to a private ntfy.sh topic and the iPhone ntfy app mirrors it to the watch; no accounts, no cost, no watch code |
| Stretch | Custom Apple Watch app with FocusBand vibration patterns; Wear OS via the ntfy Android app | Only after the ntfy route works |

## 2. Users and privacy

One person runs the app on themselves, and only they see the results. Because the camera watches someone for hours, privacy is a design rule, not a setting.

- **No video is stored.** Frames are processed in memory and dropped. The release build has no code path that writes frames to disk. A developer-only debug recorder exists behind the `FOCUSBAND_DEV_RECORDER` build flag and is off in release.
- **What is stored:** session times, distraction events (type, start, end), posture scores and calibration values, in a local SQLite file in the user's app data folder.
- **What leaves the computer:** only when a watch is paired, a small alert message (type, label, pattern, timestamp; no images, no names) is published to the user's private topic on the public ntfy.sh server. The topic is a long random name that acts as the secret; anyone who knows it can read the alerts, so it is stored in the OS keychain and shown only on the pairing screen.
- **The camera is only on during a session.** The session screen shows a clear "camera on" indicator and a pause button. Pausing or ending a session releases the camera.
- **First-run consent screen** explains what the camera analyses, what is stored and how to delete it. Settings include **Delete all my data**.
- **Test footage:** clips recorded of team members for tuning are recorded with their consent, kept off shared drives, and deleted after the project.

## 3. Requirements

Seventeen functional requirements; P0 items alone make a complete demo.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-01 | Start, pause and end a session; show elapsed time, with an optional Pomodoro-style timer whose breaks pause detection | P0 |
| FR-02 | Calibration wizard records a posture and head-pose baseline, and optionally the window direction and the keyboard work zone | P0 |
| FR-03 | Detect phone in hand or in use | P0 |
| FR-04 | Detect looking away from the screen, labelled "window" when calibrated | P0 |
| FR-05 | Detect handling non-work desk objects | P0 |
| FR-06 | Detect the user away from the desk | P0 |
| FR-07 | Alert after 60 s of continuous distraction; repeat every 2 min while it continues | P0 |
| FR-08 | Compute a posture score every second and show an on-screen tip naming the worst issue | P0 |
| FR-09 | Buzz after sustained bad posture, with a different pattern from distraction | P0 |
| FR-10 | Live camera preview with a skeleton overlay the user can toggle | P0 |
| FR-11 | Desktop notification when no watch is paired | P0 |
| FR-12 | Settings for thresholds, alert devices, camera choice and overlay | P0 |
| FR-13 | Band: BLE contract documented and a stub `AlertSink` in the dispatcher chain (not functional) | P1 |
| FR-14 | End-of-session report: focus time, distractions by type, posture score, top posture issues | P1 |
| FR-15 | Stats history dashboard across days | P1 |
| FR-16 | Custom Apple Watch app plays FocusBand vibration patterns; Wear OS receives alerts via the ntfy Android app | Stretch |
| FR-17 | Apple Watch receives alerts through ntfy, mirrored from the iPhone ntfy app (**demo-required**) | P2 |

**Non-functional targets**

| Target | Value |
| --- | --- |
| Processing rate | 15 frames per second or more on a laptop CPU from 2020 or later, no GPU required |
| Alert latency after the threshold is crossed | Under 1 s for desktop; under 5 s through ntfy to the Apple Watch |
| False alerts | No more than 1 per 30 minutes of genuine focused work |
| Offline use | Everything except watch delivery works with no internet |
| Cost | Nothing: no paid services, no trials, no developer accounts beyond a free Apple ID |
| Platforms | Windows 10/11 and macOS 13 or later |

## 4. Architecture and stack

One Python process runs everything that touches video. The only part outside it is the public ntfy.sh server and the phone and watch that subscribe to it (P2). The band appears in the diagram as a design-only stub.

```text
                 Webcam
                   |
+------------------v-------------------------------------------+
| Desktop app (one Python process)  -- all video stays here --  |
|                                                               |
|  Capture  ->  MediaPipe + YOLO26n  ->  FrameFeatures          |
|  (OpenCV)     (body, face, hands,      (2 s smoothing)        |
|                objects)                     |                 |
|                              +--------------+------+          |
|                              v                     v          |
|                  Distraction detectors      Posture tracker   |
|                              |                     |          |
|                              v                     v          |
|                  State machine  ------->  Alert dispatcher ---+-x-> Custom band (stub, never sends)
|                              |            (band stub, watch,  |---> ntfy.sh (P2) -> iPhone ntfy app -> Apple Watch
|                              v             then desktop)      |                     (Wear OS: ntfy Android app, stretch)
|                  SQLite storage                               |---> Desktop notification (P0)
|                  (events, scores; no video)                   |
|                              |                                |
|                              v                                |
|                  Qt UI thread: live preview, skeleton         |
|                  overlay, tips, report, dashboard             |
+---------------------------------------------------------------+
```

Frames flow from webcam to features; only the alert dispatcher sends anything out, and it sends a short message, never an image.

The desktop app runs three threads so the UI never freezes: a **vision thread** (capture, models, features), a **logic thread** (rules, state machine, posture tracker, storage) and the **Qt UI thread**. They pass immutable dataclasses through queues. Alert sending runs on an asyncio loop in the logic thread, because the ntfy HTTP calls (and Bluetooth, if the band is ever built) are asynchronous.

| Layer | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.11 or 3.12 | Check MediaPipe wheel support before moving to a newer Python |
| Camera | OpenCV `cv2.VideoCapture` | Camera index chosen in Settings |
| Body, face, hands | MediaPipe Tasks API: PoseLandmarker (33 points), FaceLandmarker (478 points plus a head transform matrix), HandLandmarker (21 points per hand) | Use `mp.tasks.vision`; the old `mp.solutions` API is gone from newer MediaPipe releases, so pre-2024 tutorials will not run as written |
| Objects | Ultralytics YOLO26n, pretrained on COCO (includes cell phone, keyboard, mouse, laptop, book, cup) | Licensed AGPL-3.0, fine for a school project; a commercial product needs an Ultralytics licence |
| UI | PySide6 (Qt) with pyqtgraph for charts | Qt also provides the tray or menu-bar icon |
| Desktop notifications | `desktop-notifier` package | Windows toasts and macOS Notification Center from one API |
| Bluetooth LE | Not used; the band sink is a stub | `bleak` is the intended library if the band is ever built |
| HTTP to ntfy | `httpx` (async) | P2 |
| Type checking | mypy | Run on `app/logic` and `app/alerts` |
| Storage | SQLite (Python's built-in `sqlite3`) plus a JSON settings file | Local only |
| Watch delivery (P2) | Public ntfy.sh server, no account | Free; the iPhone ntfy app mirrors notifications to the paired Apple Watch. Section 9 |
| Packaging | PyInstaller, one build per OS | The macOS build needs a camera usage description in its Info.plist |
| Development | IBM Bob for scaffolding, tests and refactors; GitHub for code | See section 13 |

## 5. Vision pipeline

Each frame runs through the three MediaPipe landmarkers, YOLO runs on every third frame, and the results become one `FrameFeatures` record that the rules read. The models only report what they see; all judgement lives in the rules (sections 6 to 8), which are easy to unit-test. Every number in sections 5 to 8 is a default from `settings.json` (section 11), not a constant in code; the settings key is given in brackets.

**Camera setup the app asks for:** webcam at the top of the screen, facing the user, with head, both shoulders and the desk surface in view. If shoulders are not visible for 5 s [`vision.shoulders_missing_warn_s`], the session screen shows "Move back or tilt the camera down".

**Per-frame steps**

1. **Capture** at 640 × 480, 30 fps [`vision.capture_width`, `capture_height`, `capture_fps`]; mirror it; wrap it as an `mp.Image` with a timestamp in milliseconds.
2. **Pose:** PoseLandmarker, *lite* model, `VIDEO` running mode, one person. Keep nose, eyes, ears, shoulders, elbows and wrists, with their visibility scores.
3. **Face:** FaceLandmarker with `output_facial_transformation_matrixes=True`. Convert the matrix to yaw, pitch and roll in degrees. Iris points are kept for optional gaze refinement later.
4. **Hands:** HandLandmarker, up to two hands. Compute a bounding box and a "grasp" flag (fingertips curled toward the palm) for each hand.
5. **Objects:** YOLO26n at image size 416 [`vision.yolo_imgsz`], every 3rd frame [`vision.yolo_every_n`] (about 10 Hz), filtered to COCO classes the rules use. Between YOLO frames, the last detections are reused.
6. **Features:** build `FrameFeatures` (below).
7. **Smoothing:** exponential moving average on angles and distances (alpha 0.3 [`smoothing.ema_alpha`]). Each boolean signal is "on" only when it holds in at least 70% of frames [`smoothing.bool_ratio`] over a rolling 2 s window [`smoothing.bool_window_s`].

```python
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
    hands: list[HandInfo]         # bbox, grasp flag, near_keyboard flag
    objects: list[Detection]      # class, confidence, bbox
```

**Performance budget:** 15 fps means about 66 ms per frame on the vision thread. If profiling on the slowest team laptop shows more than that, drop in this order: hands on every 2nd frame (`vision.hands_every_n` = 2), YOLO every 5th frame (`vision.yolo_every_n` = 5), then capture at 15 fps (`vision.capture_fps` = 15). These are settings changes, not code changes. The UI preview always shows the newest frame and never waits for the models.

## 6. Distraction detection

Each detector turns smoothed features into one yes or no per frame; the 1-minute timer in section 8 decides whether to alert. That timer filters most short, harmless moments (a sip of water, a glance at a notification) without extra rules. All angles are measured against the user's calibrated baseline, and all numbers below are starting defaults to tune in testing; they live in the `detectors` block of `settings.json`.

| Detector | Signals used | Fires when | Known false triggers and handling |
| --- | --- | --- | --- |
| Phone | YOLO `cell phone`, hand boxes, head pitch | A phone with confidence of at least 0.45 [`phone_conf`] overlaps or sits within 0.1 frame-widths [`phone_hand_dist`] of a hand, **or** a phone is visible on the desk while head pitch is 20° or more below baseline [`phone_pitch_down_deg`] | Phone used for two-factor codes or a call → 1-minute timer plus a "Snooze 10 min" button |
| Looking away | Head yaw and pitch | Yaw differs from baseline by more than 25° [`look_yaw_deg`], or pitch is more than 20° above baseline [`look_pitch_up_deg`]. Labelled **window** when yaw is within 15° [`window_yaw_tol_deg`] of the calibrated window direction | Looking down at notes is not counted: pitch down with hands on the desk or a `book` detected counts as working |
| Desk objects | Hand boxes and grasp flags, YOLO objects, calibrated work zone | A hand is grasping and is outside the keyboard work zone, **and** it overlaps an object not on the work list (keyboard, mouse, laptop, book) or no object YOLO recognizes | Weakest detector: COCO has no class for most ornaments. Writing with a pen looks similar; the work zone and book check reduce this. Upgrade path below |
| Away | Pose presence | No pose detected, or shoulder visibility under 0.5 [`away_shoulder_vis`], continuously for 10 s [`away_detect_s`]. Only then does the detector fire and the normal 60 s distraction hold (section 8) start, so an alert comes after about 70 s away | A user taking a break should press **Break**, which pauses detection |

**When several fire at once**, the event takes the highest-priority label: phone, then desk objects, then looking away, then away. The UI and report show that label.

**Desk-object upgrade path (if time allows):** photograph the team's actual ornaments (150 to 300 images), label them in Label Studio or Roboflow, and fine-tune YOLO26n on those plus COCO's work classes. This takes about one day and makes the detector far more reliable than the hand-only rule.

## 7. Posture analysis

Posture is judged as change from the user's own calibrated upright posture, not against fixed angles. A front-facing webcam cannot measure true spine angles, and camera height differs on every desk, but it can reliably see a user sink, lean in or tilt compared with how they sat at calibration.

**Calibration (about 30 s, in the wizard and from Settings)**

1. **Upright baseline, 10 s [`calibration.upright_s`]:** "Sit tall, shoulders back, look at your screen." Store the median of every posture metric and of head yaw and pitch.
2. **Window direction, 3 s [`calibration.window_s`], optional:** "Look out your window." Store head yaw.
3. **Work zone, 3 s [`calibration.work_zone_s`]:** "Put your hands on your keyboard." Store the box around both hands, enlarged by 30% [`calibration.work_zone_pad`].

At session start, if the shoulder midpoint has moved more than 15% of frame width [`calibration.recalibrate_shift`] from the stored baseline, the app suggests recalibrating, because the camera has probably moved.

**Metrics** (thresholds in the `posture` block of `settings.json`)

| Issue | Computed from | Bad when (versus baseline) | On-screen tip |
| --- | --- | --- | --- |
| Slouching | Vertical gap from nose to shoulder midpoint, divided by shoulder width | Gap shrinks by more than 15% [`slouch_pct`] | "Sit up tall: you're sinking into your chair." |
| Leaning in | Face width (proxy for distance to screen) | Grows by more than 20% [`lean_pct`] | "Lean back: you're getting close to the screen." |
| Neck bent down | Head pitch | More than 20° further down [`neck_pitch_deg`] for most of the window | "Raise your chin, or raise your screen to eye level." |
| Head tilt | Head roll | More than 10° away from baseline [`tilt_roll_deg`] | "Level your head." |
| Uneven shoulders | Angle of the line through both shoulders | More than 7° away from baseline [`shoulder_angle_deg`] | "Even out your shoulders. Leaning on one elbow?" |

**Score and alerts**

- Each second, each metric gives a penalty from 0 (at baseline) to 1 (at twice its threshold). Posture score = 100 − 20 [`posture.penalty_weight`] × the sum of penalties, clamped to 0–100.
- Posture is **bad** when the score stays under 70 [`posture.bad_score`] for 90% [`posture.bad_ratio`] of a 30 s rolling window [`posture.bad_window_s`]. The on-screen tip names the metric with the largest penalty.
- **Alert** when posture stays bad for 2 minutes [`posture_threshold_s`] (configurable, 1 to 10 min). After a posture alert, the next one waits at least 5 minutes [`posture_cooldown_s`], and posture alerts are held back while a distraction alert is active.
- Posture is not scored while the user is away or looking away, because the landmarks are unreliable then.
- The live overlay draws the pose skeleton, colours each joint line green or amber by its metric, and shows the score in a corner.

## 8. Session states and alert timing

A distraction must hold for 60 s before an alert is sent, and 5 s of focus resets the clock. The focus state machine below runs once per smoothed frame; the posture tracker from section 7 runs beside it and only reads whether the user is present and looking at the screen.

```text
                distraction seen               held 60 s
   +---------+ -----------------> +---------+ ------------> +------------------+
   | Focused |                    | Pending |               | Distracted       |<--+
   |         | <----------------- | (60 s   |               | (alert sent)     |   | repeat every 2 min
   +---------+     5 s focus      |  timer) |               +------------------+---+
     ^  |  ^                      +---------+                        |
     |  |  +---------------------------------------------------------+
     |  |                       5 s focus ends the event
     |  v
   +--------------------------------+
   | Paused                         |   Pause works from any state.
   | (Pause, Break or Snooze;       |   The session auto-pauses after 10 min away.
   |  Resume returns to Focused)    |
   +--------------------------------+
```

Any of the four distractions starts the Pending timer once its detector fires. For being away, the detector itself only fires after 10 s of absence (section 6), so Pending starts 10 s after the user leaves. 5 s of focus at any point sends the user back to Focused.

| Rule | Default | Settings key | In the Settings screen |
| --- | --- | --- | --- |
| Distraction must hold before the first alert | 60 s | `distraction_threshold_s.<type>` | 15 s to 5 min, per distraction type |
| Focus needed to cancel a pending alert or end an event | 5 s continuous | `focus_reset_s` | No (file only) |
| Repeat alert while still distracted | Every 2 min | `repeat_alert_s` (`null` = off) | 1 to 10 min, or off |
| Escalate to the stronger vibration pattern | From the 3rd repeat | `escalate_after_repeats` (`null` = off) | On or off |
| Snooze | 10 min | `snooze_s` | 5 to 30 min |
| Absence before the away detector fires | 10 s | `away_detect_s` | No (file only) |
| Away with no input before auto-pausing the session | 10 min | `auto_pause_away_s` | 5 to 30 min |

Every state change is written to the `events` table with a timestamp, so the report and dashboard are built from the same record the alerts used.

## 9. Alert delivery

Every alert goes to exactly one place: a paired Apple Watch, otherwise a desktop notification. The band sink sits first in the chain to show where the band would plug in, but it is a stub whose `available()` always returns False. Every sink implements the same interface, so the rules never know which device is in use.

```python
class AlertSink(Protocol):
    name: str
    async def available(self) -> bool: ...
    async def send(self, alert: Alert) -> bool: ...   # False = try the next sink

@dataclass(frozen=True)
class Alert:
    kind: Literal["distraction", "posture", "test"]
    label: str        # e.g. "phone", "window", "slouching"
    pattern: int      # vibration pattern ID, table below
    created_at: float
```

The dispatcher tries sinks in priority order (band stub → ntfy to the watch → desktop) and moves on if `send` fails or takes longer than 2 s [`alerts.sink_timeout_s`]. The desktop also always shows the alert as an in-app banner while the window is visible.

**Vibration patterns** (on and off times in milliseconds; Apple Watch approximates them, and the band design and Wear OS app would play them exactly)

| ID | Used for | Pattern |
| --- | --- | --- |
| 1 | Distraction | 400 on, 200 off, 400 on |
| 2 | Posture | 150 on, 100 off, 150 on, 100 off, 150 on |
| 3 | Escalated distraction | 800 on, 200 off, 800 on, 200 off, 800 on |
| 4 | Test or paired | 100 on |

On the ntfy route the watch plays its default notification haptic; only the optional custom watch app plays these patterns.

### Custom band: Bluetooth LE protocol (design only, not implemented)

The band is presented as a design. This contract describes how it would work: the band is a BLE peripheral and the desktop app the central. The desktop ships only `BleBandSink` as a stub (`available()` returns False, `send()` is never reached), so the dispatcher chain shows where a real band would go.

- **Advertising name:** starts with `FocusBand-`, followed by the last 4 hex digits of the chip's MAC address.
- **Alert service:** a custom 128-bit service UUID. Generate it once with `uuidgen` and put it in `shared/ble_contract.json` so the desktop and firmware read the same values.
- **Alert characteristic** (same base UUID, write without response): 4 bytes — `version` (1), `pattern_id` (1 to 4), `intensity` (0 to 255), `reserved` (0).
- **Battery:** the standard Battery Service (0x180F) with Battery Level (0x2A19), read once a minute and shown in the app.
- **Intended desktop behaviour (if built):** `bleak` scans for the service UUID, connects, and stays connected for the session. On disconnect it retries every 10 s and falls through to the next sink meanwhile. Pairing happens in Settings: Scan, pick the band, receive pattern 4.
- **Intended firmware (if built):** a small ESP32-C3 or nRF52840 board drives a coin vibration motor by PWM (`intensity` → duty cycle), plays `pattern_id` from the table above without blocking BLE, and reports battery each minute.

### Watches: ntfy (P2)

Watches pair with phones, not laptops, so alerts go laptop → ntfy.sh → phone → watch. This uses the free public [ntfy](https://ntfy.sh) server: no account, no card, no Apple Developer Program, and no server code of our own.

1. **Pair:** in Settings, the desktop generates a random 32-character topic name, stores it in the OS keychain, and shows it as a QR code and as text. The user subscribes to that topic in the free ntfy app on their iPhone and allows ntfy notifications to mirror to the Apple Watch. The desktop then sends pattern 4 as a test.
2. **Alert:** `NtfySink` POSTs one JSON message to `ntfy_server` with the topic, a short title and body (e.g. "Phone — 1 min"), priority high, and tags carrying `kind` and `pattern`. Nothing else is sent.
3. **Forget watch:** deletes the topic from the keychain and clears `watch_paired`.

| Watch | How the alert arrives | Vibration |
| --- | --- | --- |
| Apple Watch (demo-required) | iPhone ntfy app receives it and iOS mirrors the notification to the watch | Default notification haptic |
| Apple Watch custom app (stretch) | Small Swift app installed from Xcode with a free Apple ID (reinstall every 7 days). While open during a session, it polls `GET <ntfy_server>/<topic>/json?poll=1&since=<last id>` every few seconds | Plays the pattern from the table above with `WKInterfaceDevice` haptics. Must stay in the foreground; free accounts cannot receive push |
| Wear OS (stretch) | ntfy Android app on the phone or watch | Default notification vibration |

**Trade-off:** ntfy.sh is a third-party server and anyone who knows the topic can read its messages, which is why the topic is long, random and kept in the keychain, and why messages carry only kind, label, pattern and timestamp. If that becomes a concern, ntfy can be self-hosted later without changing the desktop code beyond `ntfy_server`.

## 10. Desktop screens

Six screens plus a tray or menu-bar icon cover the whole flow; the session screen is the one the demo lives on.

| Screen | Contents | Priority |
| --- | --- | --- |
| Welcome and consent | What the camera analyses, what is stored, camera permission request, link to Delete my data | P0 |
| Calibration wizard | The three steps from section 7 with a live preview, a countdown and a pass or retry result per step | P0 |
| Session | Live preview with skeleton overlay toggle, "camera on" indicator, timer, focus state chip, posture score, tip banner, Pause, Break, Snooze and End buttons | P0 |
| Settings | Thresholds from section 8, camera choice, overlay default, alert devices (watch pairing QR code and topic, Send test alert, Forget watch; band shown as "coming soon") | P0 |
| Session report | Focus time vs total time, distractions by type with counts and minutes, posture score over the session, the 3 most common posture issues with their tips | P1 |
| Dashboard | Focus minutes per day, distractions per hour of work, average posture score, for the last 7 or 30 days | P1 |
| Tray or menu-bar icon | Current state colour, Start or End session, Pause, Open window; keeps running when the window is closed | P0 |

## 11. Data model and settings

Four SQLite tables hold everything the report and dashboard need; nothing in them can reconstruct an image.

```sql
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,          -- ISO 8601, local time with offset
  ended_at TEXT,
  focus_seconds INTEGER DEFAULT 0,
  avg_posture_score REAL
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  session_id INTEGER REFERENCES sessions(id),
  kind TEXT NOT NULL,                -- distraction | posture | away | break | pause | alert
  label TEXT,                        -- phone, window, desk_object, slouching, ...
  started_at TEXT NOT NULL,
  ended_at TEXT,
  alert_sink TEXT                    -- ntfy | desktop, for alert rows
);

CREATE TABLE posture_samples (       -- one row per 10 s [posture.sample_interval_s], averaged
  session_id INTEGER REFERENCES sessions(id),
  t INTEGER NOT NULL,                -- seconds since session start
  score REAL,
  worst_issue TEXT
);

CREATE TABLE calibration (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  values_json TEXT NOT NULL          -- baseline metrics, window yaw, work zone box
);
```

Settings live in `settings.json` next to the database. These defaults are the single source for every threshold and timing in sections 5 to 9; `app/logic/` reads them and never hard-codes a number. The top-level timing keys are what the Settings screen exposes (ranges in section 8). The nested blocks are tuning values, edited in the file during replay evaluation (section 12). `storage/settings.py` fills any missing key from these defaults, so older settings files keep working. Defaults:

```json
{
  "camera_index": 0,
  "overlay": true,
  "watch_paired": false,
  "ntfy_server": "https://ntfy.sh",

  "distraction_threshold_s": {"phone": 60, "looking_away": 60, "desk_object": 60, "away": 60},
  "focus_reset_s": 5,
  "away_detect_s": 10,
  "repeat_alert_s": 120,
  "escalate_after_repeats": 3,
  "posture_threshold_s": 120,
  "posture_cooldown_s": 300,
  "snooze_s": 600,
  "auto_pause_away_s": 600,

  "vision": {
    "capture_width": 640, "capture_height": 480, "capture_fps": 30,
    "yolo_every_n": 3, "yolo_imgsz": 416, "hands_every_n": 1,
    "shoulders_missing_warn_s": 5
  },
  "smoothing": {"ema_alpha": 0.3, "bool_window_s": 2, "bool_ratio": 0.7},
  "detectors": {
    "phone_conf": 0.45, "phone_hand_dist": 0.1, "phone_pitch_down_deg": 20,
    "look_yaw_deg": 25, "look_pitch_up_deg": 20, "window_yaw_tol_deg": 15,
    "away_shoulder_vis": 0.5
  },
  "calibration": {
    "upright_s": 10, "window_s": 3, "work_zone_s": 3,
    "work_zone_pad": 0.3, "recalibrate_shift": 0.15
  },
  "posture": {
    "slouch_pct": 15, "lean_pct": 20, "neck_pitch_deg": 20,
    "tilt_roll_deg": 10, "shoulder_angle_deg": 7,
    "penalty_weight": 20, "bad_score": 70, "bad_window_s": 30, "bad_ratio": 0.9,
    "sample_interval_s": 10
  },
  "alerts": {"sink_timeout_s": 2}
}
```

The ntfy topic is stored in the OS keychain (via the `keyring` package), not in plain JSON; the JSON keeps only a flag that a watch is paired and the server URL.

## 12. Repository, testing and acceptance

The repo separates models from rules so that every rule can be tested with fake `FrameFeatures` and no camera.

```text
focusband/
  app/
    main.py              # starts threads, Qt app, tray icon
    vision/              # capture.py, landmarkers.py, objects.py, features.py
    logic/               # detectors.py, posture.py, state_machine.py, calibration.py
    alerts/              # dispatcher.py, desktop.py, ntfy.py, ble_band.py (stub)
    storage/             # db.py, settings.py
    ui/                  # session.py, wizard.py, settings.py, report.py, dashboard.py
  models/                # .task and .pt files, downloaded by a setup script
  shared/ble_contract.json  # band design: UUIDs and pattern table (not used at runtime)
  watch/applewatch/      # Swift custom watch app (stretch; built and installed from Xcode with a free Apple ID)
  tests/
    unit/                # rules and state machine with synthetic features
    clips/               # consented test videos, git-ignored
    eval.py              # replays clips and scores detectors
```

**Testing**

- **Unit tests (pytest):** every detector, the posture score, and every state-machine transition, fed with hand-built `FrameFeatures` sequences. Target: logic modules fully covered, and the suite runs in under 10 s.
- **Replay evaluation:** each team member records consented 3-minute clips for each scenario (focused typing, reading notes, phone, window, fidget object, away, slouching, leaning in), in daylight and lamplight. Label the start and end of each behaviour in a CSV. `eval.py` replays the clips through the real pipeline and reports detection rate and false alerts per detector.
- **Device tests:** on one Windows and one macOS laptop — camera permission, notifications, packaged build start-up, and an Apple Watch receiving a test alert through ntfy.
- **Soak test:** a 60-minute genuine work session on each OS, checking CPU, memory growth and false alerts.

**Acceptance criteria for the demo**

- [ ] Each of the 4 distractions held for 60 s triggers an alert in at least 9 of 10 replay clips.
- [ ] No more than 1 false alert in a 30-minute focused session.
- [ ] Slouching and leaning in held for 2 minutes trigger a posture buzz and the correct tip.
- [ ] At least 15 fps on the slowest team laptop with the overlay on.
- [ ] Alerts reach the desktop within 1 s when no watch is paired, and reach a paired Apple Watch within 5 s through ntfy.
- [ ] The session report matches the events logged during the session.
- [ ] A search of the app data folder after a session finds no image or video files.

## 13. Two-week plan, IBM Bob and risks

The P0 demo works end to end on desktop notifications by day 5. The ntfy sink is built early (days 6–7), so the Apple Watch already gets alerts before the P0 and P1 freeze on day 10; days 10–12 go to the optional custom watch app. Developer A owns vision and logic; developer B owns the app shell, UI, storage and alerts. The three hardware teammates design and present the band concept and also record and label test clips.

| Who | Task | Days |
| --- | --- | --- |
| Developer A | Vision pipeline and models | 1–2 |
| Developer A | Features and calibration | 3–4 |
| Developer A | Distraction detectors | 5–6 |
| Developer A | Posture scoring and tips | 7 |
| Developer A | State machine integration | 8 |
| Developer A | Replay evaluation and tuning | 9–10 |
| Developer A | Desk-object fine-tune (optional) | 11–12 |
| Developer B | Qt shell, threads, storage | 1–2 |
| Developer B | Session screen and notifications | 3–4 |
| Developer B | Settings and calibration wizard | 5 |
| Developer B | Band stub sink, ntfy sink, pairing screen with QR code | 6–7 |
| Developer B | Report and dashboard | 8–9 |
| Developer B | Custom Apple Watch app (stretch); Wear OS check with the ntfy Android app | 10–12 |
| Both developers | Packaging, fixes, demo prep | 13–14 |
| Hardware team | Band concept: design, mock-up and presentation of how it would work | 1–7 |
| Hardware team | Record and label test clips | 4–5 |

Milestones: interfaces agreed (day 1), P0 demo on desktop (day 5), Apple Watch receives a live alert through ntfy (day 7), **P0 and P1 freeze (day 10)**, final demo (day 14). Days 11 and 12 hold stretch work (custom watch app, desk-object fine-tune), so a slip in the core plan eats into stretch work rather than the demo.

**Handoffs that keep the two developers unblocked**

- Day 1: agree on `FrameFeatures`, `Alert` and the `AlertSink` interface (sections 5 and 9) before writing code. B builds the UI against a fake feature stream; A tests rules without the UI.
- Day 7: the ntfy topic is testable with `curl -d "test" ntfy.sh/<topic>`, so the watch route can be checked before the desktop sink is finished.
- Days 4 and 5: hardware teammates record and label the replay clips (section 12).

**Using IBM Bob**

- Give Bob this document as the project spec, and keep it updated when decisions change.
- Use Bob to scaffold the repository layout, dataclasses, SQLite layer and Qt screens, then review its output before merging.
- Ask Bob to write pytest cases for each detector and state transition from the tables in sections 6 to 8. Those tables are the test oracle.
- Use Bob for refactors and code review before each merge, and to draft the README and setup scripts on days 13 and 14.
- Keep model choices, thresholds and privacy rules as human decisions; Bob implements them, it doesn't pick them.

**Risks**

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Desk-object detection is unreliable | High | Ship the hand-based rule; fine-tune YOLO on the team's own ornaments if days 11 and 12 allow; otherwise demo it with known objects |
| A bright window behind the user ruins face tracking | Medium | Warn when face confidence is low; recommend the camera faces away from windows |
| Too slow on older laptops | Medium | The performance fallback order in section 5; profile on the slowest laptop by day 4 |
| macOS camera permission or packaging problems | Medium | Test the packaged build by day 10; demo from source as a fallback |
| ntfy.sh is down or rate-limits during the demo | Low | Desktop notification still fires (fallback sink); ntfy can be self-hosted on a laptop if needed |
| Watch doesn't show mirrored notifications | Medium | Check the iPhone Watch app's notification mirroring for ntfy and that the watch isn't in Do Not Disturb; test by day 7 |
| Custom watch app doesn't fit in the time | High | It is stretch; the ntfy route already meets the demo requirement |
| False alerts annoy users | Medium | 1-minute threshold, 5 s focus reset, Snooze, and replay tuning on days 9 and 10 |

## Sources

- [IBM Bob announcement, April 28, 2026 (Verdict)](https://www.verdict.co.uk/ibm-launches-bob/)
- [MediaPipe PoseLandmarker Python API](https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker)
- [MediaPipe: Tasks API replaces the legacy Solutions API (MGT-python wiki)](https://github.com/fourMs/MGT-python/wiki/10-%E2%80%90-Pose-and-Motion-Capture)
- [Ultralytics YOLO26 and licensing](https://docs.ultralytics.com/)
- [ntfy push notification service](https://github.com/binwiederhier/ntfy/blob/9f052bdf8b8094adb05b39c55a7e783bf51d51e5/README.md)
