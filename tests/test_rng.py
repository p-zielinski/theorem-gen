import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.rng import LCG


class LcgTests(unittest.TestCase):
    def test_seed_one_matches_numerical_recipes_lcg(self):
        rng = LCG(1)
        self.assertEqual(rng.next_u32(), 1015568748)
        self.assertEqual(rng.next_u32(), 1586005467)

    def test_seed_zero_and_negative_wrap(self):
        self.assertEqual(LCG(0).next_u32(), 1013904223)
        self.assertEqual(LCG(-1).next_u32(), 1012239698)
        self.assertEqual(LCG(1).next_u32(), LCG(1 + 2**32).next_u32())

    def test_randint_is_inclusive_and_stable(self):
        self.assertEqual(
            [LCG(1).randint(0, 9) for _ in range(1)],
            [8],
        )
        first = LCG(1)
        second = LCG(1)
        self.assertEqual(
            [first.randint(0, 9) for _ in range(5)],
            [second.randint(0, 9) for _ in range(5)],
        )
        rng = LCG(1)
        self.assertEqual([rng.randint(0, 9) for _ in range(5)], [8, 7, 8, 5, 2])

    def test_singleton_span_still_consumes_a_draw(self):
        rng = LCG(1)
        self.assertEqual(rng.randint(3, 3), 3)
        self.assertEqual(rng.next_u32(), 1586005467)

    def test_random_uses_full_32_bit_range(self):
        self.assertEqual(LCG(1).random(), 1015568748 / 4294967295)

    def test_bool_seed_is_rejected(self):
        with self.assertRaises(ValueError):
            LCG(True)


if __name__ == "__main__":
    unittest.main()
