"""Stage 2: variables, universal statements, assumptions, and unproved expressions."""

from __future__ import annotations

from dataclasses import replace

from theorem_gen.config import EXTENDED_RULES, GeneratorConfig
from theorem_gen.errors import GenerationError
from theorem_gen.expr import BinOp, Compare, Forall, Implies, NatLit, Var, structural_key
from theorem_gen.generate import seed_token
from theorem_gen.rng import LCG
from theorem_gen.theorem import Metadata, Proof, Theorem

GENERAL_RULES = EXTENDED_RULES


def config_for_export(config: GeneratorConfig) -> GeneratorConfig:
    """Record the rule list `generate_general` used.

    A config with `rules=None` still means the stage-1 concrete rules for
    `generate` and for `resolved_rules`. General generation treats that
    omission as `GENERAL_RULES`, so the exported header must be aligned
    before it is written.
    """
    if config.rules is not None:
        return config
    return replace(config, rules=GENERAL_RULES)


def generate_general(config: GeneratorConfig) -> list:
    if config.count == 0:
        return []
    rules = config.resolved_rules() if config.rules is not None else GENERAL_RULES
    unknown = [rule for rule in rules if rule not in GENERAL_RULES]
    if unknown:
        raise GenerationError(f"{unknown[0]} is not a general rule")
    if not rules:
        raise GenerationError(
            f"No construction rules configured; cannot generate {config.count} theorems."
        )
    rng = LCG(config.seed)
    seen = set()
    theorems = []
    attempts = 0
    limit = config.effective_max_attempts()
    while len(theorems) < config.count:
        if attempts >= limit:
            detail = "The unique setting rejected repeated statements. " if config.unique and theorems else ""
            raise GenerationError(
                f"Stopped after {attempts} attempts: requested {config.count} theorems, "
                f"produced {len(theorems)}. {detail}"
                "This is a generation limit, not a mathematical verdict."
            )
        attempts += 1
        rule = rules[0] if len(rules) == 1 else rules[rng.randint(0, len(rules) - 1)]
        theorem = _build(rule, config.seed, len(theorems))
        if config.complexity_bounds and not _within_complexity(theorem, config):
            continue
        key = structural_key(theorem.statement)
        if config.unique and key in seen:
            continue
        seen.add(key)
        theorems.append(theorem)
    return theorems


def _within_complexity(theorem, config: GeneratorConfig) -> bool:
    from theorem_gen.complexity import candidate_within_bounds

    return candidate_within_bounds(config.complexity_bounds, theorem=theorem)


def _meta(seed: int, index: int, kind: str, rule: str) -> Metadata:
    return Metadata(
        identifier=f"gen_s{seed_token(seed)}_{index:04d}",
        kind=kind,
        rules=(rule,),
        verification="unverified",
        discovered=True,
    )


def _build(rule: str, seed: int, index: int) -> Theorem:
    spec = _SCHEMAS[rule]
    shifted = _shifted(rule, seed, index)
    if shifted is None:
        statement, proof = spec["statement"], spec["proof"]
    else:
        statement, proof = shifted
    return Theorem(statement, proof, _meta(seed, index, spec["kind"], rule))


def _offset(seed: int, index: int) -> int:
    """Zero keeps the canonical statement. Later copies move with the seed."""
    if index <= 0:
        return 0
    return index + abs(int(seed)) % 10000


