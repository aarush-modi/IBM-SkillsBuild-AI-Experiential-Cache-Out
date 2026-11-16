# FocusBand — Software Design Document

Last updated Oct 12, 2026

## 1. Overview

FocusBand (working name) is a Python desktop app for Windows and macOS. It watches the user through their webcam during a study or work session, detects distraction and poor posture entirely on-device, and alerts them after 1 minute of sustained distraction with a short ping and a desktop notification on the same computer. The team builds it with IBM Bob as the AI development platform; Bob is a dev tool here, not part of the running app.

**Goals for the 2-week build**

- Detect four distractions: phone use, looking away (including out the window), handling desk objects, and being away from the desk.
- Score posture against a personal calibrated baseline and coach the user with alert pings, on-screen tips, a live skeleton overlay and an end-of-session report.
- Deliver each alert on the computer: a short ping whose sound tells the alert type apart, plus a desktop notification.
- Present the custom BLE band as a designed concept: its protocol is specified (section 9) and a stub sink shows where it plugs in, but it does not need to work.
- Keep all video on the user's computer.

**Non-goals**

- Supervisor, employer or parent monitoring; the user is the only person who sees their data.
- A working band. The hardware team designs and presents it, but there is no firmware and the desktop app never connects to it.
- Medical or ergonomic diagnosis; posture tips are general guidance.
- Phone or smartwatch apps, or any alert delivery off the computer.

**Priorities**

| Priority | Scope | Why this tier |
| --- | --- | --- |
| P0, must ship | Webcam pipeline, four distraction detectors, posture scoring, calibration, session timer, live overlay, on-screen tips, desktop notifications with alert pings | The complete demo runs on one computer |
| P1, should ship | End-of-session report, stats history dashboard, band stub sink | The report and dashboard reuse stored events; the band stub is small and shows the band design |
| Stretch | Desk-object YOLO fine-tune on the team's own ornaments (section 6) | Only after P0 and P1 work |

## 2. Users and privacy

One person runs the app on themselves, and only they see the results. Because the camera watches someone for hours, privacy is a design rule, not a setting.

- **No video is stored.** Frames are processed in memory and dropped. The release build has no code path that writes frames to disk. A developer-only debug recorder exists behind the `FOCUSBAND_DEV_RECORDER` build flag and is off in release.
- **What is stored:** session times, distraction events (type, start, end), posture scores and calibration values, in a local SQLite file in the user's app data folder.
- **Nothing leaves the computer.** Alerts are a ping and a desktop notification on the same machine, and the app makes no network requests while it runs. The only downloads are the model files, fetched once by the setup script.
- **The camera is only on during a session.** The session screen shows a clear "camera on" indicator and a pause button. Pausing or ending a session releases the camera.
- **First-run consent screen** explains what the camera analyses, what is stored and how to delete it. Settings include **Delete all my data**.
- **Test footage:** clips recorded of team members for tuning are recorded with their consent, kept off shared drives, and deleted after the project.

### Threats and mitigations

FocusBand has no accounts, no server and no cloud APIs, and sends nothing off the computer, so the risks come down to the files on the user's laptop and the third-party code it runs. Every item below is free to do.

| Threat | Likelihood | Mitigation | Where / when |
| --- | --- | --- | --- |
| Alert content seen by someone nearby | Low | Notifications carry only a short title and a generic line such as "Phone in hand for a while" (section 9). No session details, names, images or landmarks. Users can hide FocusBand previews on the lock screen in system settings | alerts/messages.py (done) |
| Another user on the same computer reads the app data | Low | App data folder 0700 and files 0600 on macOS; on Windows, the per-user %APPDATA% folder | storage/settings.py, storage/db.py (done) |
| Laptop stolen or disk copied | Low | The database holds no images, only times, labels and scores. The consent screen recommends FileVault or BitLocker. No app-level database encryption, because SQLCipher adds a native dependency and key handling for little gain | Welcome and consent screen (P0) |
| User wants their data gone | — | Delete my data removes the database and settings. Optional automatic deletion of sessions older than N days [`delete_sessions_after_days`], off by default | Welcome screen and Settings (done) |
| A swapped or tampered model file runs code (.pt uses pickle) | Low | Model URLs pinned to fixed versions, with size and SHA-256 checked before use | scripts/download_models.py (done) |
| Third-party libraries send telemetry | Medium | Ultralytics analytics off (YOLO_OFFLINE=1, event queue disabled), guarded by tests | vision/objects.py (done) |
| Frames or landmarks leak into logs or files, or data leaves the computer | Low | No frame writes in app code, and no network requests at run time. Acceptance checks: after a session, the app data folder has no image or video files, and the app made no network connections | Section 12 acceptance criteria |

## 3. Requirements

