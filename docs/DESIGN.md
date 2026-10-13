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
| P2, after the freeze | Apple Watch app via the cloud relay — **required for the final demo** | Built after P0 and P1, but must work end to end; needs a paid Apple Developer account and a Mac with Xcode |
| Stretch | Wear OS app via the same relay | Only after the Apple Watch works |

## 2. Users and privacy

One person runs the app on themselves, and only they see the results. Because the camera watches someone for hours, privacy is a design rule, not a setting.

- **No video is stored.** Frames are processed in memory and dropped. The release build has no code path that writes frames to disk. A developer-only debug recorder exists behind a build flag and is off in release.
- **What is stored:** session times, distraction events (type, start, end), posture scores and calibration values, in a local SQLite file in the user's app data folder.
- **What leaves the computer:** only when a watch is paired, a small alert message (type, label, pattern, timestamp; no images, no names) goes to the cloud relay.
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
| FR-16 | Wear OS companion app receives alerts through the cloud relay | Stretch |
| FR-17 | Apple Watch companion app receives alerts through the cloud relay (**demo-required**) | P2 |

**Non-functional targets**

| Target | Value |
| --- | --- |
| Processing rate | 15 frames per second or more on a laptop CPU from 2020 or later, no GPU required |
| Alert latency after the threshold is crossed | Under 1 s for desktop; under 5 s through the relay to the Apple Watch |
| False alerts | No more than 1 per 30 minutes of genuine focused work |
| Offline use | Everything except watch delivery works with no internet |
| Platforms | Windows 10/11 and macOS 13 or later |

## 4. Architecture and stack

