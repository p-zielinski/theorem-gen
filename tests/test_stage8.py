import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.errors import GenerationError
from theorem_gen.explore import explore, exploration_registry, theorem_from_proved
from theorem_gen.export_lean import export_theorem
from theorem_gen.theorem import claimed_true


class ExplorationTests(unittest.TestCase):
    def test_one_seed_covers_four_different_outcomes(self):
        results = explore(1, 4)
        self.assertEqual(results, explore(1, 4))
        self.assertEqual(
            {item.status for item in results},
            {"proved", "refuted", "no_proof", "unprovable_in_fragment"},
        )
        orders = {
            tuple(item.status for item in explore(seed, 4))
            for seed in range(6)
        }
        self.assertGreater(len(orders), 1)

    def test_outcomes_are_not_collapsed(self):
        by_status = {item.status: item for item in explore(1, 4)}
        proved = by_status["proved"]
        self.assertEqual(proved.dependencies, ("lemma_Nat_add_zero",))
        self.assertFalse(proved.discovered)
        self.assertEqual(proved.witness, ())
        self.assertIn("Nat.add_zero", proved.reason)
        refuted = by_status["refuted"]
        self.assertEqual(refuted.witness, (("a", 0),))
        self.assertIn("counterexample", refuted.reason)
        undecided = by_status["no_proof"]
        self.assertEqual(undecided.witness, ())
        self.assertIn("undecided", undecided.reason)
        self.assertNotIn("false", undecided.reason.lower())
        fragment = by_status["unprovable_in_fragment"]
        self.assertIn("registered fragment", fragment.reason)
        self.assertNotEqual(fragment.status, "refuted")

    def test_citation_is_recorded_separately_from_discovery(self):
        results = explore(1, 4)
        registry = exploration_registry(results)
        proved = next(item for item in results if item.status == "proved")
        record = registry.get(proved.identifier)
        self.assertFalse(record.discovered)
        self.assertEqual(record.rules, ("cite",))
        self.assertEqual(record.dependencies, ("lemma_Nat_add_zero",))
        self.assertTrue(registry.get("lemma_Nat_add_zero").discovered)
        self.assertEqual(registry.cycles(), ())

    def test_proved_result_exports_a_citation_that_is_still_unverified(self):
        proved = next(item for item in explore(1, 4) if item.status == "proved")
        theorem = theorem_from_proved(proved)
        self.assertFalse(claimed_true(theorem))
        self.assertEqual(theorem.metadata.verification, "unverified")
        self.assertIn(":= Nat.add_zero a", export_theorem(theorem))
        with self.assertRaises(GenerationError):
            theorem_from_proved(next(item for item in explore(1, 4) if item.status == "no_proof"))

    def test_a_tighter_bound_does_not_turn_no_proof_into_a_refutation(self):
        wide = {item.status: item for item in explore(1, 4, instantiation_bound=3)}
        tight = {item.status: item for item in explore(1, 4, instantiation_bound=0)}
        self.assertEqual(tight["no_proof"].status, "no_proof")
        self.assertEqual(tight["no_proof"].witness, ())
        self.assertEqual(tight["refuted"].witness, wide["refuted"].witness)
        self.assertEqual(tight["unprovable_in_fragment"].status, "unprovable_in_fragment")

    def test_empty_and_invalid_counts(self):
        self.assertEqual(explore(1, 0), [])
        with self.assertRaises(GenerationError):
            explore(1, -1)


if __name__ == "__main__":
    unittest.main()
