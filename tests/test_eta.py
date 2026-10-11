"""Tests for the time-to-ready estimator."""
# pylint: disable=missing-class-docstring


import importlib
import sys
import types
from pathlib import Path

import pytest

_PKG_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "fellow"
)
_pkg = types.ModuleType("fellow_pkg")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules.setdefault("fellow_pkg", _pkg)
eta = importlib.import_module("fellow_pkg.eta")

HeatingRateEstimator = eta.HeatingRateEstimator


def feed(est, points):
    for t, temp in points:
        est.add_sample(t, temp)


class TestHeatingRateEstimator:
    def test_steady_heating_projects_linearly(self):
        est = HeatingRateEstimator()
        # 0.1 C/s: 20C at t=0 -> 23C at t=30
        feed(est, [(0, 20.0), (10, 21.0), (20, 22.0), (30, 23.0)])
        # 95 - 23 = 72C remaining at 0.1C/s = 720s = 12 min
        assert est.minutes_to(95.0) == pytest.approx(12.0, abs=0.1)

    def test_needs_minimum_samples(self):
        est = HeatingRateEstimator()
        feed(est, [(0, 20.0), (10, 21.0)])
        assert est.minutes_to(95.0) is None

    def test_unknown_target(self):
        est = HeatingRateEstimator()
        feed(est, [(0, 20.0), (10, 21.0), (20, 22.0)])
        assert est.minutes_to(None) is None

    def test_at_target_is_zero(self):
        est = HeatingRateEstimator()
        feed(est, [(0, 93.0), (10, 94.0), (20, 95.5)])
        assert est.minutes_to(95.0) == 0.0

    def test_flat_temperature_gives_none(self):
        # Holding at temperature: not rising, no ETA.
        est = HeatingRateEstimator()
        feed(est, [(0, 95.0), (10, 95.0), (20, 95.0)])
        assert est.minutes_to(100.0) is None

    def test_old_samples_age_out_of_window(self):
        est = HeatingRateEstimator()
        # Early fast phase, then only recent points should count.
        feed(est, [(0, 20.0), (100, 40.0), (110, 41.0), (120, 42.0), (130, 43.0)])
        # Window is 90s: the t=0 sample is gone; rate from t=100..130 = 0.1C/s
        assert est.minutes_to(53.0) == pytest.approx(
            (53.0 - 43.0) / 0.1 / 60.0, abs=0.1
        )

    def test_cold_refill_resets(self):
        est = HeatingRateEstimator()
        feed(est, [(0, 90.0), (10, 91.0), (20, 92.0)])
        # Fresh cold water poured in.
        est.add_sample(30, 25.0)
        assert est.minutes_to(95.0) is None  # only 1 valid sample now
        feed(est, [(40, 26.0), (50, 27.0)])
        # New curve: 0.1C/s from 25C
        assert est.minutes_to(95.0) == pytest.approx(
            (95.0 - 27.0) / 0.1 / 60.0, abs=0.5
        )

    def test_reset_clears(self):
        est = HeatingRateEstimator()
        feed(est, [(0, 20.0), (10, 21.0), (20, 22.0)])
        est.reset()
        assert est.minutes_to(95.0) is None
