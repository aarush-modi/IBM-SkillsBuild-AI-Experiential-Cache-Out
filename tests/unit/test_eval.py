"""Replay evaluation (tests/eval.py) with synthetic features, a tiny synthetic video and a fake
pipeline, so no real clips or models are needed."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.contracts import Detection, FrameFeatures, HandInfo
from app.storage.settings import DEFAULTS
from app.vision.capture import Frame
from app.vision.pipeline import PreviewFrame
from tests import eval as ev

FPS = 5
ROOT = Path(__file__).resolve().parents[2]
PHONE = dict(hands=[HandInfo((0.6, 0.6, 0.7, 0.7), grasp=True)],
             objects=[Detection("cell phone", 0.9, (0.62, 0.6, 0.68, 0.7))])
SLOUCH = dict(nose_to_shoulder_y=0.8 * 0.7)


def feat(t: float, **kw: Any) -> FrameFeatures:
    base: dict[str, Any] = dict(
        t=t, person_present=True, shoulder_visibility=0.95, head_yaw=0.0, head_pitch=-5.0, head_roll=0.0,
        shoulder_width=0.3, shoulder_angle=0.0, shoulder_mid=(0.5, 0.45), nose_to_shoulder_y=0.8,
        face_width=0.2, face_bbox=(0.4, 0.2, 0.6, 0.4), hands=[], objects=[],
    )
    base.update(kw)
    return FrameFeatures(**base)


def timeline(*parts: tuple[float, dict[str, Any]]) -> list[FrameFeatures]:
    """Consecutive (seconds, overrides) segments at FPS, starting at t=0."""
    out, t = [], 0.0
    for seconds, kw in parts:
        for _ in range(round(seconds * FPS)):
            out.append(feat(round(t, 6), **kw))
            t += 1 / FPS
    return out


def settings() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


def lab(behaviour: str, start: float, end: float) -> ev.Label:
    return ev.Label("c", behaviour, start, end)


# --- labels ----------------------------------------------------------------------------------

def test_read_labels(tmp_path: Path) -> None:
    p = tmp_path / "labels.csv"
    p.write_text("clip,behaviour,start_s,end_s\na,phone,20,95\na,slouching,100,260\nb,away,30,120\n")
    labels = ev.read_labels(p)
    assert [x.behaviour for x in labels["a"]] == ["phone", "slouching"] and labels["b"][0].end == 120


@pytest.mark.parametrize("row,msg", [("a,typing,1,2", "unknown behaviour"), ("a,phone,5,5", "after start_s")])
def test_bad_labels_are_rejected(tmp_path: Path, row: str, msg: str) -> None:
    p = tmp_path / "labels.csv"
    p.write_text(f"clip,behaviour,start_s,end_s\n{row}\n")
    with pytest.raises(ValueError, match=msg):
        ev.read_labels(p)


# --- replay and scoring --------------------------------------------------------------------------

def test_phone_detected_and_no_false_alerts() -> None:
    fs = timeline((16, {}), (30, {}), (80, PHONE), (60, {}))
    labels = [lab("phone", 46, 126)]
    r = ev.replay(fs, labels, settings())
    assert r.calibrated and r.calibration_end == pytest.approx(11, abs=0.5)
    sc = ev.score_clip("c", r, labels, settings(), grace_s=5)
    assert (sc.scorable["phone"], sc.detected["phone"]) == (1, 1)
    assert sc.false_distraction == []
    assert sc.clean_s > 60


def test_unlabelled_distraction_is_a_false_alert() -> None:
    fs = timeline((16, {}), (80, PHONE), (20, {}))
    r = ev.replay(fs, [], settings())
    sc = ev.score_clip("c", r, [], settings(), grace_s=5)
    assert [a.label for a in sc.false_distraction] == ["phone"]


def test_short_interval_is_not_scored() -> None:
    fs = timeline((16, {}), (30, PHONE), (30, {}))
    labels = [lab("phone", 16, 46)]
    sc = ev.score_clip("c", ev.replay(fs, labels, settings()), labels, settings(), grace_s=5)
    assert sc.scorable == {} and sc.false_distraction == []


def test_posture_detected_with_right_issue() -> None:
    fs = timeline((16, {}), (170, SLOUCH), (10, {}))
    labels = [lab("slouching", 16, 186)]
    sc = ev.score_clip("c", ev.replay(fs, labels, settings()), labels, settings(), grace_s=5)
    assert (sc.posture_detected, sc.posture_scorable, sc.posture_wrong_label) == (1, 1, 0)
    wrong = [lab("leaning_in", 16, 186)]
    sc = ev.score_clip("c", ev.replay(fs, wrong, settings()), wrong, settings(), grace_s=5)
    assert (sc.posture_detected, sc.posture_wrong_label) == (0, 1)


def test_calibration_failure_is_reported() -> None:
    fs = timeline((30, dict(person_present=False, shoulder_visibility=None)))
    r = ev.replay(fs, [], settings())
    assert not r.calibrated and "calibration failed" in (r.reason or "")
    assert not ev.score_clip("c", r, [], settings(), 5).calibrated


def test_summary_checks() -> None:
    good = ev.ClipScore("a", True, clean_s=1800)
    good.scorable["phone"], good.detected["phone"] = 10, 9
    s = ev.summarise([good])
    assert s.passed and len(s.checks) == 2
    bad = ev.ClipScore("b", True, clean_s=600)
    bad.scorable["away"] = 2
    bad.false_distraction = [ev.AlertAt(1, "distraction", "phone", 1), ev.AlertAt(9, "distraction", "phone", 1)]
    s = ev.summarise([good, bad])
    assert not s.passed
    # away 0/2 fails, phone 9/10 passes, 2 false alerts in 40 clean min = 1.5 per 30 min fails
    assert [ok for _, ok in s.checks] == [False, True, False]


def test_features_json_round_trip() -> None:
    fs = timeline((1, PHONE))
    assert ev.features_from_json(ev.features_to_json(fs)) == fs


# --- video reading and the command --------------------------------------------------------------

class FakePipeline:
    def __init__(self, script: list[FrameFeatures]) -> None:
        self.script = script
        self.frames: list[Frame] = []

    def process(self, frame: Frame) -> tuple[FrameFeatures, PreviewFrame]:
        self.frames.append(frame)
        f = self.script[min(len(self.frames) - 1, len(self.script) - 1)]
        return f, PreviewFrame(image=frame.image)

    def reset(self) -> None:
        self.frames = []


def write_video(path: Path, seconds: float, fps: int = FPS) -> None:
    import cv2

    w = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"mp4v"), fps, (64, 48))
    for i in range(round(seconds * fps)):
        img = np.zeros((48, 64, 3), np.uint8)
        img[:, :8] = 255  # a white stripe on the left
        w.write(img)
    w.release()


def test_extract_features_fits_mirrors_and_times(tmp_path: Path) -> None:
    clip = tmp_path / "c.mp4"
    write_video(clip, 2)
    fake = FakePipeline(timeline((2, {})))
    fs = ev.extract_features(clip, settings(), mirror=True, pipeline=fake)
    assert len(fs) == len(fake.frames) == 2 * FPS
    assert fake.frames[0].image.shape == (480, 640, 3)
    assert fake.frames[0].image[:, -20:].mean() > 200  # the stripe moved to the right: mirrored
    ts = [f.timestamp_ms for f in fake.frames]
    assert ts == sorted(set(ts))


def test_main_end_to_end_with_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = timeline((16, {}), (80, PHONE), (40, {}))
    write_video(tmp_path / "clip1.mp4", len(script) / FPS)
    (tmp_path / "labels.csv").write_text("clip,behaviour,start_s,end_s\nclip1,phone,16,96\n")
    made: list[int] = []

    def factory(_: dict[str, Any]) -> Any:
        def make() -> FakePipeline:
            made.append(1)
            return FakePipeline(script)
        return make

    monkeypatch.setattr(ev, "_real_pipeline_factory", factory)
    out = tmp_path / "result.json"
    assert ev.main(["--clips", str(tmp_path), "--json", str(out)]) == 0
    assert '"passed": true' in out.read_text()
    assert ev.main(["--clips", str(tmp_path)]) == 0
    assert len(made) == 1  # the second run used the feature cache
    assert list((tmp_path / ".cache").glob("clip1.*.json"))


def test_main_without_clips(tmp_path: Path) -> None:
    assert ev.main(["--clips", str(tmp_path)]) == 2


def test_recorder_is_off_without_the_flag() -> None:
    env = {"PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "record_clip.py"), "x", "--behaviour", "phone"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "FOCUSBAND_DEV_RECORDER=1" in r.stdout