Sixteen functional requirements; P0 items alone make a complete demo.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-01 | Start, pause and end a session; show elapsed time, with an optional Pomodoro-style timer whose breaks pause detection | P0 |
| FR-02 | Calibration wizard records a posture and head-pose baseline, and optionally the window direction | P0 |
| FR-03 | Detect phone in hand or in use | P0 |
| FR-04 | Detect looking away from the screen, labelled "window" when calibrated | P0 |
| FR-05 | Detect handling non-work desk objects | P0 |
| FR-06 | Detect the user away from the desk | P0 |
| FR-07 | Alert after 60 s of continuous distraction; repeat every 2 min while it continues | P0 |
| FR-08 | Compute a posture score every second and show an on-screen tip naming the worst issue | P0 |
| FR-09 | Alert after sustained bad posture, with a different ping from distraction | P0 |
| FR-10 | Live camera preview with a skeleton overlay the user can toggle | P0 |
| FR-11 | Desktop notification for every alert | P0 |
| FR-12 | Settings for thresholds, alert sound, camera choice and overlay | P0 |
| FR-13 | Band: BLE contract documented and a stub `AlertSink` in the dispatcher chain (not functional) | P1 |
| FR-14 | End-of-session report: focus time, distractions by type, posture score, top posture issues | P1 |
| FR-15 | Stats history dashboard across days | P1 |
| FR-16 | Each alert plays a short ping on the computer, with a distinct sound per alert type | P0 |

**Non-functional targets**

| Target | Value |
| --- | --- |
| Processing rate | 15 frames per second or more on a laptop CPU from 2020 or later, no GPU required |
| Alert latency after the threshold is crossed | Under 1 s to the ping and the desktop notification |
| False alerts | No more than 1 per 30 minutes of genuine focused work |
| Offline use | Everything works with no internet once the models are downloaded |
| Cost | Nothing: no paid services, no trials, no developer accounts |
| Platforms | Windows 10/11 and macOS 13 or later on Apple Silicon |

## 4. Architecture and stack

