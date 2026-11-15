"""Alert sinks, dispatcher, pings and runner. Fakes only: no notification or sound is produced."""

from __future__ import annotations

import asyncio
import copy
import wave
from typing import Any

import pytest

from app.alerts import desktop as desktop_mod
from app.alerts import messages, sounds
from app.alerts.ble_band import BleBandSink
from app.alerts.desktop import DesktopSink
from app.alerts.dispatcher import Dispatcher
from app.alerts.runner import AlertRunner
from app.contracts import PATTERN_DISTRACTION, PATTERN_ESCALATED, PATTERN_POSTURE, PATTERN_TEST, Alert
from app.logic.posture import TIPS
from app.storage.settings import DEFAULTS

PHONE = Alert(kind="distraction", label="phone", pattern=PATTERN_DISTRACTION, created_at=0.0)


class FakeNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send(self, **kw: Any) -> str:
        if self.fail:
            raise RuntimeError("no notification backend")
        self.sent.append(kw)
        return "id"

    async def request_authorisation(self) -> bool:
        if self.fail:
            raise RuntimeError("no backend")
        return True


class Player:
    def __init__(self, ok: bool = True) -> None:
        self.played: list[int] = []
        self.ok = ok

    def __call__(self, pattern: int) -> bool:
        self.played.append(pattern)
        return self.ok


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- pings ------------------------------------------------------------------------------

@pytest.mark.parametrize("pattern", [PATTERN_DISTRACTION, PATTERN_POSTURE, PATTERN_ESCALATED, PATTERN_TEST])
def test_each_pattern_has_a_short_wav(pattern: int) -> None:
    with wave.open(str(sounds.sound_path(pattern))) as w:
        seconds = w.getnframes() / w.getframerate()
    assert 0.1 < seconds < 1.0


def test_play_uses_afplay_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sounds.sys, "platform", "darwin")
    monkeypatch.setattr(sounds.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    assert sounds.play(PATTERN_DISTRACTION)
    assert calls == [["afplay", str(sounds.sound_path(PATTERN_DISTRACTION))]]


def test_play_without_player_or_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sounds.sys, "platform", "linux")
    monkeypatch.setattr(sounds.shutil, "which", lambda cmd: None)
    assert not sounds.play(PATTERN_DISTRACTION)
    assert not sounds.play(99)


# --- messages --------------------------------------------------------------------------

@pytest.mark.parametrize("label", ["phone", "desk_object", "looking_away", "window", "away"])
def test_every_distraction_label_has_text(label: str) -> None:
    alert = Alert("distraction", label, PATTERN_DISTRACTION, 0.0)
    assert messages.body(alert) == messages.DISTRACTION_TEXT[label]
    assert messages.title(alert) == "FocusBand: distraction"


def test_escalated_and_posture_and_test_text() -> None:
    assert messages.title(Alert("distraction", "phone", PATTERN_ESCALATED, 0.0)) == "FocusBand: still distracted"
    posture = Alert("posture", "slouching", PATTERN_POSTURE, 0.0)
    assert messages.title(posture) == "FocusBand: posture" and messages.body(posture) == TIPS["slouching"]
    assert messages.title(Alert("test", "test", PATTERN_TEST, 0.0)) == "FocusBand: test alert"


# --- sinks -------------------------------------------------------------------------------

def test_band_stub_is_never_available() -> None:
    band = BleBandSink()
    assert not run(band.available()) and not run(band.send(PHONE))


def test_desktop_pings_and_notifies_silently() -> None:
    notifier, player = FakeNotifier(), Player()
    sink = DesktopSink(ping=True, notifier=notifier, player=player)
    assert run(sink.send(PHONE))
    assert player.played == [PATTERN_DISTRACTION]
    assert notifier.sent[0]["title"] == "FocusBand: distraction"
    assert notifier.sent[0]["sound"] is None  # the ping is the sound; no double sound


def test_desktop_ping_off() -> None:
    player = Player()
    assert run(DesktopSink(ping=False, notifier=FakeNotifier(), player=player).send(PHONE))
    assert player.played == []


def test_desktop_counts_as_delivered_if_only_the_ping_worked() -> None:
    sink = DesktopSink(ping=True, notifier=FakeNotifier(fail=True), player=Player())
    assert run(sink.send(PHONE))
    assert not run(DesktopSink(ping=False, notifier=FakeNotifier(fail=True), player=Player()).send(PHONE))


def test_prepare_survives_backend_errors() -> None:
    assert run(DesktopSink(notifier=FakeNotifier()).prepare())
    assert not run(DesktopSink(notifier=FakeNotifier(fail=True)).prepare())


# --- dispatcher ----------------------------------------------------------------------------

class Sink:
    def __init__(self, name: str, available: bool = True, ok: bool = True, delay: float = 0.0,
                 error: bool = False) -> None:
        self.name, self._available, self.ok, self.delay, self.error = name, available, ok, delay, error
        self.sent: list[Alert] = []

    async def available(self) -> bool:
        return self._available

    async def send(self, alert: Alert) -> bool:
        await asyncio.sleep(self.delay)
        if self.error:
            raise RuntimeError("boom")
        self.sent.append(alert)
        return self.ok


def test_band_stub_falls_through_to_desktop() -> None:
    desktop = Sink("desktop")
    assert run(Dispatcher([BleBandSink(), desktop], 2).dispatch(PHONE)) == "desktop"
    assert desktop.sent == [PHONE]


@pytest.mark.parametrize("bad", [
    Sink("slow", delay=0.5), Sink("broken", error=True), Sink("refuses", ok=False), Sink("off", available=False),
])
def test_bad_sinks_are_skipped(bad: Sink) -> None:
    good = Sink("good")
    assert run(Dispatcher([bad, good], timeout_s=0.1).dispatch(PHONE)) == "good"


def test_nothing_delivered() -> None:
    assert run(Dispatcher([BleBandSink(), Sink("x", ok=False)], 1).dispatch(PHONE)) is None


def test_from_settings_is_band_then_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop_mod, "DesktopNotifier", lambda **kw: FakeNotifier())
    s = copy.deepcopy(DEFAULTS)
    s["alerts"]["ping"] = False
    d = Dispatcher.from_settings(s)
    assert [x.name for x in d.sinks] == ["band", "desktop"]
    assert d.timeout_s == DEFAULTS["alerts"]["sink_timeout_s"]
    assert d.sinks[1].ping is False  # type: ignore[attr-defined]


# --- runner ---------------------------------------------------------------------------------

def test_runner_delivers_from_a_background_loop() -> None:
    desktop = Sink("desktop")
    with AlertRunner(Dispatcher([BleBandSink(), desktop], 2)) as runner:
        runner.prepare(timeout_s=2)
        assert runner.submit(PHONE).result(timeout=2) == "desktop"
    assert desktop.sent == [PHONE]
