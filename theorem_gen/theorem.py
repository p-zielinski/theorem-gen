"""A theorem is a proposition plus an optional proof and metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from theorem_gen.errors import TheoremError, TypingError
from theorem_gen.expr import infer

_VERIFICATION = {"unverified", "proved", "failed", "timeout", "unavailable"}
_PROOF_METHODS = {"rfl", "decide", "lemma", "rewrite"}


@dataclass(frozen=True)
class Proof:
    method: str
    reference: str = ""
    arguments: tuple = ()

    def __post_init__(self) -> None:
        if self.method not in _PROOF_METHODS:
            raise TheoremError(f"unsupported proof method: {self.method}")
        if not isinstance(self.reference, str):
            raise TheoremError("reference must be a string")
        if isinstance(self.arguments, str) or not isinstance(self.arguments, (tuple, list)):
            raise TheoremError("arguments must be a tuple of strings")
        arguments = tuple(self.arguments)
        if any(not isinstance(item, str) for item in arguments):
            raise TheoremError("arguments must be a tuple of strings")
        object.__setattr__(self, "arguments", arguments)
        if self.method in {"lemma", "rewrite"} and not self.reference:
            raise TheoremError(f"{self.method} requires a reference")
        if self.method == "rewrite" and not arguments:
            raise TheoremError("rewrite requires a hypothesis name")


@dataclass(frozen=True)
class Metadata:
    identifier: str
    kind: str
    rules: Tuple[str, ...]
    verification: str
    dependencies: Tuple[str, ...] = ()
    discovered: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier:
            raise TheoremError("identifier must be a non-empty string")
        if not isinstance(self.kind, str) or not self.kind:
            raise TheoremError("kind must be a non-empty string")
        if self.verification not in _VERIFICATION:
            raise TheoremError(f"unknown verification status: {self.verification}")
        object.__setattr__(self, "rules", _strings(self.rules, "rules"))
        object.__setattr__(self, "dependencies", _strings(self.dependencies, "dependencies"))
        if not isinstance(self.discovered, bool):
            raise TheoremError("discovered must be a bool")


def _strings(value: object, label: str) -> tuple:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise TheoremError(f"{label} must be a tuple of strings")
    items = tuple(value)
    if any(not isinstance(item, str) for item in items):
        raise TheoremError(f"{label} must be a tuple of strings")
    return items


@dataclass(frozen=True)
class Theorem:
    statement: object
    proof: Optional[Proof]
    metadata: Metadata

    def __post_init__(self) -> None:
        try:
            kind = infer(self.statement)
        except TypingError as exc:
            raise TheoremError(str(exc)) from exc
        if kind != "Prop":
            raise TheoremError("statement must be a proposition")
        if self.proof is not None and not isinstance(self.proof, Proof):
            raise TheoremError("proof must be a Proof or None")
        if not isinstance(self.metadata, Metadata):
            raise TheoremError("metadata is required")

    def with_verification(self, status: str) -> "Theorem":
        meta = self.metadata
        return Theorem(
            statement=self.statement,
            proof=self.proof,
            metadata=Metadata(
                identifier=meta.identifier,
                kind=meta.kind,
                rules=meta.rules,
                verification=status,
                dependencies=meta.dependencies,
                discovered=meta.discovered,
            ),
        )


def claimed_true(theorem: Theorem) -> bool:
    """Generation alone never establishes a statement."""
    return theorem.metadata.verification == "proved" and theorem.proof is not None
