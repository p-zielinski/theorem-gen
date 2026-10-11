import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.config import DEFAULT_RULES, GeneratorConfig
from theorem_gen.errors import GenerationError
from theorem_gen.expr import BinOp, NatLit, evaluate, holds, structural_key
from theorem_gen.export_lean import export_module, export_prop, export_theorem
from theorem_gen.generate import generate


def depth(expr):
    if isinstance(expr, NatLit):
        return 0
    if isinstance(expr, BinOp):
        return 1 + max(depth(expr.left), depth(expr.right))
    raise AssertionError("unexpected expression")


class GenerateTests(unittest.TestCase):
    def test_add_zero_seed_is_a_fixed_sequence(self):
        theorems = generate(GeneratorConfig(seed=1, count=2, max_literal=9, rules=("add_zero",)))
        self.assertEqual(export_prop(theorems[0].statement), "((8 + 0) = 8)")
        self.assertEqual(export_prop(theorems[1].statement), "((7 + 0) = 7)")
        self.assertEqual(theorems[0].metadata.identifier, "gen_s1_0000")
        self.assertEqual(theorems[1].metadata.identifier, "gen_s1_0001")
        self.assertEqual(theorems[0].metadata.rules, ("add_zero",))
        self.assertEqual(theorems[0].metadata.kind, "concrete")
        self.assertEqual(theorems[0].metadata.verification, "unverified")
        self.assertEqual(theorems[0].proof.method, "rfl")

    def test_same_config_repeats_and_longer_run_extends_it(self):
        short = GeneratorConfig(seed=1, count=2, rules=("add_zero",))
        longer = GeneratorConfig(seed=1, count=4, rules=("add_zero",))
        self.assertEqual(generate(short), generate(short))
        self.assertEqual(generate(short), generate(longer)[:2])

    def test_seed_changes_the_statement(self):
        first = generate(GeneratorConfig(seed=1, count=1, rules=("add_zero",)))
        second = generate(GeneratorConfig(seed=2, count=1, rules=("add_zero",)))
        self.assertEqual(export_prop(second[0].statement), "((3 + 0) = 3)")
        self.assertNotEqual(first[0].statement, second[0].statement)

    def test_negative_seed_has_a_lean_name(self):
        theorems = generate(
            GeneratorConfig(seed=-3, count=1, max_literal=0, rules=("le_refl",))
        )
        self.assertEqual(theorems[0].metadata.identifier, "gen_sneg3_0000")
        self.assertTrue(export_theorem(theorems[0]).startswith("theorem gen_sneg3_0000 "))
        self.assertTrue(holds(theorems[0].statement))

    def test_zero_count_is_empty(self):
        self.assertEqual(generate(GeneratorConfig(seed=1, count=0)), [])

    def test_unique_statements_and_explicit_duplicates(self):
        unique = generate(GeneratorConfig(seed=1, count=4, max_literal=3, max_depth=0, rules=("eval_eq",)))
        keys = [structural_key(theorem.statement) for theorem in unique]
        self.assertEqual(len(keys), len(set(keys)))
        values = {theorem.statement.left.value for theorem in unique}
        self.assertEqual(values, {0, 1, 2, 3})

        duplicated = generate(
            GeneratorConfig(
                seed=1,
                count=3,
                max_literal=0,
                rules=("le_refl",),
                unique=False,
            )
        )
        self.assertEqual(
            [export_prop(theorem.statement) for theorem in duplicated],
            ["(0 <= 0)", "(0 <= 0)", "(0 <= 0)"],
        )
        self.assertEqual(
            [theorem.metadata.identifier for theorem in duplicated],
            ["gen_s1_0000", "gen_s1_0001", "gen_s1_0002"],
        )

    def test_unique_exhaustion_is_a_generation_limit(self):
        with self.assertRaises(GenerationError) as caught:
            generate(
                GeneratorConfig(
                    seed=1,
                    count=2,
                    max_literal=0,
                    rules=("le_refl",),
                    unique=True,
                )
            )
        message = str(caught.exception)
        self.assertIn("unique", message)
        self.assertIn("requested 2", message)
        self.assertIn("produced 1", message)

    def test_impossible_rule_does_not_invent_a_theorem(self):
        for rules in (("lt_between",), ("one_mul",), ("mul_one",)):
            with self.subTest(rules=rules):
                with self.assertRaises(GenerationError) as caught:
                    generate(
                        GeneratorConfig(seed=0, count=1, max_literal=0, rules=rules)
                    )
                self.assertIn("produced 0", str(caught.exception))

    def test_max_value_filters_large_literals(self):
        theorems = generate(
            GeneratorConfig(
                seed=1,
                count=1,
                max_literal=9,
                max_value=0,
                rules=("add_zero",),
            )
        )
        self.assertEqual(export_prop(theorems[0].statement), "((0 + 0) = 0)")

    def test_max_attempts_zero_stops_immediately(self):
        with self.assertRaises(GenerationError) as caught:
            generate(GeneratorConfig(seed=1, count=1, max_attempts=0, rules=("add_zero",)))
        self.assertIn("produced 0", str(caught.exception))

    def test_invalid_config_names_the_problem(self):
        with self.assertRaises(GenerationError):
            GeneratorConfig(seed=True, count=1)
        with self.assertRaises(GenerationError):
            GeneratorConfig(seed=1, count=-1)
        with self.assertRaises(GenerationError):
            GeneratorConfig(seed=1, count=1, max_literal=-1)
        with self.assertRaises(GenerationError) as caught:
            GeneratorConfig(seed=1, count=1, rules=("nope",))
        self.assertIn("nope", str(caught.exception))
        with self.assertRaises(GenerationError):
            generate(GeneratorConfig(seed=1, count=1, rules=()))

    def test_each_default_rule_yields_a_true_concrete_theorem(self):
        self.assertEqual(
            set(DEFAULT_RULES),
            {
                "eval_eq",
                "add_zero",
                "zero_add",
                "mul_one",
                "one_mul",
                "mul_zero",
                "zero_mul",
                "add_comm",
                "mul_comm",
                "le_between",
                "lt_between",
                "le_refl",
            },
        )
        for rule in DEFAULT_RULES:
            with self.subTest(rule=rule):
                theorems = generate(
                    GeneratorConfig(seed=5, count=1, max_literal=6, rules=(rule,))
                )
                theorem = theorems[0]
                self.assertTrue(holds(theorem.statement))
                self.assertEqual(theorem.metadata.rules, (rule,))
                self.assertEqual(theorem.metadata.kind, "concrete")
                if theorem.statement.op == "eq":
                    self.assertEqual(theorem.proof.method, "rfl")
                else:
                    self.assertEqual(theorem.proof.method, "decide")

    def test_commutative_rules_swap_operands(self):
        for rule, operator in (("add_comm", "add"), ("mul_comm", "mul")):
            with self.subTest(rule=rule):
                theorem = generate(GeneratorConfig(seed=2, count=1, rules=(rule,)))[0]
                left = theorem.statement.left
                right = theorem.statement.right
                self.assertEqual(left.op, operator)
                self.assertEqual(right.op, operator)
                self.assertEqual(left.left, right.right)
                self.assertEqual(left.right, right.left)
                self.assertTrue(holds(theorem.statement))

    def test_add_zero_and_zero_add_keep_their_shape(self):
        added = generate(GeneratorConfig(seed=4, count=1, rules=("add_zero",)))[0]
        self.assertEqual(added.statement.left.right, NatLit(0))
        self.assertEqual(added.statement.right, added.statement.left.left)
        zero_first = generate(GeneratorConfig(seed=4, count=1, rules=("zero_add",)))[0]
        self.assertEqual(zero_first.statement.left.left, NatLit(0))
        self.assertEqual(zero_first.statement.right, zero_first.statement.left.right)

    def test_eval_eq_respects_depth_and_records_the_value(self):
        shallow = generate(
            GeneratorConfig(
                seed=4,
                count=15,
                max_depth=1,
                rules=("eval_eq",),
                unique=False,
            )
        )
        for theorem in shallow:
            self.assertLessEqual(depth(theorem.statement.left), 1)
            self.assertIsInstance(theorem.statement.right, NatLit)
            self.assertEqual(theorem.statement.right.value, evaluate(theorem.statement.left))

    def test_many_seeds_stay_true_unique_and_free_of_sorry(self):
        for seed in range(8):
            config = GeneratorConfig(seed=seed, count=6)
            theorems = generate(config)
            keys = [structural_key(theorem.statement) for theorem in theorems]
            self.assertEqual(len(keys), len(set(keys)))
            module = export_module(theorems, config)
            self.assertNotIn("sorry", module)
            self.assertNotIn("#eval", module)
            for theorem in theorems:
                self.assertTrue(holds(theorem.statement))
                self.assertEqual(theorem.metadata.verification, "unverified")
                self.assertNotIn("sorry", export_theorem(theorem))


if __name__ == "__main__":
    unittest.main()