One Python process runs everything that touches video. The only parts outside it are the watch apps and their small relay (P2). The band appears in the diagram as a design-only stub.

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
|                              |            (band stub, watch,  |---> Cloud relay (P2) -> Apple Watch
|                              v             then desktop)      |                        (Wear OS stretch)
|                  SQLite storage                               |---> Desktop notification (P0)
|                  (events, scores; no video)                   |
|                              |                                |
|                              v                                |
|                  Qt UI thread: live preview, skeleton         |
|                  overlay, tips, report, dashboard             |
+---------------------------------------------------------------+
```

Frames flow from webcam to features; only the alert dispatcher sends anything out, and it sends a short message, never an image.

The desktop app runs three threads so the UI never freezes: a **vision thread** (capture, models, features), a **logic thread** (rules, state machine, posture tracker, storage) and the **Qt UI thread**. They pass immutable dataclasses through queues. Alert sending runs on an asyncio loop in the logic thread, because the relay's HTTP calls (and Bluetooth, if the band is ever built) are asynchronous.

| Layer | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.11 or 3.12 | Check MediaPipe wheel support before moving to a newer Python |
| Camera | OpenCV `cv2.VideoCapture` | Camera index chosen in Settings |
| Body, face, hands | MediaPipe Tasks API: PoseLandmarker (33 points), FaceLandmarker (478 points plus a head transform matrix), HandLandmarker (21 points per hand) | Use `mp.tasks.vision`; the old `mp.solutions` API is gone from newer MediaPipe releases, so pre-2024 tutorials will not run as written |
| Objects | Ultralytics YOLO26n, pretrained on COCO (includes cell phone, keyboard, mouse, laptop, book, cup) | Licensed AGPL-3.0, fine for a school project; a commercial product needs an Ultralytics licence |
| UI | PySide6 (Qt) with pyqtgraph for charts | Qt also provides the tray or menu-bar icon |
| Desktop notifications | `desktop-notifier` package | Windows toasts and macOS Notification Center from one API |
| Bluetooth LE | Not used; the band sink is a stub | `bleak` is the intended library if the band is ever built |
| HTTP to the relay | `httpx` (async) | P2 |
| Type checking | mypy | Run on `app/logic` and `app/alerts` |
| Storage | SQLite (Python's built-in `sqlite3`) plus a JSON settings file | Local only |
| Watch relay (P2) | Firebase Cloud Messaging, called by one small Cloud Function | Section 9 explains why the desktop never calls FCM directly |
| Packaging | PyInstaller, one build per OS | The macOS build needs a camera usage description in its Info.plist |
| Development | IBM Bob for scaffolding, tests and refactors; GitHub for code | See section 13 |

## 5. Vision pipeline

Each frame runs through the three MediaPipe landmarkers, YOLO runs on every third frame, and the results become one `FrameFeatures` record that the rules read. The models only report what they see; all judgement lives in the rules (sections 6 to 8), which are easy to unit-test.

**Camera setup the app asks for:** webcam at the top of the screen, facing the user, with head, both shoulders and the desk surface in view. If shoulders are not visible for 5 s, the session screen shows "Move back or tilt the camera down".

**Per-frame steps**

1. **Capture** at 640 × 480, 30 fps; mirror it; wrap it as an `mp.Image` with a timestamp in milliseconds.
2. **Pose:** PoseLandmarker, *lite* model, `VIDEO` running mode, one person. Keep nose, eyes, ears, shoulders, elbows and wrists, with their visibility scores.
3. **Face:** FaceLandmarker with `output_facial_transformation_matrixes=True`. Convert the matrix to yaw, pitch and roll in degrees. Iris points are kept for optional gaze refinement later.
4. **Hands:** HandLandmarker, up to two hands. Compute a bounding box and a "grasp" flag (fingertips curled toward the palm) for each hand.
5. **Objects:** YOLO26n at image size 416, every 3rd frame (about 10 Hz), filtered to COCO classes the rules use. Between YOLO frames, the last detections are reused.
6. **Features:** build `FrameFeatures` (below).
7. **Smoothing:** exponential moving average on angles and distances (alpha 0.3). Each boolean signal is "on" only when it holds in at least 70% of frames over a rolling 2 s window.

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

**Performance budget:** 15 fps means about 66 ms per frame on the vision thread. If profiling on the slowest team laptop shows more than that, drop in this order: hands on every 2nd frame, YOLO every 5th frame, then capture at 15 fps. The UI preview always shows the newest frame and never waits for the models.

## 6. Distraction detection

Each detector turns smoothed features into one yes or no per frame; the 1-minute timer in section 8 decides whether to alert. That timer filters most short, harmless moments (a sip of water, a glance at a notification) without extra rules. All angles are measured against the user's calibrated baseline, and all numbers below are starting defaults to tune in testing.

| Detector | Signals used | Fires when | Known false triggers and handling |
| --- | --- | --- | --- |
| Phone | YOLO `cell phone`, hand boxes, head pitch | A phone with confidence of at least 0.45 overlaps or sits within 0.1 frame-widths of a hand, **or** a phone is visible on the desk while head pitch is 20° or more below baseline | Phone used for two-factor codes or a call → 1-minute timer plus a "Snooze 10 min" button |
| Looking away | Head yaw and pitch | Yaw differs from baseline by more than 25°, or pitch is more than 20° above baseline. Labelled **window** when yaw is within 15° of the calibrated window direction | Looking down at notes is not counted: pitch down with hands on the desk or a `book` detected counts as working |
| Desk objects | Hand boxes and grasp flags, YOLO objects, calibrated work zone | A hand is grasping and is outside the keyboard work zone, **and** it overlaps an object not on the work list (keyboard, mouse, laptop, book) or no object YOLO recognizes | Weakest detector: COCO has no class for most ornaments. Writing with a pen looks similar; the work zone and book check reduce this. Upgrade path below |
| Away | Pose presence | No pose detected, or shoulder visibility under 0.5, for 10 s | A user taking a break should press **Break**, which pauses detection |

**When several fire at once**, the event takes the highest-priority label: phone, then desk objects, then looking away, then away. The UI and report show that label.

**Desk-object upgrade path (if time allows):** photograph the team's actual ornaments (150 to 300 images), label them in Label Studio or Roboflow, and fine-tune YOLO26n on those plus COCO's work classes. This takes about one day and makes the detector far more reliable than the hand-only rule.

## 7. Posture analysis

Posture is judged as change from the user's own calibrated upright posture, not against fixed angles. A front-facing webcam cannot measure true spine angles, and camera height differs on every desk, but it can reliably see a user sink, lean in or tilt compared with how they sat at calibration.

**Calibration (about 30 s, in the wizard and from Settings)**

1. **Upright baseline, 10 s:** "Sit tall, shoulders back, look at your screen." Store the median of every posture metric and of head yaw and pitch.
2. **Window direction, 3 s, optional:** "Look out your window." Store head yaw.
3. **Work zone, 3 s:** "Put your hands on your keyboard." Store the box around both hands, enlarged by 30%.

At session start, if the shoulder midpoint has moved more than 15% of frame width from the stored baseline, the app suggests recalibrating, because the camera has probably moved.

**Metrics**

| Issue | Computed from | Bad when (versus baseline) | On-screen tip |
| --- | --- | --- | --- |
| Slouching | Vertical gap from nose to shoulder midpoint, divided by shoulder width | Gap shrinks by more than 15% | "Sit up tall: you're sinking into your chair." |
| Leaning in | Face width (proxy for distance to screen) | Grows by more than 20% | "Lean back: you're getting close to the screen." |
| Neck bent down | Head pitch | More than 20° further down for most of the window | "Raise your chin, or raise your screen to eye level." |
| Head tilt | Head roll | More than 10° away from baseline | "Level your head." |
| Uneven shoulders | Angle of the line through both shoulders | More than 7° away from baseline | "Even out your shoulders. Leaning on one elbow?" |

**Score and alerts**

- Each second, each metric gives a penalty from 0 (at baseline) to 1 (at twice its threshold). Posture score = 100 − 20 × the sum of penalties, clamped to 0–100.
- Posture is **bad** when the score stays under 70 for 90% of a 30 s rolling window. The on-screen tip names the metric with the largest penalty.
- **Buzz** when posture stays bad for 2 minutes (configurable, 1 to 10 min). After a posture buzz, the next one waits at least 5 minutes, and posture buzzes are held back while a distraction alert is active.
- Posture is not scored while the user is away or looking away, because the landmarks are unreliable then.
- The live overlay draws the pose skeleton, colours each joint line green or amber by its metric, and shows the score in a corner.

## 8. Session states and alert timing

A distraction must hold for 60 s before the wrist buzzes, and 5 s of focus resets the clock. The focus state machine below runs once per smoothed frame; the posture tracker from section 7 runs beside it and only reads whether the user is present and looking at the screen.

```text
                distraction seen               held 60 s
   +---------+ -----------------> +---------+ ------------> +------------------+
   | Focused |                    | Pending |               | Distracted       |<--+
   |         | <----------------- | (60 s   |               | (wrist buzz sent)|   | repeat every 2 min
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

Any of the four distractions, including being away, starts the Pending timer; 5 s of focus at any point sends the user back to Focused.

| Rule | Default | Configurable |
| --- | --- | --- |
| Distraction must hold before the first alert | 60 s | 15 s to 5 min, per distraction type |
| Focus needed to cancel a pending alert or end an event | 5 s continuous | No |
| Repeat alert while still distracted | Every 2 min | 1 to 10 min, or off |
| Escalate to the stronger vibration pattern | From the 3rd repeat | On or off |
| Snooze | 10 min | 5 to 30 min |
| Away before entering Away | 10 s | No |
| Away with no input before auto-pausing the session | 10 min | 5 to 30 min |

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

The dispatcher tries sinks in priority order (band stub → Apple Watch via relay → desktop) and moves on if `send` fails or takes longer than 2 s. The desktop also always shows the alert as an in-app banner while the window is visible.

**Vibration patterns** (on and off times in milliseconds; Apple Watch approximates them, and the band design and Wear OS app would play them exactly)

| ID | Used for | Pattern |
| --- | --- | --- |
| 1 | Distraction | 400 on, 200 off, 400 on |
| 2 | Posture | 150 on, 100 off, 150 on, 100 off, 150 on |
| 3 | Escalated distraction | 800 on, 200 off, 800 on, 200 off, 800 on |
| 4 | Test or paired | 100 on |

### Custom band: Bluetooth LE protocol (design only, not implemented)

The band is presented as a design. This contract describes how it would work: the band is a BLE peripheral and the desktop app the central. The desktop ships only `BleBandSink` as a stub (`available()` returns False, `send()` is never reached), so the dispatcher chain shows where a real band would go.

- **Advertising name:** starts with `FocusBand-`, followed by the last 4 hex digits of the chip's MAC address.
- **Alert service:** a custom 128-bit service UUID. Generate it once with `uuidgen` and put it in `shared/ble_contract.json` so the desktop and firmware read the same values.
- **Alert characteristic** (same base UUID, write without response): 4 bytes — `version` (1), `pattern_id` (1 to 4), `intensity` (0 to 255), `reserved` (0).
- **Battery:** the standard Battery Service (0x180F) with Battery Level (0x2A19), read once a minute and shown in the app.
- **Intended desktop behaviour (if built):** `bleak` scans for the service UUID, connects, and stays connected for the session. On disconnect it retries every 10 s and falls through to the next sink meanwhile. Pairing happens in Settings: Scan, pick the band, receive pattern 4.
- **Intended firmware (if built):** a small ESP32-C3 or nRF52840 board drives a coin vibration motor by PWM (`intensity` → duty cycle), plays `pattern_id` from the table above without blocking BLE, and reports battery each minute.

### Watches: cloud relay (P2)

Watches pair with phones, not laptops, so alerts go laptop → relay → watch. The relay is one small Firebase Cloud Function with three endpoints; the desktop never holds Google or Apple credentials, because anything shipped inside the app can be extracted.

1. **Watch registers:** the watch app gets its push token and calls `POST /register`. The relay stores the token and returns a 6-digit code, which the watch shows.
2. **User pairs:** the user types the code into the desktop app's Settings, which calls `POST /pair` and receives a long random device secret, stored locally.
3. **Alert:** the desktop calls `POST /alert` with the secret and the `Alert` fields. The relay sends a high-priority push to the stored token.

| Watch | App | How the alert arrives | Vibration |
| --- | --- | --- | --- |
| Wear OS (stretch) | Kotlin, standalone app | FCM high-priority **data** message, handled in `FirebaseMessagingService.onMessageReceived` | Exact pattern with `VibrationEffect.createWaveform`, plus a notification |
| Apple Watch (demo-required) | Swift, independent watchOS app | Relay sends straight to Apple's push service (APNs) using a token key; Firebase's watchOS support is community-maintained only, so it is skipped | System notification haptic in the background; the custom pattern plays only when the app is in the foreground |

Cloud Functions require Firebase's pay-as-you-go plan; usage at this size should cost nothing, but check current pricing before setup. Apple Watch also needs the paid Apple Developer Program to send pushes.

**Plan B if the watch apps slip:** publish each alert to a private ntfy topic (a long random name) with one HTTP POST. The user installs the free ntfy app on their phone, and the phone mirrors the notification to whatever watch is paired with it. This needs no watch code, but the vibration pattern is the watch's default.

## 10. Desktop screens

Six screens plus a tray or menu-bar icon cover the whole flow; the session screen is the one the demo lives on.

| Screen | Contents | Priority |
| --- | --- | --- |
| Welcome and consent | What the camera analyses, what is stored, camera permission request, link to Delete my data | P0 |
| Calibration wizard | The three steps from section 7 with a live preview, a countdown and a pass or retry result per step | P0 |
| Session | Live preview with skeleton overlay toggle, "camera on" indicator, timer, focus state chip, posture score, tip banner, Pause, Break, Snooze and End buttons | P0 |
| Settings | Thresholds from section 8, camera choice, overlay default, alert devices (watch pairing code, Send test alert; band shown as "coming soon") | P0 |
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
  alert_sink TEXT                    -- applewatch | wearos | desktop, for alert rows
);

