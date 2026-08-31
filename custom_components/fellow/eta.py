"""Time-to-ready estimation from recent temperature samples.

Pure Python (no Home Assistant imports) so it's unit-testable standalone.
The coordinator feeds one (timestamp, temperature) sample per poll while
the kettle is heating; the estimator fits a heating rate over a sliding
window and projects minutes until the target temperature.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

# Sliding window the rate is computed over. Long enough to smooth poll
# jitter, short enough to track the rate change as water warms.
WINDOW_SECONDS = 90.0
# Fewer samples than this and the slope is noise.
MIN_SAMPLES = 3
# Below this rate (°C/s) the water isn't meaningfully heating — at the
# typical ~0.1°C/s of a 1200W kettle this only filters out flat/falling
# readings, e.g. while holding at temperature.
MIN_RATE_C_PER_S = 0.005
# A drop bigger than this between samples means fresh cold water was
# added (or the kettle was refilled) — old samples no longer apply.
RESET_ON_DROP_C = 2.0


class HeatingRateEstimator:
    """Estimate minutes until the water reaches a target temperature."""

    def __init__(self) -> None:
        self._samples: deque[tuple[float, float]] = deque()

    def reset(self) -> None:
        self._samples.clear()

    def add_sample(self, timestamp: float, temp_c: float) -> None:
        """Record one temperature reading (monotonic seconds, Celsius)."""
        if self._samples and temp_c < self._samples[-1][1] - RESET_ON_DROP_C:
            # Fresh cold water: the old heating curve is meaningless.
            self.reset()
        self._samples.append((timestamp, temp_c))
        cutoff = timestamp - WINDOW_SECONDS
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def minutes_to(self, target_c: Optional[float]) -> Optional[float]:
        """Projected minutes until target, or None when unknowable.

        None when the target is unknown, there aren't enough samples yet,
        or the water isn't rising. 0.0 once the water is at/above target.
        """
        if target_c is None or len(self._samples) < MIN_SAMPLES:
            return None

        first_t, first_temp = self._samples[0]
        last_t, last_temp = self._samples[-1]
        if last_temp >= target_c:
            return 0.0

        elapsed = last_t - first_t
        if elapsed <= 0:
            return None
        rate = (last_temp - first_temp) / elapsed
        if rate < MIN_RATE_C_PER_S:
            return None

        return (target_c - last_temp) / rate / 60.0
