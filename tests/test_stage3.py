import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.config import GeneratorConfig
from theorem_gen.errors import TypingError
from theorem_gen.expr import (
    Atom,
    BinOp,
    Compare,
    Const,
    Forall,
    Implies,
    IntLit,
    NatLit,
    UnaryOp,
    Var,
    evaluate,
)
from theorem_gen.export_lean import export_expr, export_module, export_prop
from theorem_gen.theorem import Metadata, Proof, Theorem


class WiderAstTests(unittest.TestCase):
    def test_succ_evaluates_and_exports_without_rewriting(self):
        expr = UnaryOp("succ", NatLit(2))
        self.assertEqual(evaluate(expr), 3)
        self.assertEqual(export_expr(expr), "(Nat.succ 2)")
        theorem = Theorem(
            Compare("eq", expr, NatLit(3)),
            Proof("rfl"),
            Metadata("gen_succ", "concrete", ("succ_concrete",), "unverified"),
        )
        source = export_module((theorem,), GeneratorConfig(seed=1, count=1, rules=("eval_eq",)))
        self.assertIn("theorem gen_succ : ((Nat.succ 2) = 3) := rfl", source)

    def test_int_negation_keeps_its_sign(self):
        statement = Compare(
            "eq",
            BinOp("add", IntLit(1), IntLit(-1)),
            IntLit(0),
        )
        theorem = Theorem(
            statement,
            Proof("decide"),
            Metadata("gen_int", "concrete", ("int_neg_add",), "unverified"),
        )
        source = export_module((theorem,), GeneratorConfig(seed=1, count=1, rules=("eval_eq",)))
        self.assertIn(
            "theorem gen_int : (((1 : Int) + (-1 : Int)) = (0 : Int)) := by\n  decide",
            source,
        )

    def test_nat_plus_int_is_rejected(self):
        with self.assertRaises(TypingError) as caught:
            BinOp("add", NatLit(1), IntLit(1))
        self.assertIn("cannot apply add to Nat and Int", str(caught.exception))

    def test_negation_of_nat_is_rejected(self):
        with self.assertRaises(TypingError) as caught:
            UnaryOp("neg", NatLit(1))
        self.assertIn("neg expects Int", str(caught.exception))

    def test_succ_of_int_is_rejected(self):
        with self.assertRaises(TypingError) as caught:
            UnaryOp("succ", IntLit(1))
        self.assertIn("succ expects Nat", str(caught.exception))

    def test_pred_is_rejected_instead_of_changing_zero(self):
        with self.assertRaises(TypingError) as caught:
            UnaryOp("pred", NatLit(0))
        self.assertIn("pred", str(caught.exception))
        self.assertIn("0", str(caught.exception))

    def test_negation_exports_the_operator(self):
        expr = UnaryOp("neg", IntLit(1))
        self.assertEqual(export_expr(expr), "(-(1 : Int))")
        theorem = Theorem(
            Compare("eq", expr, IntLit(-1)),
            Proof("rfl"),
            Metadata("gen_neg", "concrete", ("int_neg",), "unverified"),
        )
        source = export_module((theorem,), GeneratorConfig(seed=1, count=1, rules=("eval_eq",)))
        self.assertIn("theorem gen_neg : ((-(1 : Int)) = (-1 : Int)) := rfl", source)

    def test_atom_exports_without_becoming_a_proof(self):
        variable = Var("a", "Nat")
        statement = Forall((variable,), Atom("P", (variable,)))
        self.assertEqual(export_prop(statement.body), "(P a)")
        theorem = Theorem(
            statement,
            None,
            Metadata("gen_atom", "expression", ("atom_p",), "unverified"),
        )
        source = export_module((theorem,), GeneratorConfig(seed=1, count=1, rules=("eval_eq",)))
        self.assertIn("#check (forall (a : Nat), (P a))", source)
        self.assertNotIn(":=", source.split("#check", 1)[1])

    def test_implication_and_const_reject_a_change_of_meaning(self):
        with self.assertRaises(TypingError) as caught:
            Implies(NatLit(1), Compare("eq", NatLit(1), NatLit(1)))
        self.assertIn("proposition", str(caught.exception))
        with self.assertRaises(TypingError):
            Var("a", "Bool")
        with self.assertRaises(TypingError):
            Const("flag", "Bool", ())
        with self.assertRaises(TypingError) as caught:
            Const("double", "Nat", (IntLit(1),))
        self.assertIn("cannot apply double to Int", str(caught.exception))
        with self.assertRaises(TypingError) as caught:
            Atom("P", (Compare("eq", NatLit(0), NatLit(0)),))
        self.assertIn("expects an expression", str(caught.exception))

    def test_unbound_and_duplicate_binders_are_rejected(self):
        with self.assertRaises(TypingError) as caught:
            Forall((Var("a", "Nat"),), Compare("eq", Var("b", "Nat"), NatLit(0)))
        self.assertIn("unbound variable b", str(caught.exception))
        with self.assertRaises(TypingError) as caught:
            Forall(
                (Var("a", "Nat"), Var("a", "Nat")),
                Compare("eq", Var("a", "Nat"), Var("a", "Nat")),
            )
        self.assertIn("duplicate binder a", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