One Python process runs everything, and nothing leaves the computer. The band appears in the diagram as a design-only stub.

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
|                              |            (band stub, then    |
|                              v             desktop)           |---> Ping + desktop notification (P0)
|                  SQLite storage                               |
|                  (events, scores; no video)                   |
|                              |                                |
|                              v                                |
|                  Qt UI thread: live preview, skeleton         |
|                  overlay, tips, report, dashboard             |
+---------------------------------------------------------------+
```

Frames flow from webcam to features; the alert dispatcher turns alerts into a ping and a desktop notification on the same computer, never an image.

The desktop app runs three threads so the UI never freezes (`app/runtime.py`): a **vision thread** (capture, models, features), a **logic thread** (rules, state machine, posture tracker, storage) and the **Qt UI thread**, which polls the other two about 30 times a second and is the only thread that touches widgets. They pass immutable dataclasses through queues. Alert sending runs on an asyncio loop beside the logic thread (`alerts/runner.py`), because `desktop-notifier` (and Bluetooth, if the band is ever built) is asynchronous; a slow notification never delays a frame.

| Layer | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.12 or 3.13 | MediaPipe 1.1.0 wheels: Apple Silicon Macs, Windows x64/ARM, Linux; **no Intel Mac** |
| Camera | OpenCV `cv2.VideoCapture` | Camera index chosen in Settings |
| Body, face, hands | MediaPipe Tasks API: PoseLandmarker (33 points), FaceLandmarker (478 points plus a head transform matrix), HandLandmarker (21 points per hand) | Use `mp.tasks.vision`; the old `mp.solutions` API is gone from newer MediaPipe releases, so pre-2024 tutorials will not run as written |
| Objects | Ultralytics YOLO26n, pretrained on COCO (includes cell phone, keyboard, mouse, laptop, book, cup) | Licensed AGPL-3.0, fine for a school project; a commercial product needs an Ultralytics licence |
| UI | PySide6 (Qt) with pyqtgraph for charts | Qt also provides the tray or menu-bar icon |
| Desktop notifications | `desktop-notifier` package | Windows toasts and macOS Notification Center from one API |
| Alert pings | Short WAV files in the repo, played with `afplay` on macOS and the standard-library `winsound` on Windows | No audio dependency |
| Bluetooth LE | Not used; the band sink is a stub | `bleak` is the intended library if the band is ever built |
| Type checking | mypy, strict | Paths set in `pyproject.toml`: contracts, logic, alerts, storage |
| Storage | SQLite (Python's built-in `sqlite3`) plus a JSON settings file | Local only |
| Packaging | PyInstaller, one build per OS | The macOS build needs a camera usage description in its Info.plist |
| Development | IBM Bob for scaffolding, tests and refactors; GitHub for code | See section 13 |

## 5. Vision pipeline

Each frame runs through the three MediaPipe landmarkers, YOLO runs on every third frame, and the results become one `FrameFeatures` record that the rules read. The models only report what they see; all judgement lives in the rules (sections 6 to 8), which are easy to unit-test. Every number in sections 5 to 8 is a default from `settings.json` (section 11), not a constant in code; the settings key is given in brackets.

**Camera setup the app asks for:** webcam at the top of the screen, facing the user, with head, both shoulders and the desk surface in view. If shoulders are not visible for 5 s [`vision.shoulders_missing_warn_s`], the session screen shows "Move back or tilt the camera down".

**Per-frame steps**

1. **Capture** at 640 × 480, 30 fps [`vision.capture_width`, `capture_height`, `capture_fps`]; mirror it; wrap it as an `mp.Image` with a timestamp in milliseconds. If the camera ignores the requested size and delivers another aspect ratio, centre-crop to 4:3 before resizing; never stretch, because stretching distorts shoulder width, face width and head yaw. If the camera returns no frame 30 times in a row [`vision.max_read_failures`], capture stops with a "Camera not responding" error instead of hanging.
2. **Pose:** PoseLandmarker, *lite* model, `VIDEO` running mode, one person. Keep nose, eyes, ears, shoulders, elbows and wrists, with their visibility scores. All three landmarkers use a minimum detection, presence and tracking confidence of 0.5 [`vision.mp_min_confidence`].
3. **Face:** FaceLandmarker with `output_facial_transformation_matrixes=True`. Convert the matrix to yaw, pitch and roll in degrees (yaw positive when the user turns to their right in the mirrored view, pitch negative when looking down, roll positive when the head tips toward the user's left shoulder). Iris points are kept for optional gaze refinement later.
4. **Hands:** HandLandmarker, up to two hands. Compute a bounding box and a "grasp" flag for each hand. Grasp uses the 3D world landmarks so it does not depend on how the hand faces the camera: for the four fingers, the mean of fingertip-to-wrist distance divided by knuckle-to-wrist distance is under 1.4 [`vision.grasp_curl_ratio`] (an open hand is about 1.8, a fist about 0.8). The keyboard is below the camera's view on a normal desk, so hands on the keyboard are not seen; a hand in frame has been lifted toward the face or desk.
5. **Objects:** YOLO26n at image size 416 [`vision.yolo_imgsz`], every 3rd frame [`vision.yolo_every_n`] (about 10 Hz), keeping boxes with confidence of at least 0.25 [`vision.yolo_conf`] (the phone rule applies its own, higher threshold). Only the classes in [`vision.yolo_classes`] are kept: cell phone, the work-list classes and small handheld objects. People, furniture and screens are dropped, so a hand resting on the desk never counts as holding a `dining table`. Between YOLO frames, the last detections are reused.
6. **Features:** build `FrameFeatures` (below).
7. **Smoothing:** exponential moving average on angles, distances and shoulder visibility (alpha 0.3 [`smoothing.ema_alpha`]), done in `vision/features.py`. A value that goes missing is reported as `None` and its average restarts when it comes back. Each detector's yes/no signal is "on" only when it holds in at least 70% of frames [`smoothing.bool_ratio`] over a rolling 2 s window [`smoothing.bool_window_s`]; that smoothing lives in `logic/detectors.py`, because the signals it smooths are judgements.

```python
@dataclass(frozen=True)
class FrameFeatures:
    t: float                      # seconds since session start
    person_present: bool          # a pose was detected this frame
    shoulder_visibility: float | None  # lower of the two shoulders' visibility, 0 to 1
    head_yaw: float | None        # degrees, 0 = facing camera
    head_pitch: float | None      # degrees, negative = looking down
    head_roll: float | None
    shoulder_width: float | None  # frame-width units
    shoulder_angle: float | None  # degrees from horizontal
    shoulder_mid: tuple[float, float] | None  # shoulder midpoint (x, y), frame-width units
    nose_to_shoulder_y: float | None  # vertical gap, divided by shoulder width
    face_width: float | None      # proxy for distance to screen
    face_bbox: BBox | None        # box around the face landmarks, 0 to 1 on each axis
    hands: list[HandInfo]         # bbox, grasp flag
    objects: list[Detection]      # class, confidence, bbox
