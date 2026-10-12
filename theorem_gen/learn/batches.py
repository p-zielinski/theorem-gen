"""One curriculum level adds one capability. Level 1 stays on concrete generate()."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from theorem_gen.complexity import measure_expr
from theorem_gen.config import GeneratorConfig
from theorem_gen.definitions import double_definition, theorem_about_double
from theorem_gen.errors import RegistryError
from theorem_gen.export_lean import export_library
from theorem_gen.expr import Compare, NatLit, UnaryOp
from theorem_gen.general import generate_general
from theorem_gen.generate import generate
from theorem_gen.learn.astjson import canonical_json, structural_hash
from theorem_gen.learn.errors import LearnError
from theorem_gen.registry import Registry
from theorem_gen.theorem import Metadata, Proof, Theorem

LEVELS = {
    1: frozenset({"concrete"}),
    2: frozenset({"concrete", "general"}),
    3: frozenset({"concrete", "general", "wide_ast"}),
    4: frozenset({"concrete", "general", "wide_ast", "registry"}),
    5: frozenset({"concrete", "general", "wide_ast", "registry", "complexity"}),
    6: frozenset(
        {"concrete", "general", "wide_ast", "registry", "complexity", "definitions"}
    ),
    7: frozenset(
        {
            "concrete",
            "general",
            "wide_ast",
            "registry",
            "complexity",
            "definitions",
            "roles",
        }
    ),
}

WIDE_BOUNDS = {
    "ast_size": (1, 1000),
    "depth": (1, 100),
    "variables": (0, 100),
    "operators": (0, 1000),
    "dependencies": (0, 100),
    "definitions": (0, 100),
}


def capabilities(level: int) -> frozenset:
    try:
        return LEVELS[level]
    except KeyError as exc:
        raise LearnError(f"curriculum level {level} is outside 1..7") from exc


def has_capability(level: int, name: str) -> bool:
    return name in capabilities(level)


@dataclass
class BatchItem:
    stable_id: str
    candidate_kind: str
    canonical_ast_json: str
    structural_hash: str
    family: str
    proof_method: str
    ast_size: int
    depth: int
    dependency_depth: int
    provenance: dict
    validation_type: str
    theorem: object = None
    definition: object = None
    support: tuple = ()
    depends_on: tuple = ()
    registry_deps: tuple = ()
    ancestor_stable_id: str = None
    needs_roles: bool = False
    rules: tuple = field(default_factory=tuple)
    lean_source: str = ""


# Shifts the review generator off the forward batch so the same index is a new row.
_REVIEW_SEED = 1_000_003


def rich_items(seed: int, batch_index: int, run_id: str, seen) -> tuple:
    """One equational theorem for this batch, unless that statement is already stored."""
    from theorem_gen.richgen import rich_theorem

    theorem = rich_theorem(seed, batch_index)
    digest = hashlib.sha256(theorem.statement.encode("utf-8")).hexdigest()
    if digest in set(seen):
        return ()
    return (
        BatchItem(
            stable_id=_scoped(run_id, f"richgen:{seed}:{batch_index}"),
            candidate_kind="theorem",
            canonical_ast_json=json.dumps(
                {"generator": "richgen", "statement": theorem.statement},
                sort_keys=True,
            ),
            structural_hash=digest,
            family=theorem.family,
            proof_method=theorem.proof_method,
            ast_size=theorem.size,
            depth=theorem.depth,
            dependency_depth=0,
            provenance={
                "origin": "generator",
                "generator": "richgen",
                "rule": theorem.family,
                "seed": seed,
                "batch_index": batch_index,
            },
            validation_type="proof",
            lean_source=theorem.source,
            needs_roles=False,
        ),
    )


def review_level_for(level: int, batch_index: int):
    """Lower level rehearsed by this batch. Level 1 has nothing earlier to repeat."""
    capabilities(level)
    if isinstance(batch_index, bool) or not isinstance(batch_index, int) or batch_index < 0:
        raise LearnError("batch_index must be >= 0")
    if level == 1:
        return None
    return (batch_index % (level - 1)) + 1


def review_items(
    level: int,
    *,
    seed: int,
    count: int,
    batch_index: int = 0,
    run_id: str = "",
    seen=(),
) -> tuple:
    """A rotating slice of an earlier level, tagged so the promotion gate ignores it.

    Half of `count`, and at least one when `count` is positive. Statements
    already stored for the run are skipped. The lower batch may add that
    level's whole surface on top of the half.
    """
    source = review_level_for(level, batch_index)
    if source is None or count <= 0:
        return ()
    review_count = max(1, count // 2)
    items = novel_batch(
        source,
        seed=seed + _REVIEW_SEED * source,
        count=review_count,
        batch_index=batch_index,
        run_id=run_id,
        seen=seen,
    )
    return _tag_review(list(items), source, batch_index)


def novel_batch(
    level: int,
    *,
    seed: int,
    count: int,
    batch_index: int = 0,
    run_id: str = "",
    seen=(),
) -> tuple:
    """A batch whose statements are not already in `seen`.

    The default literal cap is 0..9. When that surface is already stored, the
    next draw raises the cap by 10. Depth stays 2. This does not change
    `python3 -m theorem_gen generate`.
    """
    if count <= 0:
        return ()
    blocked = set(seen)
    chosen = []
    chosen_hashes = set()
    target = max(count, 1)
    for step in range(8):
        items = build_batch(
            level,
            seed=seed + step * _REVIEW_SEED,
            count=count,
            batch_index=batch_index,
            run_id=run_id,
            max_literal=9 + 10 * step,
        )
        for item in items:
            if item.structural_hash in blocked or item.structural_hash in chosen_hashes:
                continue
            chosen_hashes.add(item.structural_hash)
            chosen.append(item)
        if len(chosen) >= target:
            break
    return tuple(chosen)


def _tag_review(items, source_level: int, batch_index: int) -> tuple:
    renamed = {}
    for item in items:
        previous = item.stable_id
        item.stable_id = f"{previous}:review:{source_level}:{batch_index}"
        renamed[previous] = item.stable_id
        item.needs_roles = False
        item.provenance = dict(item.provenance)
        item.provenance["review"] = True
        item.provenance["source_level"] = source_level
    for item in items:
        item.depends_on = tuple(renamed.get(dep, dep) for dep in item.depends_on)
        item.registry_deps = tuple(renamed.get(dep, dep) for dep in item.registry_deps)
    return tuple(items)


def build_batch(
    level: int,
    *,
    seed: int,
    count: int,
    batch_index: int = 0,
    run_id: str = "",
    max_literal: int = None,
) -> tuple:
    allowed = capabilities(level)
    item_seed = seed + batch_index
    items = []
    if "concrete" in allowed:
        items.extend(
            _from_theorems(
                generate(
                    _generator_config(
                        item_seed, count, level, rules=None, max_literal=max_literal
                    )
                ),
                generator="generate",
                seed=item_seed,
                batch_index=batch_index,
                level=level,
                run_id=run_id,
            )
        )
    if "general" in allowed:
        items.extend(
            _from_theorems(
                generate_general(
                    _generator_config(
                        item_seed, count, level, rules=None, max_literal=max_literal
                    )
                ),
                generator="generate_general",
                seed=item_seed,
                batch_index=batch_index,
                level=level,
                run_id=run_id,
            )
        )
    if "wide_ast" in allowed:
        items.append(_wide(item_seed, batch_index, level, run_id))
    if "definitions" in allowed:
        items.extend(_definitions(level, run_id))
    if "registry" in allowed:
        _check_registry(items)
        for item in items:
            item.provenance["registry"] = True
    if "complexity" in allowed:
        for item in items:
            item.provenance["complexity"] = True
    if "roles" in allowed:
        for item in items:
            if item.candidate_kind == "theorem":
                item.needs_roles = True
    _assign_depths(items)
    return tuple(items)


def source_for(item: BatchItem) -> str:
    if item.lean_source:
        text = item.lean_source
        return text if text.endswith("\n") else text + "\n"
    if item.definition is not None and item.theorem is None:
        return export_library(
            (item.definition,),
            (),
            GeneratorConfig(seed=1, count=0, rules=("use_definition",)),
        )
    return export_library(
        item.support,
        (item.theorem,),
        GeneratorConfig(seed=1, count=1, rules=item.rules),
    )


def _generator_config(seed: int, count: int, level: int, *, rules, max_literal=None) -> GeneratorConfig:
    bounds = WIDE_BOUNDS if "complexity" in capabilities(level) else None
    kwargs = {}
    if max_literal is not None:
        kwargs["max_literal"] = max_literal
    return GeneratorConfig(
        seed=seed,
        count=count,
        rules=rules,
        complexity_bounds=bounds,
        **kwargs,
    )


def _from_theorems(theorems, *, generator: str, seed: int, batch_index: int, level: int, run_id: str = "") -> list:
    items = []
    for theorem in theorems:
        measures = measure_expr(theorem.statement)
        rule = theorem.metadata.rules[0] if theorem.metadata.rules else generator
        proof_method = theorem.proof.method if theorem.proof is not None else ""
        kind = "expression" if theorem.metadata.kind == "expression" else "theorem"
        validation_type = "check" if proof_method == "" or kind == "expression" else "proof"
        items.append(
            BatchItem(
                stable_id=_scoped(run_id, f"{generator}:{seed}:{batch_index}:{theorem.metadata.identifier}"),
                candidate_kind=kind,
                canonical_ast_json=canonical_json(theorem.statement),
                structural_hash=structural_hash(theorem.statement),
                family=rule,
                proof_method=proof_method,
                ast_size=measures["ast_size"],
                depth=measures["depth"],
                dependency_depth=0,
                provenance={
                    "origin": "generator",
                    "generator": generator,
                    "rule": rule,
                    "seed": seed,
                    "batch_index": batch_index,
                    "level": level,
                    "measures": measures,
                    "registry": False,
                    "complexity": False,
                },
                validation_type=validation_type,
                theorem=theorem,
                rules=tuple(theorem.metadata.rules),
            )
        )
    return items


def _scoped(run_id: str, body: str) -> str:
    if not run_id:
        return body
    return f"{run_id}:{body}"


def _wide(seed: int, batch_index: int, level: int, run_id: str = "") -> BatchItem:
    statement = Compare("eq", UnaryOp("succ", NatLit(0)), NatLit(1))
    identifier = f"wide_succ_{seed}_{batch_index}"
    theorem = Theorem(
        statement,
        Proof("rfl"),
        Metadata(
            identifier=identifier,
            kind="concrete",
            rules=("eval_eq",),
            verification="unverified",
        ),
    )
    return _from_theorems(
        (theorem,),
        generator="wide_ast",
        seed=seed,
        batch_index=batch_index,
        level=level,
        run_id=run_id,
    )[0]


def _definitions(level: int, run_id: str = "") -> list:
    definition = double_definition()
    theorem = theorem_about_double(definition)
    body_measures = measure_expr(definition.body)
    theorem_measures = measure_expr(theorem.statement)
    definition_item = BatchItem(
        stable_id=_scoped(run_id, "definition:def_double"),
        candidate_kind="definition",
        canonical_ast_json=canonical_json(definition.body),
        structural_hash=structural_hash(definition.body),
        family="define",
        proof_method="",
        ast_size=body_measures["ast_size"],
        depth=body_measures["depth"],
        dependency_depth=0,
        provenance={
            "origin": "generator",
            "generator": "definitions",
            "rule": "define",
            "level": level,
            "measures": body_measures,
            "registry": False,
            "complexity": False,
        },
        validation_type="check",
        definition=definition,
        rules=("use_definition",),
    )
    theorem_item = _from_theorems(
        (theorem,),
        generator="definitions",
        seed=0,
        batch_index=0,
        level=level,
        run_id=run_id,
    )[0]
    definition_id = _scoped(run_id, "definition:def_double")
    theorem_item.stable_id = _scoped(run_id, "theorem:gen_double_zero")
    theorem_item.support = (definition,)
    theorem_item.depends_on = (definition_id,)
    theorem_item.registry_deps = (definition_id,)
    theorem_item.ast_size = theorem_measures["ast_size"]
    theorem_item.provenance["generator"] = "definitions"
    return [definition_item, theorem_item]


def _check_registry(items) -> None:
    registry = Registry()
    ordered = sorted(items, key=lambda item: (item.candidate_kind != "definition", item.stable_id))
    try:
        for item in ordered:
            registry.add(
                item.stable_id,
                kind="definition" if item.candidate_kind == "definition" else "theorem",
                dependencies=item.registry_deps,
                rules=item.rules or (item.family,),
                discovered=not item.registry_deps,
            )
    except RegistryError as exc:
        raise LearnError(str(exc)) from exc


def _assign_depths(items) -> None:
    by_id = {item.stable_id: item for item in items}

    def depth(item, seen):
        if not item.depends_on:
            return 0
        if item.stable_id in seen:
            return 0
        seen = seen | {item.stable_id}
        return 1 + max(depth(by_id[dep], seen) for dep in item.depends_on)

    for item in items:
        item.dependency_depth = depth(item, frozenset())
