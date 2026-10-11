"""32-bit LCG so a seed does not depend on CPython's random module."""

from __future__ import annotations


class LCG:
    """Numerical Recipes LCG: state = (1664525 * state + 1013904223) mod 2**32."""

    MODULUS = 2**32
    MULTIPLIER = 1664525
    INCREMENT = 1013904223

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an int")
        self._state = seed % self.MODULUS

    def get_state(self) -> int:
        return self._state

    def set_state(self, state: int) -> None:
        if isinstance(state, bool) or not isinstance(state, int):
            raise ValueError("state must be an int")
        self._state = state % self.MODULUS

    def next_u32(self) -> int:
        self._state = (self.MULTIPLIER * self._state + self.INCREMENT) % self.MODULUS
        return self._state

    def randint(self, low: int, high: int) -> int:
        if low > high:
            raise ValueError("low must be <= high")
        span = high - low + 1
        return low + (self.next_u32() % span)

    def random(self) -> float:
        return self.next_u32() / 4294967295