```

All distances (shoulder width, face width, the nose-to-shoulder gap, `phone_hand_dist`) are in frame-width units: y is scaled by height ÷ width first, so a distance means the same horizontally and vertically. Boxes stay in normalized 0 to 1 coordinates on each axis.

Alongside each `FrameFeatures`, the vision thread sends the UI a `PreviewFrame` (newest image, raw pose and hand points, object boxes) for the live overlay. It lives only in memory and never reaches the logic thread.

**Performance budget:** 15 fps means about 66 ms per frame on the vision thread. If profiling on the slowest team laptop shows more than that, drop in this order: hands on every 2nd frame (`vision.hands_every_n` = 2), YOLO every 5th frame (`vision.yolo_every_n` = 5), then capture at 15 fps (`vision.capture_fps` = 15). These are settings changes, not code changes. The UI preview always shows the newest frame and never waits for the models.

## 6. Distraction detection

Each detector turns smoothed features into one yes or no per frame, which is then smoothed over 2 s (section 5, step 7); the 1-minute timer in section 8 decides whether to alert. All four are judged only against the user's saved calibration, so a session needs one. That timer filters most short, harmless moments (a sip of water, a glance at a notification) without extra rules. All head angles are measured relative to the user's calibrated head pose (section 7, `logic/head_pose.py`), so an angled camera doesn't skew them, and all numbers below are starting defaults to tune in testing; they live in the `detectors` block of `settings.json`.

| Detector | Signals used | Fires when | Known false triggers and handling |
| --- | --- | --- | --- |
| Phone | YOLO `cell phone`, hand boxes, head pitch | A phone with confidence of at least 0.45 [`phone_conf`] overlaps or sits within 0.1 frame-widths [`phone_hand_dist`] of a hand (the gap between the two boxes, with height scaled by the capture aspect ratio), **or** a phone is visible on the desk while head pitch is 20° or more below baseline [`phone_pitch_down_deg`] | Phone used for two-factor codes or a call → 1-minute timer plus a "Snooze 10 min" button |
| Looking away | Head yaw and pitch | Yaw differs from baseline by more than 25° [`look_yaw_deg`], or pitch is more than 20° above baseline [`look_pitch_up_deg`]. Also fires when a body is seen with its shoulders visible but no face is found, because the head has turned further than the face tracker follows. Labelled **window** when yaw is within 15° [`window_yaw_tol_deg`] of the calibrated window direction (never when the face is lost). Not judged while the away signal is on | Looking down at notes is not counted: pitch down with hands on the desk or a `book` detected counts as working |
| Desk objects | Hand boxes and grasp flags, YOLO objects, face box | A visible hand is grasping (typing hands are below the camera's view, so a hand in frame has been lifted), does not overlap the face box, **and** it overlaps an object not on the work list (keyboard, mouse, laptop, book [`work_classes`]) or no object YOLO recognizes | Weakest detector: COCO has no class for most ornaments. Writing with a pen looks similar; the book check reduces this. A chin or cheek resting on a curled hand is ignored by the face-box check; a phone at the ear is still caught by the phone detector. Upgrade path below |
| Away | `person_present`, `shoulder_visibility` | No pose detected, or shoulder visibility under 0.5 [`away_shoulder_vis`], continuously for 10 s [`away_detect_s`]. Only then does the detector fire and the normal 60 s distraction hold (section 8) start, so an alert comes after about 70 s away | A user taking a break should press **Break**, which pauses detection |

**When several fire at once**, the event takes the highest-priority label: phone, then desk objects, then looking away, then away. The UI and report show that label. Labels are `phone`, `desk_object`, `window` or `looking_away`, and `away`; `window` uses the `looking_away` timer in `distraction_threshold_s`.

**Desk-object upgrade path (if time allows):** photograph the team's actual ornaments (150 to 300 images), label them in Label Studio or Roboflow, and fine-tune YOLO26n on those plus COCO's work classes. This takes about one day and makes the detector far more reliable than the hand-only rule.

## 7. Posture analysis

Posture is judged as change from the user's own calibrated upright posture, not against fixed angles. A front-facing webcam cannot measure true spine angles, and camera height differs on every desk, but it can reliably see a user sink, lean in or tilt compared with how they sat at calibration.

**Calibration (about 15 s, in the wizard and from Settings)**

1. **Upright baseline, 10 s [`calibration.upright_s`]:** "Sit tall, shoulders back, look at your screen." Store the median of every posture metric, of head yaw and pitch, and of the shoulder midpoint. A frame counts only if a pose and a face are found and shoulder visibility is at least [`detectors.away_shoulder_vis`].
2. **Window direction, 3 s [`calibration.window_s`], optional:** "Turn your head toward your window and hold it." The 3 s start only once the head has turned more than [`detectors.look_yaw_deg`] from the screen, so the user can read the instruction first. Store the median head yaw relative to the upright baseline. It fails if that yaw is within [`detectors.look_yaw_deg`] of the screen baseline, because the window could then never be told apart from the screen; the retry message shows the measured angle, and the user can skip the step.

Each step passes when at least 80% of its frames [`calibration.min_valid_ratio`] count; otherwise the wizard shows a retry with the reason (for example "Move back or tilt the camera down so both shoulders are in view"). The result is saved as one row in the `calibration` table; the newest row is the one in use. Each row records a calibration version; when an update changes what a stored value means (version 2: face width measured in 3D; version 3: window yaw relative to the baseline head pose), older rows are refused and the user is asked to recalibrate.

At session start, the app watches the first 3 s [`calibration.recalibrate_check_s`]. If the median shoulder midpoint has moved more than 15% of frame width [`calibration.recalibrate_shift`] from the stored baseline, it suggests recalibrating, because the camera has probably moved.

**Metrics** (thresholds in the `posture` block of `settings.json`)

| Issue | Computed from | Bad when (versus baseline) | On-screen tip |
| --- | --- | --- | --- |
| Slouching | Vertical gap from nose to shoulder midpoint, divided by shoulder width | Gap shrinks by more than 15% [`slouch_pct`] | "Sit up tall: you're sinking into your chair." |
| Leaning in | Face width, measured in 3D from the face landmarks so that turning the head doesn't change it (proxy for distance to screen) | Grows by more than 20% [`lean_pct`] | "Lean back: you're getting close to the screen." |
| Neck bent down | Head pitch, relative to the calibrated head pose | More than 20° further down [`neck_pitch_deg`] for most of the window | "Raise your chin, or raise your screen to eye level." |
| Head tilt | Head roll, relative to the calibrated head pose | More than 10° away from baseline [`tilt_roll_deg`] | "Level your head." |
| Uneven shoulders | Angle of the line through both shoulders | More than 7° away from baseline [`shoulder_angle_deg`] | "Even out your shoulders. Leaning on one elbow?" |

Head yaw, pitch and roll are measured in the head's own calibrated frame (`logic/head_pose.py`), here and by the looking-away and phone detectors in section 6: the rotation since calibration is rebuilt from yaw, pitch and roll and decomposed again, rather than subtracting each angle. With a camera above or beside the screen, subtracting angles turns an ordinary head turn into apparent tilt or nodding; the relative rotation does not.

**Score and alerts**

- Each second, each metric gives a penalty, averaged over that second's frames. It is 0 until the metric is half-way to its threshold [`posture.dead_zone`], so normal wobble costs nothing; it then rises to 0.5 at the threshold and to 1 at twice the threshold. Only the harmful direction counts: a bigger nose-to-shoulder gap or a smaller face is not penalised. Posture score = 100 − 60 [`posture.penalty_weight`] × the sum of penalties, clamped to 0–100. With 60, any single metric past its threshold (penalty over 0.5) scores under 70, so one issue on its own can make posture bad; so can two issues each more than halfway to their thresholds.
- Posture is **bad** when the score stays under 70 [`posture.bad_score`] for 90% [`posture.bad_ratio`] of a 30 s rolling window [`posture.bad_window_s`]; seconds that were not scored count as not bad. The on-screen tip names the metric with the largest total penalty over that window.
- **Alert** when posture stays bad for 2 minutes [`posture_threshold_s`] (configurable, 1 to 10 min). After a posture alert, the next one waits at least 5 minutes [`posture_cooldown_s`]; if posture is still bad then, it alerts again. Posture alerts are held back while a distraction alert is active and sent once it ends, if posture is still bad. Good posture at any point resets the 2-minute clock.
- Posture is not scored while the user is away or looking away (including the seconds before the away detector fires), because the landmarks are unreliable then.
- Every 10 s [`posture.sample_interval_s`] the tracker emits one `posture_samples` row: the mean score of the scored seconds and the issue with the largest total penalty.
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
   | (Pause or Break; camera off;   |   The session auto-pauses after 10 min away.
   |  Resume returns to Focused)    |
   +--------------------------------+
```

