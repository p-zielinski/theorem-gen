"""Errors for the continuous loop. They are not mathematical verdicts."""

from __future__ import annotations


class LearnError(Exception):
    """The loop stopped because of its own bookkeeping, not because a statement is false."""


class CapabilityError(LearnError):
    """The current curriculum level does not include this operation."""


class Backpressure(LearnError):
    """A bounded queue is at its high-water mark."""


class Crash(LearnError):
    """Injected process death. The in-flight transaction is rolled back."""

    def __init__(self, point: str) -> None:
        super().__init__(point)
        self.point = point
