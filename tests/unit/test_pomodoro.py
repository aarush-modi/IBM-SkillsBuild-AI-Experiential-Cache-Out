"""Pomodoro timer (FR-01)."""

from __future__ import annotations

import copy

import pytest

from app.logic.pomodoro import Pomodoro
from app.storage.settings import DEFAULTS


def test_work_then_break_then_work() -> None:
    p = Pomodoro(work_min=25, break_min=5, now=0.0)
    t = p.tick(60.0)
    assert t.phase == "work" and t.changed_to is None and t.left_s == pytest.approx(24 * 60)
    t = p.tick(25 * 60)
    assert t.phase == "break" and t.changed_to == "break" and t.left_s == pytest.approx(5 * 60)
    assert p.tick(26 * 60).changed_to is None
    t = p.tick(30 * 60)
    assert t.phase == "work" and t.changed_to == "work"


def test_lengths_from_settings() -> None:
    s = copy.deepcopy(DEFAULTS)
    s["pomodoro"].update(work_min=50, break_min=10)
    p = Pomodoro.from_settings(s, now=100.0)
    assert p.tick(100.0 + 49 * 60).phase == "work"
    assert p.tick(100.0 + 50 * 60).changed_to == "break"
