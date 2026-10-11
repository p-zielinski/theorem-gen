import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.config import GeneratorConfig
from theorem_gen.expr import BinOp, Compare, Forall, Implies, IntLit, NatLit, UnaryOp, Var
from theorem_gen.general import generate_general
from theorem_gen.hypothesis import (
    INVALID_SYNTAX,
    INVALID_TYPE,
    PROVED,
    REFUTED,
    UNRESOLVED,
    HypothesisCandidate,
    assess_hypothesis,
    diversity_metrics,
    limit_repetition,
)
from theorem_gen.theorem import claimed_true
from theorem_gen.verify import VerificationReport


def report(status, failure_class=None, message="checked"):
    return VerificationReport(status, 0 if status == "proved" else 1, "", message, message, failure_class)


def closed(op, left, right):
    return Compare(op, NatLit(left), NatLit(right))


def forall_a(body):
    variable = Var("a", "Nat")
    return Forall((variable,), body(variable))


class HypothesisTests(unittest.TestCase):
    def test_counterexample_beats_a_claimed_proof(self):
        candidate = HypothesisCandidate("bad", statement=closed("eq", 1, 0), proof_supplied=True)
        assessment = assess_hypothesis(candidate, verification=report("proved"), search_bound=0)
        self.assertEqual(assessment.status, REFUTED)
        self.assertEqual(assessment.evidence, {})

    def test_universal_falsehood_names_a_witness(self):
        statement = forall_a(lambda variable: Compare("lt", variable, variable))
        assessment = assess_hypothesis(HypothesisCandidate("lt", statement=statement))
        self.assertEqual(assessment.status, REFUTED)
        self.assertEqual(assessment.evidence, {"a": 0})

    def test_failed_search_is_not_falsity(self):
        statement = forall_a(lambda variable: Compare("eq", BinOp("add", variable, variable), variable))
        narrow = assess_hypothesis(
            HypothesisCandidate("open", statement=statement),
            search_bound=0,
        )
        self.assertEqual(narrow.status, UNRESOLVED)
        self.assertIn("not evidence of truth or falsity", narrow.message)
        wide = assess_hypothesis(
            HypothesisCandidate("open", statement=statement),
            search_bound=1,
        )
        self.assertEqual(wide.status, REFUTED)
        self.assertEqual(wide.evidence, {"a": 1})

    def test_accepted_proof_is_proved_only_when_a_proof_was_supplied(self):
        statement = closed("eq", 1, 1)
        proved = assess_hypothesis(
            HypothesisCandidate("ok", statement=statement, proof_supplied=True),
            verification=report("proved"),
        )
        self.assertEqual(proved.status, PROVED)
        self.assertEqual(proved.evidence, "Lean")
        missing = assess_hypothesis(
            HypothesisCandidate("ok", statement=statement, proof_supplied=False),
            verification=report("proved"),
        )
        self.assertEqual(missing.status, UNRESOLVED)

    def test_timeout_does_not_decide_a_true_statement(self):
        timeout = VerificationReport(
            "timeout",
            None,
            "",
            "",
            "Lean timed out after 1s. The result is inconclusive; a timeout does not decide the statement.",
            None,
        )
        unresolved = assess_hypothesis(
            HypothesisCandidate("holds", statement=closed("eq", 1, 1), proof_supplied=True),
            verification=timeout,
        )
        self.assertEqual(unresolved.status, UNRESOLVED)
        refuted = assess_hypothesis(
            HypothesisCandidate("bad", statement=closed("eq", 1, 0), proof_supplied=True),
            verification=timeout,
        )
        self.assertEqual(refuted.status, REFUTED)
        self.assertEqual(refuted.evidence, {})

    def test_syntax_and_type_failures_stay_ill_formed(self):
        source = HypothesisCandidate("src", source="theorem bad")
        syntax = assess_hypothesis(source, verification=report("failed", "syntax", "unexpected token"))
        self.assertEqual(syntax.status, INVALID_SYNTAX)
        typed = assess_hypothesis(
            HypothesisCandidate("nat", statement=NatLit(1))
        )
        self.assertEqual(typed.status, INVALID_TYPE)
        unchecked = assess_hypothesis(source)
        self.assertEqual(unchecked.status, UNRESOLVED)
        self.assertIn("not been checked", unchecked.message)
        proof_failure = assess_hypothesis(
            source,
            verification=report("failed", "proof", "unsolved goals"),
        )
        self.assertEqual(proof_failure.status, UNRESOLVED)
        self.assertIn("does not establish falsity", proof_failure.message)

    def test_closed_int_falsehood_is_a_counterexample(self):
        statement = Compare(
            "eq",
            BinOp("add", IntLit(1), UnaryOp("neg", IntLit(1))),
            IntLit(1),
        )
        assessment = assess_hypothesis(HypothesisCandidate("int", statement=statement))
        self.assertEqual(assessment.status, REFUTED)
        self.assertEqual(assessment.evidence, {})
        true_statement = Compare(
            "eq",
            BinOp("add", IntLit(1), UnaryOp("neg", IntLit(1))),
            IntLit(0),
        )
        unresolved = assess_hypothesis(
            HypothesisCandidate("int_true", statement=true_statement)
        )
        self.assertEqual(unresolved.status, UNRESOLVED)

    def test_implication_can_be_refuted(self):
        statement = forall_a(
            lambda variable: Implies(
                Compare("eq", variable, variable),
                Compare("lt", variable, variable),
            )
        )
        assessment = assess_hypothesis(HypothesisCandidate("imp", statement=statement))
        self.assertEqual(assessment.status, REFUTED)
        self.assertEqual(assessment.evidence, {"a": 0})

    def test_generated_expression_is_not_true_until_separately_assessed(self):
        theorem = generate_general(
            GeneratorConfig(seed=1, count=1, rules=("open_double_eq",))
        )[0]
        self.assertFalse(claimed_true(theorem))
        assessment = assess_hypothesis(
            HypothesisCandidate(theorem.metadata.identifier, statement=theorem.statement),
            search_bound=1,
        )
        self.assertEqual(assessment.status, REFUTED)

    def test_repetition_and_diversity(self):
        same = HypothesisCandidate("a", statement=closed("eq", 1, 1))
        other = HypothesisCandidate(
            "b",
            statement=forall_a(lambda variable: Compare("eq", variable, variable)),
        )
        duplicate = HypothesisCandidate("c", statement=closed("eq", 1, 1))
        items = (same, other, duplicate)
        unique = limit_repetition(items)
        self.assertEqual(len(unique), 2)
        metrics = diversity_metrics(items)
        self.assertEqual(metrics["count"], 3)
        self.assertEqual(metrics["unique"], 2)
        self.assertAlmostEqual(metrics["unique_ratio"], 2 / 3)
        self.assertGreater(metrics["shape_entropy"], 0)
        empty = diversity_metrics(())
        self.assertEqual(empty["unique_ratio"], 1.0)
        self.assertEqual(empty["shape_entropy"], 0.0)
        sources = limit_repetition(
            (
                HypothesisCandidate("s", source="same"),
                HypothesisCandidate("t", source="same"),
            )
        )
        self.assertEqual(len(sources), 1)


if __name__ == "__main__":
    unittest.main()