Any of the four distractions starts the Pending timer once its detector fires. For being away, the detector itself only fires after 10 s of absence (section 6), so Pending starts 10 s after the user leaves. 5 s of focus at any point sends the user back to Focused.

- **Focus** means present and facing the screen: no detector firing and not absent. Being out of view for less than `away_detect_s` is neither focus nor distraction, so it neither cancels nor advances anything.
- **One distraction, one timer.** If the label changes during a distraction (looking away, then the phone), the clock keeps running from when it began and is compared with the threshold of the current type. The alert carries the current label; the logged event keeps the highest-priority label seen.
- **Snooze mutes alerts only.** For `snooze_s`, no distraction or posture alerts are sent, but the camera stays on and detection, timers and logging carry on. It ends by itself, or when the user un-snoozes. Pause and Break release the camera; Resume starts detectors and posture fresh while the session clock carries on.
- **What is logged:** a distraction (or away) event from when it began until focus returned, but only once it reached an alert, so harmless glances cancelled within the hold are not recorded. Also every alert, each stretch of bad posture, and each pause, break and snooze. Time in a distraction, including its pending minute, does not count toward `focus_seconds`.

| Rule | Default | Settings key | In the Settings screen |
| --- | --- | --- | --- |
| Distraction must hold before the first alert | 60 s | `distraction_threshold_s.<type>` | 15 s to 5 min, per distraction type |
| Focus needed to cancel a pending alert or end an event | 5 s continuous | `focus_reset_s` | No (file only) |
| Repeat alert while still distracted | Every 2 min | `repeat_alert_s` (`null` = off) | 1 to 10 min, or off |
| Escalate to the stronger vibration pattern | From the 3rd repeat | `escalate_after_repeats` (`null` = off) | On or off |
| Snooze | 10 min | `snooze_s` | 5 to 30 min |
| Absence before the away detector fires | 10 s | `away_detect_s` | No (file only) |
| Away with no input before auto-pausing the session | 10 min | `auto_pause_away_s` | 5 to 30 min |