CREATE TABLE posture_samples (       -- one row per 10 s, averaged
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

Settings live in `settings.json` next to the database. Defaults:

```json
{
  "camera_index": 0,
  "overlay": true,
  "distraction_threshold_s": {"phone": 60, "looking_away": 60, "desk_object": 60, "away": 60},
  "repeat_alert_s": 120,
  "escalate_after_repeats": 3,
  "posture_threshold_s": 120,
  "posture_cooldown_s": 300,
  "snooze_s": 600,
  "auto_pause_away_s": 600,
  "watch_paired": false
}
```

The watch device secret is stored in the OS keychain (via the `keyring` package), not in plain JSON; the JSON keeps only a flag that a watch is paired.

## 12. Repository, testing and acceptance

The repo separates models from rules so that every rule can be tested with fake `FrameFeatures` and no camera.

```text
focusband/
  app/
    main.py              # starts threads, Qt app, tray icon
    vision/              # capture.py, landmarkers.py, objects.py, features.py
    logic/               # detectors.py, posture.py, state_machine.py, calibration.py
    alerts/              # dispatcher.py, desktop.py, relay.py, ble_band.py (stub)
    storage/             # db.py, settings.py
    ui/                  # session.py, wizard.py, settings.py, report.py, dashboard.py
  models/                # .task and .pt files, downloaded by a setup script
  shared/ble_contract.json  # band design: UUIDs and pattern table (not used at runtime)
  relay/                 # Firebase Cloud Function (P2)
  watch/applewatch/      # Swift (P2, demo-required)
  watch/wearos/          # Kotlin (stretch)
  tests/
    unit/                # rules and state machine with synthetic features
    clips/               # consented test videos, git-ignored
    eval.py              # replays clips and scores detectors
```

**Testing**

- **Unit tests (pytest):** every detector, the posture score, and every state-machine transition, fed with hand-built `FrameFeatures` sequences. Target: logic modules fully covered, and the suite runs in under 10 s.
- **Replay evaluation:** each team member records consented 3-minute clips for each scenario (focused typing, reading notes, phone, window, fidget object, away, slouching, leaning in), in daylight and lamplight. Label the start and end of each behaviour in a CSV. `eval.py` replays the clips through the real pipeline and reports detection rate and false alerts per detector.
- **Device tests:** on one Windows and one macOS laptop — camera permission, notifications, packaged build start-up, and an Apple Watch receiving a test alert through the relay.
- **Soak test:** a 60-minute genuine work session on each OS, checking CPU, memory growth and false alerts.

**Acceptance criteria for the demo**

- [ ] Each of the 4 distractions held for 60 s triggers an alert in at least 9 of 10 replay clips.
- [ ] No more than 1 false alert in a 30-minute focused session.
- [ ] Slouching and leaning in held for 2 minutes trigger a posture buzz and the correct tip.
- [ ] At least 15 fps on the slowest team laptop with the overlay on.
- [ ] Alerts reach the desktop within 1 s when no watch is paired, and reach a paired Apple Watch within 5 s through the relay.
- [ ] The session report matches the events logged during the session.
- [ ] A search of the app data folder after a session finds no image or video files.

## 13. Two-week plan, IBM Bob and risks

The P0 demo works end to end on desktop notifications by day 5. The relay is built early (days 6–7) so the Apple Watch app, which starts after the P0 and P1 freeze on day 10, only has to receive pushes. Developer A owns vision and logic; developer B owns the app shell, UI, storage and alerts. The three hardware teammates design and present the band concept and also record and label test clips.

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
| Developer B | Band stub sink, relay endpoints (`/register`, `/pair`, `/alert`) | 6–7 |
| Developer B | Report and dashboard | 8–9 |
| Developer B | Apple Watch app (P2, demo-required); Wear OS only if it works early | 10–12 |
| Both developers | Packaging, fixes, demo prep | 13–14 |
| Hardware team | Band concept: design, mock-up and presentation of how it would work | 1–7 |
| Hardware team | Record and label test clips | 4–5 |

Milestones: interfaces agreed (day 1), Apple Developer account and Xcode Mac confirmed (day 2), P0 demo on desktop (day 5), relay deployed (day 7), **P0 and P1 freeze (day 10)**, Apple Watch receives a live alert (day 12), final demo (day 14). Days 11 and 12 hold the Apple Watch work, so a slip in the core plan eats into Wear OS and the desk-object fine-tune first.

**Handoffs that keep the two developers unblocked**

- Day 1: agree on `FrameFeatures`, `Alert` and the `AlertSink` interface (sections 5 and 9) before writing code. B builds the UI against a fake feature stream; A tests rules without the UI.
- Day 7: the relay is deployed and testable with `curl`, so the Apple Watch app only has to register and receive pushes.
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
| Apple Watch blocked by accounts or tooling | Medium | It needs the paid Apple Developer Program (for APNs) and a Mac with Xcode; confirm both by day 2 |
| Watch apps don't fit in the time | High | Cut Wear OS first; Apple Watch must stay. If it slips, use the ntfy Plan B to get alerts onto the watch for the demo |
| False alerts annoy users | Medium | 1-minute threshold, 5 s focus reset, Snooze, and replay tuning on days 9 and 10 |

## Sources

- [IBM Bob announcement, April 28, 2026 (Verdict)](https://www.verdict.co.uk/ibm-launches-bob/)
- [MediaPipe PoseLandmarker Python API](https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker)
- [MediaPipe: Tasks API replaces the legacy Solutions API (MGT-python wiki)](https://github.com/fourMs/MGT-python/wiki/10-%E2%80%90-Pose-and-Motion-Capture)
- [Ultralytics YOLO26 and licensing](https://docs.ultralytics.com/)
- [Firebase Apple SDK: watchOS is community-supported](https://github.com/Notsfsssf/firebase-ios-sdk)
- [ntfy push notification service](https://github.com/binwiederhier/ntfy/blob/9f052bdf8b8094adb05b39c55a7e783bf51d51e5/README.md)
