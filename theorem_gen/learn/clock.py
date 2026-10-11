"""Injectable clock so checkpoints and leases do not depend on wall time in tests."""

from __future__ import annotations

import time


class Clock:
    def time(self) -> float:
        return time.time()


class ManualClock:
    def __init__(self, start: float = 1000.0) -> None:
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            raise ValueError("start must be a number")
        self._time = float(start)

    def time(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("seconds must be a number")
        if seconds < 0:
            raise ValueError("seconds must be >= 0")
        self._time += float(seconds)
