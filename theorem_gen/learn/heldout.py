"""Fixed held-out pair. These statements are never training rows."""

from __future__ import annotations

from theorem_gen.config import GeneratorConfig
from theorem_gen.export_lean import export_module
from theorem_gen.expr import Compare, NatLit
from theorem_gen.learn.astjson import structural_hash
from theorem_gen.learn.validate import negation_source, python_witness
from theorem_gen.theorem import Metadata, Proof, Theorem


def held_out_true() -> Theorem:
    return Theorem(
        Compare("eq", NatLit(0), NatLit(0)),
        Proof("rfl"),
        Metadata(
            identifier="heldout_true",
            kind="concrete",
            rules=("eval_eq",),
            verification="unverified",
        ),
    )


def held_out_false_statement():
    return Compare("eq", NatLit(1), NatLit(0))


HELD_OUT_HASHES = frozenset(
    (
        structural_hash(held_out_true().statement),
        structural_hash(held_out_false_statement()),
    )
)


def evaluate_held_out(validate) -> dict:
    """Score the frozen pair. `validate(source, validation_type)` returns a record."""
    true = held_out_true()
    true_source = export_module(
        (true,),
        GeneratorConfig(seed=1, count=1, rules=("eval_eq",)),
    )
    true_result = validate(true_source, "proof")
    true_ok = bool(true_result["accepted"]) and true_result["validation_type"] == "proof"
    witness = python_witness(held_out_false_statement())
    false_ok = False
    if witness is not None:
        source = negation_source(witness["instantiated_prop"], "heldout_false")
        false_result = validate(source, "counterexample")
        false_ok = (
            bool(false_result["accepted"])
            and false_result["validation_type"] == "counterexample"
        )
    matched = int(true_ok) + int(false_ok)
    return {
        "score": matched / 2,
        "matched": matched,
        "total": 2,
        "false_proved": False,
    }


def scores_from_held_out(result: dict) -> dict:
    """solve_rate and correctness come from the held-out pair.

    diversity and resource are reference constants for the deterministic
    generator. They are not measurements of a neural model.
    """
    score = float(result["score"])
    return {
        "correctness": 0.0 if result.get("false_proved") else 1.0,
        "solve_rate": score,
        "calibration": score,
        "diversity": 1.0,
        "resource": 1.0,
    }
