"""Generator configuration for concrete Nat theorems."""

from __future__ import annotations

from dataclasses import dataclass

from theorem_gen.errors import GenerationError

DEFAULT_RULES = (
    "eval_eq",
    "add_zero",
    "zero_add",
    "mul_one",
    "one_mul",
    "mul_zero",
    "zero_mul",
    "add_comm",
    "mul_comm",
    "le_between",
    "lt_between",
    "le_refl",
)

EXTENDED_RULES = (
    "add_zero_all",
    "zero_add_all",
    "add_comm_all",
    "mul_comm_all",
    "mul_one_all",
    "one_mul_all",
    "le_refl_all",
    "eq_implies_add_zero",
    "open_double_eq",
)

DEFINITION_RULES = ("use_definition",)

ALLOWED_RULES = DEFAULT_RULES + EXTENDED_RULES + DEFINITION_RULES
COMPLEXITY_MEASURES = (
    "ast_size",
    "depth",
    "variables",
    "operators",
    "dependencies",
    "definitions",
)


def _bounds(value: object):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise GenerationError("complexity_bounds must be a mapping")
    clean = {}
    for key, pair in value.items():
        if key not in COMPLEXITY_MEASURES:
            raise GenerationError(f"unknown complexity measure: {key}")
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise GenerationError(f"bounds for {key} must be a low, high pair")
        low, high = pair
        _require_int(f"{key} low", low, 0)
        _require_int(f"{key} high", high, 0)
        if low > high:
            raise GenerationError(f"{key} low must be <= high")
        clean[key] = (low, high)
    return clean


def _require_int(name: str, value: object, minimum: int = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GenerationError(f"{name} must be an int")
    if minimum is not None and value < minimum:
        raise GenerationError(f"{name} must be >= {minimum}")


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int
    count: int
    max_literal: int = 9
    max_depth: int = 2
    max_value: int = 10000
    unique: bool = True
    rules: tuple = None
    max_attempts: int = None
    complexity_bounds: object = None

    def __post_init__(self) -> None:
        _require_int("seed", self.seed)
        _require_int("count", self.count, 0)
        _require_int("max_literal", self.max_literal, 0)
        _require_int("max_depth", self.max_depth, 0)
        _require_int("max_value", self.max_value, 0)
        if not isinstance(self.unique, bool):
            raise GenerationError("unique must be a bool")
        if self.max_attempts is not None:
            _require_int("max_attempts", self.max_attempts, 0)
        if self.rules is not None:
            if isinstance(self.rules, str) or not isinstance(self.rules, (tuple, list)):
                raise GenerationError("rules must be a sequence of rule names")
            rules = tuple(self.rules)
            unknown = [rule for rule in rules if rule not in ALLOWED_RULES]
            if unknown:
                raise GenerationError("unknown rules: " + ", ".join(unknown))
            object.__setattr__(self, "rules", rules)
        object.__setattr__(
            self, "complexity_bounds", _bounds(self.complexity_bounds)
        )

    def resolved_rules(self) -> tuple:
        if self.rules is None:
            return DEFAULT_RULES
        return self.rules

    def effective_max_attempts(self) -> int:
        if self.max_attempts is None:
            return max(100, self.count * 100)
        return self.max_attempts
