"""settings.json: defaults, loading and saving (DESIGN §11).

DEFAULTS is the single source for every threshold and timing. Missing keys in the
user's file are filled from DEFAULTS, so older files keep working. The ntfy topic is
a secret and never belongs here; it lives in the OS keychain.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

APP_NAME = "FocusBand"

DEFAULTS: dict[str, Any] = {
    "camera_index": 0,
    "overlay": True,
    "watch_paired": False,
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
        "shoulders_missing_warn_s": 5, "max_read_failures": 30,
    },
    "smoothing": {"ema_alpha": 0.3, "bool_window_s": 2, "bool_ratio": 0.7},
    "detectors": {
        "phone_conf": 0.45, "phone_hand_dist": 0.1, "phone_pitch_down_deg": 20,
        "look_yaw_deg": 25, "look_pitch_up_deg": 20, "window_yaw_tol_deg": 15,
        "away_shoulder_vis": 0.5,
    },
    "calibration": {
        "upright_s": 10, "window_s": 3, "work_zone_s": 3,
        "work_zone_pad": 0.3, "recalibrate_shift": 0.15,
    },
    "posture": {
        "slouch_pct": 15, "lean_pct": 20, "neck_pitch_deg": 20,
        "tilt_roll_deg": 10, "shoulder_angle_deg": 7,
        "penalty_weight": 20, "bad_score": 70, "bad_window_s": 30, "bad_ratio": 0.9,
        "sample_interval_s": 10,
    },
    "alerts": {"sink_timeout_s": 2},
}


def app_data_dir() -> Path:
    """The user's app data folder, where settings.json and the database live."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def default_path() -> Path:
    return app_data_dir() / "settings.json"


def _merge(defaults: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Return defaults overlaid with the user's values, recursing into nested blocks."""
    merged = copy.deepcopy(defaults)
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(path: Path | None = None) -> dict[str, Any]:
    """Load settings, filling any missing key from DEFAULTS.

    A missing file gives the defaults. An unreadable file also gives the defaults and
    logs a warning; the file is left untouched so the user can fix it.
    """
    path = path or default_path()
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(DEFAULTS)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read %s (%s); using defaults", path, e)
        return copy.deepcopy(DEFAULTS)
    if not isinstance(user, dict):
        log.warning("%s is not a JSON object; using defaults", path)
        return copy.deepcopy(DEFAULTS)
    return _merge(DEFAULTS, user)


def save(settings: dict[str, Any], path: Path | None = None) -> None:
    """Write settings atomically, so a crash mid-write never leaves a broken file."""
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(path)
