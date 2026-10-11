import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.expr import (
    BinOp,
    Compare,
    ExprError,
    NatLit,
    TypingError,
    evaluate,
    holds,
    infer,
    structural_key,
)


class ExprTests(unittest.TestCase):
    def test_literal_and_operations_have_nat_type(self):
        expr = BinOp("mul", BinOp("add", NatLit(2), NatLit(3)), NatLit(4))
        self.assertEqual(infer(NatLit(0)), "Nat")
        self.assertEqual(infer(expr), "Nat")
        self.assertEqual(evaluate(expr), 20)

    def test_comparison_is_a_proposition(self):
        prop = Compare("eq", BinOp("add", NatLit(2), NatLit(3)), NatLit(5))
        self.assertEqual(infer(prop), "Prop")
        self.assertTrue(holds(prop))
        self.assertFalse(holds(Compare("eq", NatLit(1), NatLit(0))))
        self.assertTrue(holds(Compare("le", NatLit(2), NatLit(2))))
        self.assertFalse(holds(Compare("lt", NatLit(2), NatLit(2))))
        self.assertTrue(holds(Compare("lt", NatLit(2), NatLit(3))))

    def test_concrete_identities_follow_nat_arithmetic(self):
        samples = (
            BinOp("add", NatLit(0), NatLit(5)),
            BinOp("add", NatLit(5), NatLit(0)),
            BinOp("mul", NatLit(5), NatLit(0)),
            BinOp("mul", NatLit(0), NatLit(5)),
            BinOp("mul", NatLit(5), NatLit(1)),
            BinOp("mul", NatLit(1), NatLit(5)),
        )
        self.assertEqual([evaluate(expr) for expr in samples], [5, 5, 0, 0, 5, 5])

    def test_structural_key_keeps_operator_and_shape(self):
        prop = Compare("eq", BinOp("add", NatLit(2), NatLit(3)), NatLit(5))
        self.assertEqual(
            structural_key(prop),
            ("eq", ("add", ("lit", 2), ("lit", 3)), ("lit", 5)),
        )
        self.assertNotEqual(
            structural_key(Compare("eq", NatLit(0), NatLit(0))),
            structural_key(Compare("le", NatLit(0), NatLit(0))),
        )

    def test_negative_bool_and_non_int_literals_are_rejected(self):
        with self.assertRaises(ExprError):
            NatLit(-1)
        with self.assertRaises(ExprError):
            NatLit(True)
        with self.assertRaises(ExprError):
            NatLit(1.5)

    def test_proposition_cannot_be_an_operand(self):
        prop = Compare("eq", NatLit(1), NatLit(1))
        with self.assertRaises(TypingError):
            BinOp("add", prop, NatLit(1))

    def test_unknown_operators_are_rejected(self):
        with self.assertRaises(TypingError):
            BinOp("div", NatLit(1), NatLit(1))
        with self.assertRaises(TypingError):
            Compare("plus", NatLit(1), NatLit(1))

    def test_non_expression_child_is_rejected(self):
        with self.assertRaises(TypingError):
            BinOp("add", NatLit(1), "x")

    def test_evaluate_rejects_a_proposition(self):
        prop = Compare("eq", NatLit(1), NatLit(1))
        with self.assertRaises(TypingError):
            evaluate(prop)


if __name__ == "__main__":
    unittest.main()