**Pomodoro (optional, FR-01).** Off by default and switched on per session from Home [`pomodoro.enabled` remembers the last choice]. Work periods of 25 min [`pomodoro.work_min`] alternate with 5 min breaks [`pomodoro.break_min`]. A break pauses the session like the Break button (camera off) and sends a "break time" alert; when it ends, the session resumes by itself with a "back to work" alert (pattern 4). Manual pauses don't stop the Pomodoro clock.

Every state change is written to the `events` table with a timestamp, so the report and dashboard are built from the same record the alerts used.

## 9. Alert delivery

Every alert goes to exactly one sink. In practice that is the desktop sink: a short ping plus a desktop notification on the same computer. The band sink sits first in the chain to show where the band would plug in, but it is a stub whose `available()` always returns False. Every sink implements the same interface, so the rules never know which device is in use.

```python
class AlertSink(Protocol):
    name: str
    async def available(self) -> bool: ...
    async def send(self, alert: Alert) -> bool: ...   # False = try the next sink

@dataclass(frozen=True)
class Alert:
    kind: Literal["distraction", "posture", "pomodoro", "test"]
    label: str        # e.g. "phone", "window", "slouching"
    pattern: int      # alert pattern ID, table below
    created_at: float
```

The dispatcher tries sinks in priority order (band stub → desktop) and moves on if `send` fails or takes longer than 2 s [`alerts.sink_timeout_s`]. The desktop also always shows the alert as an in-app banner while the window is visible.

**Desktop sink.** It plays the ping for the alert's pattern first [`alerts.ping`], then shows a silent desktop notification, so the two sounds never overlap. The ping doesn't need notification permission, so the user still hears an alert if notifications are blocked or in Do Not Disturb. On macOS the first session asks for notification permission once. Notification text is short and generic: a title ("FocusBand: distraction", "FocusBand: still distracted" when escalated, "FocusBand: posture") and one line, the posture tip for posture alerts (`alerts/messages.py`).

**Alert patterns.** Each alert carries a pattern ID. The desktop plays it as a ping (WAVs made by `scripts/make_sounds.py`); the band design would play it as a vibration (on and off times in milliseconds).

| ID | Used for | Ping on the computer | Band vibration (design) |
| --- | --- | --- | --- |
| 1 | Distraction | Two beeps at 880 Hz | 400 on, 200 off, 400 on |
| 2 | Posture | One soft low tone at 440 Hz | 150 on, 100 off, 150 on, 100 off, 150 on |
| 3 | Escalated distraction | Three fast beeps at 1320 Hz | 800 on, 200 off, 800 on, 200 off, 800 on |
| 4 | Test | A rising chirp | 100 on |

### Custom band: Bluetooth LE protocol (design only, not implemented)

The band is presented as a design. This contract describes how it would work: the band is a BLE peripheral and the desktop app the central. The desktop ships only `BleBandSink` as a stub (`available()` returns False, `send()` is never reached), so the dispatcher chain shows where a real band would go.

- **Advertising name:** starts with `FocusBand-`, followed by the last 4 hex digits of the chip's MAC address.
- **Alert service:** a custom 128-bit service UUID. Generate it once with `uuidgen` and put it in `shared/ble_contract.json` so the desktop and firmware read the same values.
- **Alert characteristic** (same base UUID, write without response): 4 bytes — `version` (1), `pattern_id` (1 to 4), `intensity` (0 to 255), `reserved` (0).
- **Battery:** the standard Battery Service (0x180F) with Battery Level (0x2A19), read once a minute and shown in the app.
- **Intended desktop behaviour (if built):** `bleak` scans for the service UUID, connects, and stays connected for the session. On disconnect it retries every 10 s and falls through to the next sink meanwhile. Pairing happens in Settings: Scan, pick the band, receive pattern 4.
- **Intended firmware (if built):** a small ESP32-C3 or nRF52840 board drives a coin vibration motor by PWM (`intensity` → duty cycle), plays `pattern_id` from the table above without blocking BLE, and reports battery each minute.

## 10. Desktop screens

One window switches between pages (Welcome on first run → Calibration → Home → Session), with Settings as a dialog and a tray or menu-bar icon; the session page is the one the demo lives on. Closing the window keeps the app running in the tray. The look follows the system light or dark mode.

