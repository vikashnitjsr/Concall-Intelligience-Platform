"""Unit tests for the guidance reconciler and scoring.

Run with:  pytest -q   (uses an in-memory SQLite database)
"""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["LLM_PROVIDER"] = "stub"
os.environ["EXTRACTION_PROVIDER"] = "stub"

from app.services.guidance import _classify  # noqa: E402
from app.schemas import decision_band  # noqa: E402


def test_classify_met_when_target_beaten():
    status, variance = _classify(target=100.0, actual=110.0, direction="up")
    assert status == "MET"
    assert variance == 10.0


def test_classify_partial_within_ten_percent():
    status, _ = _classify(target=100.0, actual=93.0, direction="up")
    assert status == "PARTIAL"


def test_classify_missed_when_far_short():
    status, _ = _classify(target=100.0, actual=70.0, direction="up")
    assert status == "MISSED"


def test_classify_in_progress_without_actual():
    status, variance = _classify(target=100.0, actual=None, direction="up")
    assert status == "IN_PROGRESS"
    assert variance is None


def test_decision_band_boundaries():
    assert decision_band(90) == "Exceptional"
    assert decision_band(80) == "High quality"
    assert decision_band(70) == "Good"
    assert decision_band(55) == "Average"
    assert decision_band(40) == "Avoid"
