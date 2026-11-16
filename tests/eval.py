"""Replay evaluation (DESIGN §12): replays recorded clips through the real pipeline and scores
the detectors against labelled intervals, for the acceptance criteria.

Usage: python tests/eval.py [--clip NAME ...] [--settings FILE] [--mirror] [--no-cache] [--json OUT]

Clips live in the git-ignored tests/clips/ (record them with scripts/record_clip.py) and are
labelled in tests/clips/labels.csv: clip, behaviour, start_s, end_s. Behaviours: phone,
looking_away, window, desk_object, away (distractions); slouching, leaning_in (posture);
focused (optional, informational); window_calibration (optional, for the window step).

Each clip calibrates itself from its upright opening, then the real SessionLogic runs over the
rest. The vision pass is cached as FrameFeatures (never images) in tests/clips/.cache, so
re-running after tuning settings.json takes seconds. Exit code 0 when every acceptance check
passes, 1 when one fails, 2 when there is nothing to evaluate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.contracts import Detection, FrameFeatures, HandInfo  # noqa: E402
from app.logic.calibration import Calibration, UprightStep, WindowStep  # noqa: E402
from app.logic.session import SessionLogic  # noqa: E402
from app.storage import settings as settings_mod  # noqa: E402

CLIPS_DIR = ROOT / "tests" / "clips"
CACHE_VERSION = 1

DISTRACTIONS = {"phone": "phone", "looking_away": "looking_away", "window": "looking_away",
                "desk_object": "desk_object", "away": "away"}
POSTURE = {"slouching", "leaning_in"}
KNOWN = set(DISTRACTIONS) | POSTURE | {"focused", "window_calibration"}

CALIBRATION_START_S = 1.0   # let the smoothing settle before the upright opening is measured
DETECTION_TARGET = 0.9      # §12: an alert in at least 9 of 10 clips
FALSE_ALERTS_PER_30_MIN = 1.0  # §12: no more than 1 false alert in a 30-minute focused session


# --- labels -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Label:
    clip: str
    behaviour: str
    start: float
    end: float


def read_labels(path: Path) -> dict[str, list[Label]]:
    out: dict[str, list[Label]] = defaultdict(list)
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            b = row["behaviour"].strip()
            if b not in KNOWN:
                raise ValueError(f"{path.name} line {n}: unknown behaviour {b!r}")
            start, end = float(row["start_s"]), float(row["end_s"])
            if end <= start:
                raise ValueError(f"{path.name} line {n}: end_s must be after start_s")
            out[row["clip"].strip()].append(Label(row["clip"].strip(), b, start, end))
    return out


# --- vision pass (cached) ------------------------------------------------------------------------

class PipelineLike(Protocol):
    def process(self, frame: Any) -> tuple[FrameFeatures, Any]: ...
    def reset(self) -> None: ...


def extract_features(clip: Path, settings: dict[str, Any], mirror: bool, pipeline: PipelineLike) -> list[FrameFeatures]:
    import cv2
    import numpy as np

    from app.vision.capture import Frame, fit_frame

    v = settings["vision"]
    cap = cv2.VideoCapture(str(clip))
    if not cap.isOpened():
        raise OSError(f"Could not open {clip}")
    fps = cap.get(cv2.CAP_PROP_FPS) or v["capture_fps"]
    pipeline.reset()
    features: list[FrameFeatures] = []
    i = 0
    try:
        while True:
            ok, raw = cap.read()
            if not ok:
                break
            image = fit_frame(np.asarray(raw, dtype=np.uint8), v["capture_width"], v["capture_height"])
            if mirror:
                image = np.asarray(cv2.flip(image, 1), dtype=np.uint8)
            f, _ = pipeline.process(Frame(image=image, timestamp_ms=int(round(i * 1000 / fps)) + i))
            features.append(f)
            i += 1
    finally:
        cap.release()
    return features


def _cache_key(clip: Path, settings: dict[str, Any], mirror: bool) -> str:
    st = clip.stat()
    blob = json.dumps([CACHE_VERSION, st.st_size, st.st_mtime_ns, settings["vision"],
                       settings["smoothing"]["ema_alpha"], mirror], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def features_to_json(fs: list[FrameFeatures]) -> list[dict[str, Any]]:
    return [asdict(f) for f in fs]


def features_from_json(rows: list[dict[str, Any]]) -> list[FrameFeatures]:
    out = []
    for r in rows:
        r = dict(r)
        r["hands"] = [HandInfo(bbox=tuple(h["bbox"]), grasp=h["grasp"]) for h in r["hands"]]
        r["objects"] = [Detection(cls=o["cls"], confidence=o["confidence"], bbox=tuple(o["bbox"])) for o in r["objects"]]
        for k in ("shoulder_mid", "face_bbox"):
            if r.get(k) is not None:
                r[k] = tuple(r[k])
        out.append(FrameFeatures(**r))
    return out


def load_features(clip: Path, settings: dict[str, Any], mirror: bool, use_cache: bool,
                  pipeline_factory: Any) -> list[FrameFeatures]:
    cache = clip.parent / ".cache" / f"{clip.stem}.{_cache_key(clip, settings, mirror)}.json"
    if use_cache and cache.exists():
        return features_from_json(json.loads(cache.read_text(encoding="utf-8")))
    fs = extract_features(clip, settings, mirror, pipeline_factory())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(features_to_json(fs)), encoding="utf-8")
    return fs


# --- logic replay ------------------------------------------------------------------------------

@dataclass(frozen=True)
class AlertAt:
    t: float
    kind: str
    label: str
    pattern: int


@dataclass
class Replay:
    calibrated: bool
    reason: str | None = None
    calibration_end: float = 0.0
    end_t: float = 0.0
    alerts: list[AlertAt] = field(default_factory=list)


def replay(features: list[FrameFeatures], labels: list[Label], settings: dict[str, Any]) -> Replay:
    upright = UprightStep(settings)
    for f in features:
        if f.t >= CALIBRATION_START_S:
            upright.add(f)
            if upright.done():
                break
    if not upright.done():
        return Replay(False, "clip is shorter than the upright opening")
    result = upright.result()
    if result.value is None:
        return Replay(False, f"upright calibration failed: {result.reason}")
    baseline = result.value
    calibration_end = CALIBRATION_START_S + upright.elapsed_s

    window_yaw = None
    for lab in labels:
        if lab.behaviour == "window_calibration":
            step = WindowStep(settings, baseline)
            for f in features:
                if lab.start <= f.t <= lab.end:
                    step.add(f)
            window_yaw = step.result().value if step.done() else None

    session = SessionLogic(settings, Calibration(baseline, window_yaw), wall_start=0.0)
    out = Replay(True, calibration_end=calibration_end)
    for f in features:
        if f.t <= calibration_end:
            continue
        u = session.update(f)
        out.end_t = f.t
        out.alerts += [AlertAt(f.t, a.kind, a.label, a.pattern) for a in u.alerts]
    return out


# --- scoring ----------------------------------------------------------------------------------

@dataclass
class ClipScore:
    clip: str
    calibrated: bool
    reason: str | None = None
    scorable: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    detected: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    window_labelled: int = 0
    window_correct: int = 0
    false_distraction: list[AlertAt] = field(default_factory=list)
    posture_scorable: int = 0
    posture_detected: int = 0
    posture_wrong_label: int = 0
    false_posture: list[AlertAt] = field(default_factory=list)
    clean_s: float = 0.0          # monitored time outside labelled distractions


def _union_length(spans: list[tuple[float, float]]) -> float:
    total, cur = 0.0, None
    for a, b in sorted(spans):
        if cur is None or a > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    return total + (cur[1] - cur[0] if cur else 0.0)


def score_clip(clip: str, r: Replay, labels: list[Label], settings: dict[str, Any], grace_s: float) -> ClipScore:
    sc = ClipScore(clip, r.calibrated, r.reason)
    if not r.calibrated:
        return sc
    smoothing = settings["smoothing"]["bool_window_s"]
    p = settings["posture"]
    posture_needs = settings["posture_threshold_s"] + p["bad_ratio"] * p["bad_window_s"] + 1 + smoothing
    distraction_alerts = [a for a in r.alerts if a.kind == "distraction"]
    posture_alerts = [a for a in r.alerts if a.kind == "posture"]
    monitored = [lab for lab in labels if lab.end > r.calibration_end]

    def within(a: AlertAt, lab: Label) -> bool:
        return lab.start <= a.t <= lab.end + grace_s

    distraction_labels = [lab for lab in monitored if lab.behaviour in DISTRACTIONS]
    for lab in distraction_labels:
        kind = DISTRACTIONS[lab.behaviour]
        needs = settings["distraction_threshold_s"][kind] + smoothing
        if kind == "away":
            needs += settings["away_detect_s"]
        if lab.end - max(lab.start, r.calibration_end) < needs:
            continue  # too short to require an alert
        sc.scorable[lab.behaviour] += 1
        hits = [a for a in distraction_alerts if within(a, lab) and DISTRACTIONS.get(a.label) == kind]
        if hits:
            sc.detected[lab.behaviour] += 1
        if lab.behaviour == "window":
            sc.window_labelled += 1
            sc.window_correct += any(a.label == "window" for a in hits)
    sc.false_distraction = [a for a in distraction_alerts if not any(within(a, lab) for lab in distraction_labels)]

    posture_labels = [lab for lab in monitored if lab.behaviour in POSTURE]
    for lab in posture_labels:
        if lab.end - max(lab.start, r.calibration_end) < posture_needs:
            continue
        sc.posture_scorable += 1
        hits = [a for a in posture_alerts if within(a, lab)]
        if any(a.label == lab.behaviour for a in hits):
            sc.posture_detected += 1
        elif hits:
            sc.posture_wrong_label += 1
    sc.false_posture = [a for a in posture_alerts if not any(within(a, lab) for lab in posture_labels)]

    spans = [(max(lab.start, r.calibration_end), min(lab.end + grace_s, r.end_t)) for lab in distraction_labels]
    sc.clean_s = max(0.0, (r.end_t - r.calibration_end) - _union_length([s for s in spans if s[1] > s[0]]))
    return sc


@dataclass
class Summary:
    detection: dict[str, tuple[int, int]]   # behaviour -> (detected, scorable)
    false_distraction: int
    clean_minutes: float
    posture: tuple[int, int, int]            # detected, scorable, wrong label
    false_posture: int
    uncalibrated: list[str]
    checks: list[tuple[str, bool]]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(ok for _, ok in self.checks)


def summarise(scores: list[ClipScore]) -> Summary:
    det: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in scores:
        for b, n in s.scorable.items():
            det[b][1] += n
            det[b][0] += s.detected.get(b, 0)
    false_d = sum(len(s.false_distraction) for s in scores)
    clean_min = sum(s.clean_s for s in scores) / 60
    p_det = sum(s.posture_detected for s in scores)
    p_n = sum(s.posture_scorable for s in scores)
    p_wrong = sum(s.posture_wrong_label for s in scores)
    false_p = sum(len(s.false_posture) for s in scores)

    checks: list[tuple[str, bool]] = []
    for b, (d, n) in sorted(det.items()):
        checks.append((f"{b}: alert in {d}/{n} clips (need {DETECTION_TARGET:.0%})", n > 0 and d / n >= DETECTION_TARGET))
    if clean_min > 0:
        rate = false_d / clean_min * 30
        checks.append((f"false distraction alerts: {rate:.2f} per 30 min (max {FALSE_ALERTS_PER_30_MIN:g})",
                       rate <= FALSE_ALERTS_PER_30_MIN))
    if p_n:
        checks.append((f"posture: right alert and tip in {p_det}/{p_n} intervals", p_det == p_n))
    return Summary(
        detection={b: (d, n) for b, (d, n) in det.items()}, false_distraction=false_d, clean_minutes=clean_min,
        posture=(p_det, p_n, p_wrong), false_posture=false_p,
        uncalibrated=[s.clip for s in scores if not s.calibrated], checks=checks,
    )


# --- command line --------------------------------------------------------------------------------

def _real_pipeline_factory(settings: dict[str, Any]) -> Any:
    from app.vision.pipeline import VisionPipeline

    pipeline = None

    def make() -> Any:
        nonlocal pipeline
        if pipeline is None:
            pipeline = VisionPipeline.from_settings(settings)
        return pipeline
    return make


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay clips through FocusBand and score the detectors.")
    parser.add_argument("--clips", type=Path, default=CLIPS_DIR, help="clips folder (default tests/clips)")
    parser.add_argument("--labels", type=Path, help="labels CSV (default <clips>/labels.csv)")
    parser.add_argument("--clip", action="append", help="only this clip (repeatable)")
    parser.add_argument("--settings", type=Path, help="settings.json to evaluate (default: the app's)")
    parser.add_argument("--mirror", action="store_true", help="mirror frames (clips not made by record_clip.py)")
    parser.add_argument("--no-cache", action="store_true", help="re-run the vision pass")
    parser.add_argument("--grace", type=float, default=5.0, help="seconds an alert may come after an interval")
    parser.add_argument("--json", type=Path, help="also write the results as JSON")
    args = parser.parse_args(argv)

    settings = settings_mod.load(args.settings)
    labels = read_labels(args.labels or args.clips / "labels.csv")
    clips = sorted(p for ext in ("*.mp4", "*.mov", "*.avi", "*.mkv") for p in args.clips.glob(ext))
    if args.clip:
        clips = [c for c in clips if c.stem in set(args.clip)]
    if not clips:
        print(f"No clips in {args.clips}. Record some with scripts/record_clip.py (see DESIGN §12).")
        return 2

    factory = _real_pipeline_factory(settings)
    scores = []
    for clip in clips:
        clip_labels = labels.get(clip.stem, [])
        if not clip_labels:
            print(f"! {clip.name}: no labels; counted as focused throughout")
        features = load_features(clip, settings, args.mirror, not args.no_cache, factory)
        r = replay(features, clip_labels, settings)
        sc = score_clip(clip.stem, r, clip_labels, settings, args.grace)
        scores.append(sc)
        if not r.calibrated:
            print(f"✗ {clip.name}: {r.reason}")
            continue
        alerts = ", ".join(f"{a.label}@{a.t:.0f}s" for a in r.alerts) or "none"
        print(f"  {clip.name}: {r.end_t / 60:.1f} min, alerts: {alerts}")

    s = summarise(scores)
    print("\nDetection by behaviour (clips long enough to need an alert):")
    for b, (d, n) in sorted(s.detection.items()):
        print(f"  {b:<13} {d}/{n}")
    print(f"False distraction alerts: {s.false_distraction} in {s.clean_minutes:.1f} min without labelled distractions")
    pd, pn, pw = s.posture
    print(f"Posture: {pd}/{pn} correct, {pw} with the wrong issue, {s.false_posture} outside labelled posture")
    if s.uncalibrated:
        print(f"Not evaluated (calibration failed): {', '.join(s.uncalibrated)}")
    print("\nAcceptance (DESIGN §12):")
    for text, ok in s.checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {text}")
    if not s.checks:
        print("  nothing to check: label some behaviours long enough to need an alert")
    if args.json:
        args.json.write_text(json.dumps({
            "clips": [{**{k: v for k, v in asdict(sc).items() if k not in ("false_distraction", "false_posture")},
                       "false_distraction": [asdict(a) for a in sc.false_distraction],
                       "false_posture": [asdict(a) for a in sc.false_posture]} for sc in scores],
            "checks": [{"check": t, "passed": ok} for t, ok in s.checks],
        }, indent=2), encoding="utf-8")
    return 0 if s.passed else (2 if not s.checks else 1)


if __name__ == "__main__":
    sys.exit(main())