| Screen | Contents | Priority |
| --- | --- | --- |
| Welcome and consent | What the camera analyses, what is stored, camera permission request, link to Delete my data | P0 |
| Calibration wizard | The two steps from section 7 with a live preview, a countdown and a pass or retry result per step | P0 |
| Home | Start session, an optional Pomodoro toggle, the last session's summary, Recalibrate and Settings | P0 |
| Session | Live preview with skeleton overlay toggle, "camera on" indicator, timer, focus state chip, posture score, tip banner, Pause, Break, Snooze and End buttons; also the alert banner, the "move back or tilt the camera" hint, the camera-moved warning with Recalibrate, and the Pomodoro countdown | P0 |
| Settings | Thresholds from section 8, Pomodoro lengths, camera choice, overlay default, alert sound on or off, Send test alert, band shown as "coming soon", session retention and Delete my data | P0 |
| Session report | Focus time vs total time, distractions by type with counts and minutes, posture score over the session, the 3 most common posture issues with their tips. Opens when a session ends and from Home; built only from the stored rows (`logic/report.py`) | P1 |
| Dashboard | Focus minutes per day, distractions per hour of work, average posture score, for the last 7 or 30 days, with totals for the period. Opened from Home; aggregates each session's report (`logic/stats.py`), so the two always agree. Distractions per hour and focus share use running time, not pauses or breaks | P1 |
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
  kind TEXT NOT NULL,                -- distraction | posture | away | break | pause | snooze | alert
  label TEXT,                        -- phone, window, desk_object, slouching, ...
  started_at TEXT NOT NULL,
  ended_at TEXT,
  alert_sink TEXT                    -- desktop (or band, if ever built), for alert rows
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
  values_json TEXT NOT NULL          -- baseline metrics, window yaw
);
```

Settings live in `settings.json` next to the database. These defaults are the single source for every threshold and timing in sections 5 to 9; `app/logic/` reads them and never hard-codes a number. The top-level timing keys are what the Settings screen exposes (ranges in section 8). The nested blocks are tuning values, edited in the file during replay evaluation (section 12). `storage/settings.py` fills any missing key from these defaults, so older settings files keep working. Defaults:

```json
{
  "camera_index": 0,
  "overlay": true,
  "consent_given": false,

  "distraction_threshold_s": {"phone": 60, "looking_away": 60, "desk_object": 60, "away": 60},
  "focus_reset_s": 5,
  "away_detect_s": 10,
  "repeat_alert_s": 120,
  "escalate_after_repeats": 3,
  "posture_threshold_s": 120,
  "posture_cooldown_s": 300,
  "snooze_s": 600,
  "auto_pause_away_s": 600,
  "pomodoro": {"enabled": false, "work_min": 25, "break_min": 5},
  "delete_sessions_after_days": null,

  "vision": {
    "capture_width": 640, "capture_height": 480, "capture_fps": 30,
    "yolo_every_n": 3, "yolo_imgsz": 416, "hands_every_n": 1,
    "shoulders_missing_warn_s": 5, "max_read_failures": 30,
    "mp_min_confidence": 0.5, "yolo_conf": 0.25, "grasp_curl_ratio": 1.4,
    "yolo_classes": [
      "cell phone", "keyboard", "mouse", "laptop", "book", "cup", "bottle", "wine glass", "remote",
      "scissors", "sports ball", "teddy bear", "toothbrush", "fork", "knife", "spoon",
      "banana", "apple", "orange", "clock", "vase", "frisbee"
    ]
  },
  "smoothing": {"ema_alpha": 0.3, "bool_window_s": 2, "bool_ratio": 0.7},
  "detectors": {
    "phone_conf": 0.45, "phone_hand_dist": 0.1, "phone_pitch_down_deg": 20,
    "look_yaw_deg": 25, "look_pitch_up_deg": 20, "window_yaw_tol_deg": 15,
    "away_shoulder_vis": 0.5,
    "work_classes": ["keyboard", "mouse", "laptop", "book"]
  },
  "calibration": {
    "upright_s": 10, "window_s": 3, "recalibrate_shift": 0.15,
    "min_valid_ratio": 0.8, "recalibrate_check_s": 3
  },
  "posture": {
    "slouch_pct": 15, "lean_pct": 20, "neck_pitch_deg": 20,
    "tilt_roll_deg": 10, "shoulder_angle_deg": 7,
    "penalty_weight": 60, "dead_zone": 0.5, "bad_score": 70, "bad_window_s": 30, "bad_ratio": 0.9,
    "sample_interval_s": 10
  },
  "alerts": {"sink_timeout_s": 2, "ping": true}
}
```

`consent_given` records that the user accepted the Welcome screen; it is false again after Delete my data. `delete_sessions_after_days` is off (`null`) by default. When set to N, sessions that started more than N days ago are deleted at app start, together with their `events` and `posture_samples` rows. Calibration rows are kept. The Settings screen offers off, 7, 30 or 90 days.

## 12. Repository, testing and acceptance

The repo separates models from rules so that every rule can be tested with fake `FrameFeatures` and no camera.

```text
focusband/
  app/
    main.py              # entry point: Qt app, theme, old-session cleanup, main window
    runtime.py           # vision and logic threads, and the Engine the UI drives them through
    contracts.py         # shared frozen dataclasses and AlertSink (stdlib only)
    vision/              # capture.py, landmarkers.py, objects.py, features.py
    logic/               # detectors.py, posture.py, state_machine.py, calibration.py, session.py, report.py, stats.py, ...
    alerts/              # dispatcher.py, desktop.py, sounds.py (+ sounds/*.wav), messages.py, runner.py, ble_band.py (stub)
    storage/             # db.py, settings.py
    ui/                  # main_window.py, welcome.py, wizard.py, home.py, session.py, settings.py, tray.py, theme.py, widgets.py; report.py, dashboard.py (P1)
  models/                # .task and .pt files, downloaded by a setup script
  shared/ble_contract.json  # band design: UUIDs and pattern table (not used at runtime)
  tests/
    unit/                # rules and state machine with synthetic features
    clips/               # consented test videos, git-ignored
    eval.py              # replays clips and scores detectors
