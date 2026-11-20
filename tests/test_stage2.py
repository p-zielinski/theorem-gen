import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.config import GeneratorConfig
from theorem_gen.errors import GenerationError
from theorem_gen.export_lean import export_module, export_theorem
from theorem_gen.general import GENERAL_RULES, config_for_export, generate_general
from theorem_gen.generate import generate
from theorem_gen.theorem import claimed_true


class GeneralGenerationTests(unittest.TestCase):
    def test_universal_equality_is_exported_as_a_lemma_application(self):
        theorem = self.one("add_zero_all")
        self.assertEqual(theorem.metadata.kind, "universal")
        self.assertEqual(theorem.metadata.verification, "unverified")
        self.assertFalse(claimed_true(theorem))
        self.assertEqual(
            export_theorem(theorem),
            "theorem gen_s1_0000 (a : Nat) : ((a + 0) = a) := Nat.add_zero a",
        )

    def test_binary_universal_keeps_both_binders(self):
        theorem = self.one("add_comm_all")
        self.assertEqual(
            export_theorem(theorem),
            "theorem gen_s1_0000 (a : Nat) (b : Nat) : ((a + b) = (b + a)) := Nat.add_comm a b",
        )

    def test_conditional_uses_the_assumption(self):
        theorem = self.one("eq_implies_add_zero")
        self.assertEqual(theorem.metadata.kind, "conditional")
        self.assertFalse(claimed_true(theorem))
        self.assertEqual(
            export_theorem(theorem),
            "\n".join(
                (
                    "theorem gen_s1_0000 (a : Nat) (b : Nat) (h : (a = b)) : ((a + 0) = b) := by",
                    "  rw [Nat.add_zero]",
                    "  exact h",
                )
            ),
        )

    def test_open_expression_has_no_proof_and_is_not_claimed(self):
        theorem = self.one("open_double_eq")
        self.assertEqual(theorem.metadata.kind, "expression")
        self.assertIsNone(theorem.proof)
        self.assertEqual(theorem.metadata.verification, "unverified")
        self.assertFalse(claimed_true(theorem))
        text = export_theorem(theorem)
        self.assertIn("#check (forall (a : Nat), ((a + a) = a))", text)
        self.assertIn("not claimed true", text)
        self.assertNotIn(":=", text)
        self.assertNotIn("sorry", text)

    def test_header_records_the_general_rules_that_were_used(self):
        bare = GeneratorConfig(seed=1, count=1)
        source = export_module(generate_general(bare), config_for_export(bare))
        self.assertIn(
            "-- theorem-gen rules: " + ",".join(GENERAL_RULES),
            source,
        )
        self.assertNotIn("eval_eq", source)
        self.assertIn("Typed definitions, theorems, and checked expressions.", source)

    def test_same_seed_repeats(self):
        config = GeneratorConfig(seed=2, count=4)
        self.assertEqual(
            generate_general(config),
            generate_general(config),
        )

    def test_a_later_copy_shifts_the_term_and_the_lemma(self):
        config = GeneratorConfig(seed=1, count=2, rules=("add_zero_all",))
        first, second = generate_general(config)
        self.assertNotEqual(first.statement, second.statement)
        self.assertEqual(
            export_theorem(second),
            "theorem gen_s1_0001 (a : Nat) : (((a + 2) + 0) = (a + 2)) := Nat.add_zero (a + 2)",
        )
        many = generate_general(GeneratorConfig(seed=1, count=30, rules=("add_zero_all",)))
        self.assertEqual(len({item.statement for item in many}), 30)

    def test_an_unshifted_rule_cannot_fill_a_second_statement(self):
        config = GeneratorConfig(seed=1, count=2, rules=("open_double_eq",))
        with self.assertRaises(GenerationError) as caught:
            generate_general(config)
        self.assertIn("produced 1", str(caught.exception))
        self.assertIn("not a mathematical verdict", str(caught.exception))

    def test_concrete_rule_is_rejected_by_the_general_generator(self):
        config = GeneratorConfig(seed=1, count=1, rules=("add_zero",))
        with self.assertRaises(GenerationError) as caught:
            generate_general(config)
        self.assertIn("not a general rule", str(caught.exception))

    def test_general_rule_is_rejected_by_the_concrete_generator(self):
        config = GeneratorConfig(seed=1, count=1, rules=("add_zero_all",))
        with self.assertRaises(GenerationError) as caught:
            generate(config)
        self.assertIn("not a concrete rule", str(caught.exception))

    def test_four_kinds_stay_distinct(self):
        kinds = {
            self.one("add_zero_all").metadata.kind,
            self.one("eq_implies_add_zero").metadata.kind,
            self.one("open_double_eq").metadata.kind,
        }
        self.assertEqual(kinds, {"universal", "conditional", "expression"})
        concrete = generate(GeneratorConfig(seed=1, count=1, rules=("add_zero",)))
        self.assertEqual(concrete[0].metadata.kind, "concrete")

    def one(self, rule):
        config = GeneratorConfig(seed=1, count=1, rules=(rule,))
        return generate_general(config)[0]


if __name__ == "__main__":
    unittest.main()