def _shifted(rule: str, seed: int, index: int):
    """One numeral added to the quantified term. The same lemma still closes it."""
    offset = _offset(seed, index)
    if offset <= 0 or rule not in _SHIFTS:
        return None
    kind, reference, names = _SHIFTS[rule]
    terms = [f"({name} + {offset})" for name in names]
    if kind == "add_zero":
        body = Compare(
            "eq",
            BinOp("add", BinOp("add", _A, NatLit(offset)), NatLit(0)),
            BinOp("add", _A, NatLit(offset)),
        )
        binders = ("a",)
    elif kind == "zero_add":
        body = Compare(
            "eq",
            BinOp("add", NatLit(0), BinOp("add", _A, NatLit(offset))),
            BinOp("add", _A, NatLit(offset)),
        )
        binders = ("a",)
    elif kind == "mul_one":
        body = Compare(
            "eq",
            BinOp("mul", BinOp("add", _A, NatLit(offset)), NatLit(1)),
            BinOp("add", _A, NatLit(offset)),
        )
        binders = ("a",)
    elif kind == "one_mul":
        body = Compare(
            "eq",
            BinOp("mul", NatLit(1), BinOp("add", _A, NatLit(offset))),
            BinOp("add", _A, NatLit(offset)),
        )
        binders = ("a",)
    elif kind == "le_refl":
        body = Compare("le", BinOp("add", _A, NatLit(offset)), BinOp("add", _A, NatLit(offset)))
        binders = ("a",)
    elif kind == "add_comm":
        left = BinOp("add", _A, NatLit(offset))
        right = BinOp("add", _B, NatLit(offset))
        body = Compare("eq", BinOp("add", left, right), BinOp("add", right, left))
        binders = ("a", "b")
    else:
        left = BinOp("add", _A, NatLit(offset))
        right = BinOp("add", _B, NatLit(offset))
        body = Compare("eq", BinOp("mul", left, right), BinOp("mul", right, left))
        binders = ("a", "b")
    return _forall(binders, body), Proof("lemma", reference, tuple(terms))


_SHIFTS = {
    "add_zero_all": ("add_zero", "Nat.add_zero", ("a",)),
    "zero_add_all": ("zero_add", "Nat.zero_add", ("a",)),
    "mul_one_all": ("mul_one", "Nat.mul_one", ("a",)),
    "one_mul_all": ("one_mul", "Nat.one_mul", ("a",)),
    "le_refl_all": ("le_refl", "Nat.le_refl", ("a",)),
    "add_comm_all": ("add_comm", "Nat.add_comm", ("a", "b")),
    "mul_comm_all": ("mul_comm", "Nat.mul_comm", ("a", "b")),
}


def _var(name: str) -> Var:
    return Var(name, "Nat")


def _forall(names: tuple, body: object) -> Forall:
    return Forall(tuple(_var(name) for name in names), body)


_A = _var("a")
_B = _var("b")

_SCHEMAS = {
    "add_zero_all": {
        "kind": "universal",
        "proof": Proof("lemma", "Nat.add_zero", ("a",)),
        "statement": _forall(("a",), Compare("eq", BinOp("add", _A, NatLit(0)), _A)),
    },
    "zero_add_all": {
        "kind": "universal",
        "proof": Proof("lemma", "Nat.zero_add", ("a",)),
        "statement": _forall(("a",), Compare("eq", BinOp("add", NatLit(0), _A), _A)),
    },
    "add_comm_all": {
        "kind": "universal",
        "proof": Proof("lemma", "Nat.add_comm", ("a", "b")),
        "statement": _forall(
            ("a", "b"),
            Compare("eq", BinOp("add", _A, _B), BinOp("add", _B, _A)),
        ),
    },
    "mul_comm_all": {
        "kind": "universal",
        "proof": Proof("lemma", "Nat.mul_comm", ("a", "b")),
        "statement": _forall(
            ("a", "b"),
            Compare("eq", BinOp("mul", _A, _B), BinOp("mul", _B, _A)),
        ),
    },
    "mul_one_all": {
        "kind": "universal",
        "proof": Proof("lemma", "Nat.mul_one", ("a",)),
        "statement": _forall(("a",), Compare("eq", BinOp("mul", _A, NatLit(1)), _A)),
    },
    "one_mul_all": {
        "kind": "universal",
        "proof": Proof("lemma", "Nat.one_mul", ("a",)),
        "statement": _forall(("a",), Compare("eq", BinOp("mul", NatLit(1), _A), _A)),
    },
    "le_refl_all": {
        "kind": "universal",
        "proof": Proof("lemma", "Nat.le_refl", ("a",)),
        "statement": _forall(("a",), Compare("le", _A, _A)),
    },
    "eq_implies_add_zero": {
        "kind": "conditional",
        "proof": Proof("rewrite", "Nat.add_zero", ("h",)),
        "statement": _forall(
            ("a", "b"),
            Implies(Compare("eq", _A, _B), Compare("eq", BinOp("add", _A, NatLit(0)), _B)),
        ),
    },
    "open_double_eq": {
        "kind": "expression",
        "proof": None,
        "statement": _forall(("a",), Compare("eq", BinOp("add", _A, _A), _A)),
    },
}
