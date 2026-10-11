import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.complexity import measure_expr, measure_theorem
from theorem_gen.config import GeneratorConfig
from theorem_gen.definitions import (
    double_definition,
    register_definition,
    supporting_definitions,
    theorem_about_double,
)
from theorem_gen.errors import GenerationError
from theorem_gen.expr import Compare, Forall, NatLit, Var
from theorem_gen.export_lean import export_module, export_prop
from theorem_gen.general import generate_general
from theorem_gen.generate import generate


class ComplexityTests(unittest.TestCase):
    def test_literal_magnitude_is_not_a_measure(self):
        small = measure_expr(NatLit(1))
        huge = measure_expr(NatLit(10**12))
        self.assertEqual(small["ast_size"], huge["ast_size"])
        self.assertEqual(small["depth"], huge["depth"])
        self.assertNotIn("value", huge)
        richer = measure_expr(Forall((Var("a", "Nat"),), Compare("eq", Var("a", "Nat"), Var("a", "Nat"))))
        self.assertGreater(richer["ast_size"], huge["ast_size"])
        self.assertGreater(richer["variables"], huge["variables"])

    def test_generation_can_stay_inside_bounds(self):
        config = GeneratorConfig(
            seed=1,
            count=2,
            max_literal=9,
            rules=("add_zero",),
            complexity_bounds={"ast_size": (5, 5), "variables": (0, 0)},
        )
        theorems = generate(config)
        self.assertEqual(export_prop(theorems[0].statement), "((8 + 0) = 8)")
        self.assertEqual(export_prop(theorems[1].statement), "((7 + 0) = 7)")
        source = export_module(theorems, config)
        self.assertIn("-- theorem-gen complexity: ast_size:5-5,variables:0-0", source)
        self.assertIn("Concrete Nat theorems only.", source)

    def test_impossible_bounds_are_a_generation_limit(self):
        config = GeneratorConfig(
            seed=1,
            count=1,
            rules=("add_zero",),
            complexity_bounds={"ast_size": (1, 2)},
        )
        with self.assertRaises(GenerationError) as caught:
            generate(config)
        self.assertIn("produced 0", str(caught.exception))
        self.assertIn("not a mathematical verdict", str(caught.exception))

    def test_variable_bound_rejects_closed_arithmetic(self):
        config = GeneratorConfig(
            seed=1,
            count=1,
            rules=("add_zero",),
            complexity_bounds={"variables": (1, 3)},
        )
        with self.assertRaises(GenerationError) as caught:
            generate(config)
        self.assertIn("produced 0", str(caught.exception))

    def test_inverted_bounds_are_rejected_by_config(self):
        with self.assertRaises(GenerationError) as caught:
            GeneratorConfig(seed=1, count=1, complexity_bounds={"depth": (3, 1)})
        self.assertIn("low must be <= high", str(caught.exception))

    def test_depth_and_operator_bounds_select_a_shape(self):
        matched = GeneratorConfig(
            seed=1,
            count=1,
            rules=("add_zero",),
            complexity_bounds={"depth": (2, 2), "operators": (1, 1)},
        )
        theorem = generate(matched)[0]
        self.assertEqual(export_prop(theorem.statement), "((8 + 0) = 8)")
        shallow = GeneratorConfig(
            seed=1,
            count=2,
            rules=("le_refl",),
            complexity_bounds={"depth": (1, 1), "operators": (0, 0)},
        )
        generated = generate(shallow)
        self.assertEqual(export_prop(generated[0].statement), "(8 <= 8)")
        self.assertTrue(all(measure_expr(item.statement)["operators"] == 0 for item in generated))
        with self.assertRaises(GenerationError) as caught:
            generate(
                GeneratorConfig(
                    seed=1,
                    count=1,
                    rules=("add_zero",),
                    complexity_bounds={"operators": (3, 4)},
                )
            )
        self.assertIn("produced 0", str(caught.exception))

    def test_variable_bounds_select_a_quantified_statement(self):
        one = GeneratorConfig(
            seed=1,
            count=1,
            rules=("add_zero_all",),
            complexity_bounds={"variables": (1, 1)},
        )
        two = GeneratorConfig(
            seed=1,
            count=1,
            rules=("add_comm_all",),
            complexity_bounds={"variables": (2, 2)},
        )
        self.assertEqual(measure_theorem(generate_general(one)[0])["variables"], 1)
        self.assertEqual(measure_theorem(generate_general(two)[0])["variables"], 2)
        with self.assertRaises(GenerationError) as caught:
            generate_general(
                GeneratorConfig(
                    seed=1,
                    count=1,
                    rules=("add_zero_all",),
                    complexity_bounds={"variables": (4, 5)},
                )
            )
        self.assertIn("produced 0", str(caught.exception))

    def test_definition_and_dependency_bounds_select_the_library_theorem(self):
        config = GeneratorConfig(
            seed=1,
            count=1,
            rules=("use_definition",),
            complexity_bounds={"dependencies": (1, 1), "definitions": (1, 1)},
        )
        theorem = generate(config)[0]
        measured = measure_theorem(theorem)
        self.assertEqual(measured["dependencies"], 1)
        self.assertEqual(measured["definitions"], 1)
        self.assertEqual(theorem.metadata.dependencies, ("def_double",))
        self.assertFalse(theorem.metadata.discovered)
        self.assertEqual(supporting_definitions((theorem,))[0].name, "double")
        with self.assertRaises(GenerationError):
            generate(
                GeneratorConfig(
                    seed=1,
                    count=1,
                    rules=("add_zero",),
                    complexity_bounds={"dependencies": (1, 2)},
                )
            )

    def test_definition_dependency_is_counted_from_the_registry(self):
        definition = double_definition()
        theorem = theorem_about_double(definition)
        registry = register_definition(definition, theorem)
        measured = measure_theorem(theorem, registry)
        self.assertEqual(measured["dependencies"], 1)
        self.assertEqual(measured["definitions"], 1)


if __name__ == "__main__":
    unittest.main()
