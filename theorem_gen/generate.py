"""Deterministic generator of concrete Nat theorems."""

from __future__ import annotations

from typing import Optional, Tuple

from theorem_gen.config import GeneratorConfig
from theorem_gen.errors import GenerationError, TypingError
from theorem_gen.expr import BinOp, Compare, NatLit, evaluate, structural_key
from theorem_gen.rng import LCG
from theorem_gen.theorem import Metadata, Proof, Theorem


def seed_token(seed: int) -> str:
    if seed < 0:
        return f"neg{-seed}"
    return str(seed)


def generate(config: GeneratorConfig) -> list:
    if config.count == 0:
        return []
    rules = config.resolved_rules()
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
            detail = ""
            if config.unique and theorems:
                detail = "The unique setting rejected repeated statements. "
            raise GenerationError(
                f"Stopped after {attempts} attempts: requested {config.count} theorems, "
                f"produced {len(theorems)}. {detail}"
                "This is a generation limit, not a mathematical verdict."
            )
        attempts += 1
        rule = rules[0] if len(rules) == 1 else rules[rng.randint(0, len(rules) - 1)]
        built = _apply_rule(rule, rng, config)
        if built is None:
            continue
        statement, proof, dependencies = built
        if _exceeds_max_value(statement, config):
            continue
        if config.complexity_bounds and not _within_complexity(
            statement, dependencies, config
        ):
            continue
        key = structural_key(statement)
        if config.unique and key in seen:
            continue
        seen.add(key)
        identifier = f"gen_s{seed_token(config.seed)}_{len(theorems):04d}"
        theorems.append(
            Theorem(
                statement=statement,
                proof=proof,
                metadata=Metadata(
                    identifier=identifier,
                    kind="concrete",
                    rules=(rule,),
                    verification="unverified",
                    dependencies=dependencies,
                    discovered=not dependencies,
                ),
            )
        )
    return theorems


def _apply_rule(
    rule: str, rng: LCG, config: GeneratorConfig
) -> Optional[Tuple[Compare, Proof, tuple]]:
    implementation = _RULES.get(rule)
    if implementation is None:
        raise GenerationError(f"{rule} is not a concrete rule")
    built = implementation(rng, config)
    if built is None:
        return None
    if len(built) == 2:
        statement, proof = built
        return statement, proof, ()
    return built


def _exceeds_max_value(statement: Compare, config: GeneratorConfig) -> bool:
    try:
        left = evaluate(statement.left)
        right = evaluate(statement.right)
    except TypingError:
        return False
    return left > config.max_value or right > config.max_value


def _within_complexity(statement: Compare, dependencies: tuple, config: GeneratorConfig) -> bool:
    from theorem_gen.complexity import measure_expr, within_bounds

    measures = measure_expr(statement)
    measures["dependencies"] = len(dependencies)
    if dependencies:
        measures["definitions"] = len(dependencies)
    return within_bounds(measures, config.complexity_bounds)


def _literal(rng: LCG, config: GeneratorConfig) -> int:
    return rng.randint(0, config.max_literal)


def _random_expr(rng: LCG, config: GeneratorConfig, depth_left: int):
    if depth_left <= 0 or rng.random() < 0.35:
        return NatLit(rng.randint(0, config.max_literal))
    operator = "add" if rng.randint(0, 1) == 0 else "mul"
    return BinOp(
        operator,
        _random_expr(rng, config, depth_left - 1),
        _random_expr(rng, config, depth_left - 1),
    )


def _eval_eq(rng: LCG, config: GeneratorConfig):
    expr = _random_expr(rng, config, config.max_depth)
    return Compare("eq", expr, NatLit(evaluate(expr))), Proof("rfl")


def _add_zero(rng: LCG, config: GeneratorConfig):
    number = _literal(rng, config)
    return (
        Compare("eq", BinOp("add", NatLit(number), NatLit(0)), NatLit(number)),
        Proof("rfl"),
    )


def _zero_add(rng: LCG, config: GeneratorConfig):
    number = _literal(rng, config)
    return (
        Compare("eq", BinOp("add", NatLit(0), NatLit(number)), NatLit(number)),
        Proof("rfl"),
    )


def _with_one(rng: LCG, config: GeneratorConfig, one_on_the_right: bool):
    if config.max_literal < 1:
        return None
    number = _literal(rng, config)
    if one_on_the_right:
        expr = BinOp("mul", NatLit(number), NatLit(1))
    else:
        expr = BinOp("mul", NatLit(1), NatLit(number))
    return Compare("eq", expr, NatLit(number)), Proof("rfl")


def _mul_one(rng: LCG, config: GeneratorConfig):
    return _with_one(rng, config, True)


def _one_mul(rng: LCG, config: GeneratorConfig):
    return _with_one(rng, config, False)


def _mul_zero(rng: LCG, config: GeneratorConfig):
    number = _literal(rng, config)
    return (
        Compare("eq", BinOp("mul", NatLit(number), NatLit(0)), NatLit(0)),
        Proof("rfl"),
    )


def _zero_mul(rng: LCG, config: GeneratorConfig):
    number = _literal(rng, config)
    return (
        Compare("eq", BinOp("mul", NatLit(0), NatLit(number)), NatLit(0)),
        Proof("rfl"),
    )


def _comm(rng: LCG, config: GeneratorConfig, operator: str):
    left = _literal(rng, config)
    right = _literal(rng, config)
    return (
        Compare(
            "eq",
            BinOp(operator, NatLit(left), NatLit(right)),
            BinOp(operator, NatLit(right), NatLit(left)),
        ),
        Proof("rfl"),
    )


def _add_comm(rng: LCG, config: GeneratorConfig):
    return _comm(rng, config, "add")


def _mul_comm(rng: LCG, config: GeneratorConfig):
    return _comm(rng, config, "mul")


def _le_between(rng: LCG, config: GeneratorConfig):
    left = _literal(rng, config)
    right = rng.randint(left, config.max_literal)
    return Compare("le", NatLit(left), NatLit(right)), Proof("decide")


def _lt_between(rng: LCG, config: GeneratorConfig):
    if config.max_literal < 1:
        return None
    left = rng.randint(0, config.max_literal - 1)
    right = rng.randint(left + 1, config.max_literal)
    return Compare("lt", NatLit(left), NatLit(right)), Proof("decide")


def _le_refl(rng: LCG, config: GeneratorConfig):
    number = _literal(rng, config)
    return Compare("le", NatLit(number), NatLit(number)), Proof("decide")


def _use_definition(rng: LCG, config: GeneratorConfig):
    from theorem_gen.definitions import theorem_about_double

    theorem = theorem_about_double()
    return theorem.statement, theorem.proof, theorem.metadata.dependencies


_RULES = {
    "eval_eq": _eval_eq,
    "add_zero": _add_zero,
    "zero_add": _zero_add,
    "mul_one": _mul_one,
    "one_mul": _one_mul,
    "mul_zero": _mul_zero,
    "zero_mul": _zero_mul,
    "add_comm": _add_comm,
    "mul_comm": _mul_comm,
    "le_between": _le_between,
    "lt_between": _lt_between,
    "le_refl": _le_refl,
    "use_definition": _use_definition,
}
