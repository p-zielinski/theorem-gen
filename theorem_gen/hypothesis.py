"""Stage 7: hypotheses are assessed separately from proof generation."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from theorem_gen.errors import TypingError
from theorem_gen.expr import (
    BinOp,
    Compare,
    Forall,
    Implies,
    IntLit,
    NatLit,
    UnaryOp,
    arith_type,
    holds,
    infer,
    structural_key,
    substitute,
)

PROVED = "proved"
REFUTED = "refuted"
UNRESOLVED = "unresolved"
INVALID_SYNTAX = "invalid_syntax"
INVALID_TYPE = "invalid_type"


@dataclass(frozen=True)
class HypothesisCandidate:
    identifier: str
    statement: object = None
    source: str = ""
    proof_supplied: bool = False


@dataclass(frozen=True)
class HypothesisAssessment:
    candidate: HypothesisCandidate
    status: str
    evidence: object = None
    message: str = ""


def assess_hypothesis(
    candidate: HypothesisCandidate,
    *,
    verification=None,
    search_bound: int = 5,
) -> HypothesisAssessment:
    if isinstance(search_bound, bool) or not isinstance(search_bound, int) or search_bound < 0:
        raise ValueError("search_bound must be a non-negative int")
    if candidate.statement is None:
        return _source_assessment(candidate, verification)
    try:
        if infer(candidate.statement) != "Prop":
            raise TypingError("hypothesis must have type Prop")
    except (TypingError, TypeError, ValueError) as exc:
        return HypothesisAssessment(
            candidate, INVALID_TYPE, message=f"Ill-typed hypothesis: {exc}"
        )
    counterexample = find_counterexample(candidate.statement, search_bound)
    if counterexample is not None:
        return HypothesisAssessment(
            candidate,
            REFUTED,
            evidence=counterexample,
            message="A concrete counterexample was found.",
        )
    if (
        verification is not None
        and verification.status == "proved"
        and candidate.proof_supplied
    ):
        return HypothesisAssessment(
            candidate,
            PROVED,
            evidence="Lean",
            message="Lean accepted the supplied proof.",
        )
    if verification is not None and verification.failure_class in {"syntax", "typing"}:
        status = (
            INVALID_SYNTAX
            if verification.failure_class == "syntax"
            else INVALID_TYPE
        )
        return HypothesisAssessment(candidate, status, message=verification.message)
    return HypothesisAssessment(
        candidate,
        UNRESOLVED,
        message=(
            "No counterexample was found in the finite search, but no proof was "
            "accepted. This is not evidence of truth or falsity."
        ),
    )


def _source_assessment(candidate, verification):
    if verification is None:
        return HypothesisAssessment(
            candidate, UNRESOLVED, message="Source has not been checked."
        )
    if verification.failure_class == "syntax":
        return HypothesisAssessment(
            candidate, INVALID_SYNTAX, message=verification.message
        )
    if verification.failure_class == "typing":
        return HypothesisAssessment(candidate, INVALID_TYPE, message=verification.message)
    if verification.status == "proved" and candidate.proof_supplied:
        return HypothesisAssessment(candidate, PROVED, evidence="Lean")
    return HypothesisAssessment(
        candidate,
        UNRESOLVED,
        message="Failure to prove source does not establish falsity.",
    )


def find_counterexample(statement: object, search_bound: int) -> object:
    if isinstance(statement, Forall):
        nat_binders = [item for item in statement.binders if item.type_name == "Nat"]
        if len(nat_binders) != len(statement.binders):
            return None
        domain = range(search_bound + 1)
        for values in itertools.product(domain, repeat=len(nat_binders)):
            environment = {
                binder.name: NatLit(value)
                for binder, value in zip(nat_binders, values)
            }
            try:
                instantiated = substitute(statement.body, environment)
                failed = not _closed_truth(instantiated)
            except TypingError:
                return None
            if failed:
                return dict(zip((item.name for item in nat_binders), values))
        return None
    try:
        return {} if not _closed_truth(statement) else None
    except TypingError:
        return None


def _closed_truth(statement: object) -> bool:
    if isinstance(statement, Compare):
        side = arith_type(statement.left)
        if side == "Nat":
            return holds(statement)
        if side == "Int":
            return _int_holds(statement)
        raise TypingError("finite evaluation supports Nat and Int comparisons")
    if isinstance(statement, Implies):
        return (not _closed_truth(statement.premise)) or _closed_truth(
            statement.conclusion
        )
    raise TypingError("finite evaluation supports comparisons and implications")


def _int_holds(statement: Compare) -> bool:
    left = _int_value(statement.left)
    right = _int_value(statement.right)
    if statement.op == "eq":
        return left == right
    if statement.op == "le":
        return left <= right
    return left < right


def _int_value(expr: object) -> int:
    if isinstance(expr, IntLit):
        return expr.value
    if isinstance(expr, UnaryOp) and expr.op == "neg":
        return -_int_value(expr.arg)
    if isinstance(expr, BinOp) and arith_type(expr) == "Int":
        left = _int_value(expr.left)
        right = _int_value(expr.right)
        if expr.op == "add":
            return left + right
        return left * right
    raise TypingError("finite evaluation expects a closed Int expression")


def limit_repetition(candidates) -> tuple:
    seen = set()
    result = []
    for candidate in candidates:
        if candidate.statement is None:
            key = ("source", candidate.source)
        else:
            key = structural_key(candidate.statement)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return tuple(result)


def diversity_metrics(candidates) -> dict:
    items = tuple(candidates)
    unique = limit_repetition(items)
    if not items:
        return {
            "count": 0,
            "unique": 0,
            "unique_ratio": 1.0,
            "shape_entropy": 0.0,
        }
    shapes = {}
    for candidate in items:
        key = (
            type(candidate.statement).__name__
            if candidate.statement is not None
            else "source"
        )
        shapes[key] = shapes.get(key, 0) + 1
    entropy = 0.0
    for count in shapes.values():
        probability = count / len(items)
        entropy -= probability * math.log2(probability)
    return {
        "count": len(items),
        "unique": len(unique),
        "unique_ratio": len(unique) / len(items),
        "shape_entropy": entropy,
    }
