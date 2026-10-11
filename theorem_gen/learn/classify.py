"""Derive a candidate outcome from Lean validations only.

Role text, a Python witness, and agreement among roles are not inputs.
`quarantined` means the store holds both an accepted proof and an accepted
counterexample certificate. That is a system defect, not a fifth mathematical
outcome and not a synonym of proved, refuted, unresolved, or ill_formed.
"""

from __future__ import annotations

from typing import Optional, Sequence

OUTCOMES = ("proved", "refuted", "unresolved", "ill_formed")
DEFECT = "quarantined"
STATUSES = OUTCOMES + (DEFECT,)

_HYPOTHESIS_MAP = {
    "invalid_syntax": "ill_formed",
    "invalid_type": "ill_formed",
    "proved": "proved",
    "refuted": "refuted",
    "unresolved": "unresolved",
}


class ValidationView:
    def __init__(self, validation_type: str, result: str, accepted: bool, failure_class: Optional[str]) -> None:
        self.validation_type = validation_type
        self.result = result
        self.accepted = bool(accepted)
        self.failure_class = failure_class


def map_hypothesis_status(status: str) -> str:
    """Vocabulary map from assess_hypothesis. It does not write a store status."""
    try:
        return _HYPOTHESIS_MAP[status]
    except KeyError as exc:
        raise ValueError(f"unknown hypothesis status: {status}") from exc


def map_report(report, validation_type: str) -> ValidationView:
    failure = report.failure_class
    if failure in {"rejected", "syntax", "typing"}:
        return ValidationView(validation_type, "ill_formed", False, failure)
    if report.status == "timeout":
        return ValidationView(validation_type, "timeout", False, None)
    if report.status == "unavailable":
        return ValidationView(validation_type, "unavailable", False, None)
    if report.status == "proved":
        # A check records that Lean accepted a definition or expression.
        # The accepted flag stays false so the row cannot become proved.
        if validation_type == "check":
            return ValidationView(validation_type, "accepted", False, None)
        return ValidationView(validation_type, "accepted", True, None)
    return ValidationView(validation_type, "rejected", False, failure or "other")


def _accepted_certificate(item: ValidationView, validation_type: str) -> bool:
    return bool(item.accepted) and item.result == "accepted" and item.validation_type == validation_type


def derive_outcome(validations: Sequence[ValidationView]) -> str:
    proofs = [item for item in validations if _accepted_certificate(item, "proof")]
    refutations = [item for item in validations if _accepted_certificate(item, "counterexample")]
    if proofs and refutations:
        return DEFECT
    if proofs:
        return "proved"
    if refutations:
        return "refuted"
    for item in validations:
        if item.result == "ill_formed" or item.failure_class in {"syntax", "typing", "rejected"}:
            return "ill_formed"
    return "unresolved"


def counts_as_lean_evaluated(item: ValidationView) -> bool:
    """A pre-Lean refusal, a missing toolchain, and a timeout are not evaluations.

    A timeout means Lean did not decide the file. It must not fill the
    promotion count of 1000.
    """
    if item.failure_class == "rejected":
        return False
    if item.result in {"unavailable", "timeout"}:
        return False
    return True


def mathematical_outcome(status: str) -> Optional[str]:
    if status == DEFECT:
        return None
    if status not in OUTCOMES:
        raise ValueError(f"unknown status: {status}")
    return status