```

**Testing**

- **Unit tests (pytest):** every detector, the posture score, and every state-machine transition, fed with hand-built `FrameFeatures` sequences. Target: logic modules fully covered, and the suite runs in under 10 s.
- **Replay evaluation:** each team member records consented 3-minute clips for each scenario (focused typing, reading notes, phone, window, fidget object, away, slouching, leaning in), in daylight and lamplight.
  - **Recording:** `FOCUSBAND_DEV_RECORDER=1 python scripts/record_clip.py NAME --behaviour phone`. It runs only with that flag (it is the one piece of code that writes camera frames to disk), asks that everyone in view has agreed, and saves what the app sees (mirrored, capture size) into the git-ignored `tests/clips/`.
  - **Calibration and labels:** every clip starts with 15 s sitting upright facing the screen; `eval.py` calibrates each clip from that opening (and from a `window_calibration` interval if one is labelled). During recording, Space marks when the behaviour starts and stops, appending rows to `tests/clips/labels.csv` (`clip, behaviour, start_s, end_s`); rows can also be added or corrected by hand.
  - **Scoring:** `python tests/eval.py` runs the real pipeline once per clip (caching FrameFeatures, never images, in `tests/clips/.cache`) and replays the real calibration and SessionLogic. A labelled distraction long enough to need an alert counts as detected if an alert of its type arrives before it ends (plus 5 s grace); `window` intervals also report whether the label was `window`. Distraction alerts outside labelled distractions are false alerts, reported per 30 minutes of clean time. Posture intervals long enough to need an alert must get one naming the right issue. It prints PASS or FAIL for each acceptance criterion below and exits non-zero on a failure, so tuning `settings.json` and re-running takes seconds.
- **Device tests:** on one Windows and one macOS laptop — camera permission, notification permission, the four pings audible and distinct, and packaged build start-up.
- **Soak test:** a 60-minute genuine work session on each OS, checking CPU, memory growth and false alerts.

**Acceptance criteria for the demo**

- [ ] Each of the 4 distractions held for 60 s triggers an alert in at least 9 of 10 replay clips.
- [ ] No more than 1 false alert in a 30-minute focused session.
- [ ] Slouching and leaning in held for 2 minutes trigger a posture ping and the correct tip.
- [ ] At least 15 fps on the slowest team laptop with the overlay on.
- [ ] The ping and desktop notification arrive within 1 s of the alert threshold.
- [ ] The session report matches the events logged during the session.
- [ ] A search of the app data folder after a session finds no image or video files.
- [ ] The app makes no network connections during a session.

## 13. Two-week plan, IBM Bob and risks

The P0 demo works end to end on desktop notifications and pings by day 5. Everything runs on the computer: there is no watch or phone delivery. Days 11 and 12 go to the optional desk-object fine-tune. Developer A owns vision and logic; developer B owns the app shell, UI, storage and alerts. The three hardware teammates design and present the band concept and also record and label test clips.

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
| Developer B | Band stub sink, desktop sink with pings, Send test alert | 6–7 |
| Developer B | Report and dashboard | 8–9 |
| Developer B | Tray icon polish, Delete my data, consent screen | 10–12 |
| Both developers | Packaging, fixes, demo prep | 13–14 |
| Hardware team | Band concept: design, mock-up and presentation of how it would work | 1–7 |
| Hardware team | Record and label test clips | 4–5 |

Milestones: interfaces agreed (day 1), P0 demo on desktop (day 5), **P0 and P1 freeze (day 10)**, final demo (day 14). Days 11 and 12 hold stretch work (desk-object fine-tune), so a slip in the core plan eats into stretch work rather than the demo.

**Handoffs that keep the two developers unblocked**

- Day 1: agree on `FrameFeatures`, `Alert` and the `AlertSink` interface (sections 5 and 9) before writing code. B builds the UI against a fake feature stream; A tests rules without the UI.
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
| Notifications blocked or in Do Not Disturb during the demo | Medium | The ping plays regardless of notification permission; check the macOS permission prompt was accepted before the demo |
| False alerts annoy users | Medium | 1-minute threshold, 5 s focus reset, Snooze, and replay tuning on days 9 and 10 |

## Sources

- [IBM Bob announcement, April 28, 2026 (Verdict)](https://www.verdict.co.uk/ibm-launches-bob/)
- [MediaPipe PoseLandmarker Python API](https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker)
- [MediaPipe: Tasks API replaces the legacy Solutions API (MGT-python wiki)](https://github.com/fourMs/MGT-python/wiki/10-%E2%80%90-Pose-and-Motion-Capture)
- [Ultralytics YOLO26 and licensing](https://docs.ultralytics.com/)
