"""Stage 8: exploration that can stop without a verdict."""

from __future__ import annotations

from dataclasses import dataclass

from theorem_gen.errors import GenerationError
from theorem_gen.expr import Atom, BinOp, Compare, Forall, NatLit, Var
from theorem_gen.hypothesis import HypothesisCandidate, assess_hypothesis
from theorem_gen.registry import Registry
from theorem_gen.rng import LCG
from theorem_gen.theorem import Metadata, Proof, Theorem

_TEMPLATES = ("proved_add_zero", "refuted_lt", "bounded_le", "atom_p")


@dataclass(frozen=True)
class ExplorationResult:
    identifier: str
    status: str
    reason: str
    witness: tuple
    dependencies: tuple
    discovered: bool
    statement: object


def explore(seed: int, count: int = 4, instantiation_bound: int = 3) -> list:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise GenerationError("seed must be an int")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise GenerationError("count must be >= 0")
    rng = LCG(seed)
    pool = []
    results = []
    while len(results) < count:
        if not pool:
            pool = list(_TEMPLATES)
        results.append(
            _one(pool.pop(rng.randint(0, len(pool) - 1)), len(results), instantiation_bound)
        )
    return results


def exploration_registry(results) -> Registry:
    registry = Registry()
    registry.add("lemma_Nat_add_zero", kind="lemma", rules=("primitive",), discovered=True)
    for result in results:
        registry.add(
            result.identifier,
            kind="theorem" if result.status == "proved" else "hypothesis",
            dependencies=result.dependencies,
            rules=("cite",) if result.status == "proved" else ("explore",),
            discovered=result.discovered,
        )
    return registry


def _one(template: str, index: int, bound: int) -> ExplorationResult:
    identifier = f"explore_{index:04d}"
    statement = _statement(template)
    assessment = assess_hypothesis(
        HypothesisCandidate(identifier, statement=statement, proof_supplied=False),
        search_bound=bound,
    )
    if template == "proved_add_zero" and assessment.status != "refuted":
        return ExplorationResult(
            identifier,
            "proved",
            "Cited the registered lemma Nat.add_zero. Lean must still check the exported proof.",
            (),
            ("lemma_Nat_add_zero",),
            False,
            statement,
        )
    if assessment.status == "refuted":
        witness = tuple(sorted(assessment.evidence.items()))
        return ExplorationResult(
            identifier,
            "refuted",
            "A concrete counterexample was found.",
            witness,
            (),
            False,
            statement,
        )
    if template == "atom_p":
        return ExplorationResult(
            identifier,
            "unprovable_in_fragment",
            "No registered rule introduces atom P. This judgment applies only to the registered fragment.",
            (),
            (),
            False,
            statement,
        )
    return ExplorationResult(
        identifier,
        "no_proof",
        "The bounded search produced no proof and no counterexample. The statement remains undecided.",
        (),
        (),
        False,
        statement,
    )


def _statement(template: str):
    if template == "proved_add_zero":
        variable = Var("a", "Nat")
        return Forall((variable,), Compare("eq", BinOp("add", variable, NatLit(0)), variable))
    if template == "refuted_lt":
        variable = Var("a", "Nat")
        return Forall((variable,), Compare("lt", variable, variable))
    if template == "bounded_le":
        left = Var("a", "Nat")
        right = Var("b", "Nat")
        return Forall(
            (left, right),
            Compare("le", left, BinOp("add", left, right)),
        )
    variable = Var("a", "Nat")
    return Forall((variable,), Atom("P", (variable,)))


def theorem_from_proved(result: ExplorationResult) -> Theorem:
    if result.status != "proved":
        raise GenerationError(f"{result.identifier} has status {result.status}")
    return Theorem(
        result.statement,
        Proof("lemma", "Nat.add_zero", ("a",)),
        Metadata(
            identifier=result.identifier,
            kind="universal",
            rules=("cite",),
            verification="unverified",
            dependencies=result.dependencies,
            discovered=False,
        ),
    )
