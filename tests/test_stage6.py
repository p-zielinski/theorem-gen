import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.config import GeneratorConfig
from theorem_gen.definitions import (
    Definition,
    double_definition,
    register_definition,
    theorem_about_double,
    validate_definition,
)
from theorem_gen.errors import DefinitionError
from theorem_gen.expr import BinOp, Const, NatLit, Var
from theorem_gen.export_lean import export_library


class DefinitionTests(unittest.TestCase):
    def test_double_is_exported_with_a_dependent_theorem(self):
        definition = double_definition()
        validate_definition(definition)
        theorem = theorem_about_double(definition)
        registry = register_definition(definition, theorem)
        self.assertEqual(registry.dependencies("gen_double_zero"), ("def_double",))
        self.assertFalse(registry.get("gen_double_zero").discovered)
        source = export_library(
            (definition,),
            (theorem,),
            GeneratorConfig(seed=1, count=1, rules=("le_refl",)),
        )
        self.assertIn("def double (n : Nat) : Nat := (n + n)", source)
        self.assertIn("theorem gen_double_zero : ((double 0) = 0) := rfl", source)
        self.assertNotIn("sorry", source)

    def test_free_variable_type_mismatch_and_recursion_are_rejected(self):
        param = Var("n", "Nat")
        with self.assertRaises(DefinitionError) as caught:
            validate_definition(
                Definition(
                    "def_bad",
                    "bad",
                    (param,),
                    BinOp("add", param, Var("m", "Nat")),
                    "Nat",
                )
            )
        self.assertIn("free variable m", str(caught.exception))
        with self.assertRaises(DefinitionError) as caught:
            validate_definition(
                Definition("def_bad", "bad", (param,), NatLit(1), "Int")
            )
        self.assertIn("body has type Nat", str(caught.exception))
        with self.assertRaises(DefinitionError) as caught:
            validate_definition(
                Definition(
                    "def_bad",
                    "double",
                    (param,),
                    Const("double", "Nat", (param,)),
                    "Nat",
                )
            )
        self.assertIn("recursive", str(caught.exception))
        with self.assertRaises(DefinitionError) as caught:
            validate_definition(
                Definition(
                    "def_bad",
                    "bad",
                    (param, param),
                    BinOp("add", param, param),
                    "Nat",
                )
            )
        self.assertIn("duplicate parameter", str(caught.exception))
        with self.assertRaises(DefinitionError) as caught:
            validate_definition(
                Definition("def_bad", "bad", (NatLit(0),), NatLit(0), "Nat")
            )
        self.assertIn("parameters must be variables", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
