import json
from pathlib import Path

from app.storage import settings


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert settings.load(tmp_path / "nope.json") == settings.DEFAULTS


def test_partial_file_is_filled_from_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"snooze_s": 900, "detectors": {"phone_conf": 0.6}}))

    s = settings.load(path)

    assert s["snooze_s"] == 900
    assert s["detectors"]["phone_conf"] == 0.6
    assert s["detectors"]["look_yaw_deg"] == settings.DEFAULTS["detectors"]["look_yaw_deg"]
    assert s["posture"] == settings.DEFAULTS["posture"]


def test_corrupt_file_gives_defaults_and_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json")

    assert settings.load(path) == settings.DEFAULTS
    assert path.read_text() == "{not json"


def test_load_does_not_share_state_with_defaults(tmp_path: Path) -> None:
    s = settings.load(tmp_path / "nope.json")
    s["detectors"]["phone_conf"] = 0.99

    assert settings.DEFAULTS["detectors"]["phone_conf"] == 0.45


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "settings.json"
    s = settings.load(path)
    s["camera_index"] = 2

    settings.save(s, path)

    assert settings.load(path)["camera_index"] == 2


def test_defaults_match_design_doc() -> None:
    """DEFAULTS must equal the settings.json block in docs/DESIGN.md §11."""
    doc = (Path(__file__).parents[2] / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    block = doc.split("```json\n", 1)[1].split("```", 1)[0]
    assert json.loads(block) == settings.DEFAULTS


def test_no_secret_in_defaults() -> None:
    assert "ntfy_topic" not in settings.DEFAULTS
