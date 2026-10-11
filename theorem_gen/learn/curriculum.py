"""Promotion gates. Training loss is not an input."""

from __future__ import annotations

import json

from theorem_gen.learn.classify import ValidationView, counts_as_lean_evaluated, derive_outcome

MIN_EVALUATED = 1000
WINDOW_SIZE = 100
CONSECUTIVE_WINDOWS = 3
NOVELTY_FLOOR = 0.5


def generator_of(row) -> str:
    raw = row["provenance"]
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    generator = payload.get("generator")
    return generator if isinstance(generator, str) else ""


def coverage_met(level: int, rows: list) -> bool:
    """1000 stays the floor. Only a level that adds a new surface asks for more.

    Level 2 adds a second distribution, so the thousand must come from
    `generate_general`. Level 3 adds one fixed statement. Level 6 adds the
    `double` definition and its theorem. Registry and complexity add no
    candidates, so levels 4 and 5 do not raise the count.
    """
    if level == 2:
        return sum(generator_of(row) == "generate_general" for row in rows) >= MIN_EVALUATED
    if level == 3:
        return any(generator_of(row) == "wide_ast" for row in rows)
    if level == 6:
        kinds = {row["kind"] for row in rows if generator_of(row) == "definitions"}
        return "definition" in kinds and "theorem" in kinds
    return True


def level_is_justified(store, run_id: str, level: int) -> bool:
    if level == 1:
        return True
    return all(store.passed_gate(run_id, previous) for previous in range(1, level))


def window_health(rows: list) -> dict:
    hashes = [row["structural_hash"] for row in rows]
    novelty = len(set(hashes)) / len(rows) if rows else 0.0
    methods = {row["proof_method"] for row in rows if row["proof_method"]}
    sizes = sorted(row["ast_size"] for row in rows)
    median = sizes[len(sizes) // 2] if sizes else 0
    depths = [row["dependency_depth"] for row in rows]
    violations = sum(1 for row in rows if row["violation"])
    families = {row["family"] for row in rows}
    gaming = novelty < NOVELTY_FLOOR or (
        len(methods) <= 1 and median <= 2 and len(rows) >= WINDOW_SIZE
    )
    return {
        "novelty": novelty,
        "median_ast_size": median,
        "proof_diversity": len(methods),
        "max_dependency_depth": max(depths) if depths else 0,
        "unique_families": len(families),
        "violations": violations,
        "triviality_gaming": gaming,
        "passed": violations == 0 and not gaming,
    }


def assess_gate(store, run_id: str, *, held_out_latest: float, held_out_baseline: float) -> dict:
    run = store.get_run(run_id)
    level = int(run["curriculum_level"])
    rows = [row for row in _annotated(store, run_id, level) if not row["held_out"]]
    violations = sum(1 for row in rows if row["violation"])
    evaluated = [row for row in rows if row["evaluated"]]
    windows = []
    for start in range(0, len(evaluated), WINDOW_SIZE):
        chunk = evaluated[start : start + WINDOW_SIZE]
        if len(chunk) == WINDOW_SIZE:
            windows.append(chunk)
    reports = []
    for index, window in enumerate(windows):
        report = window_health(window)
        report["index"] = index
        reports.append(report)
        store.upsert_window(
            run_id=run_id,
            level=level,
            window_index=index,
            metrics_json=json.dumps(report, sort_keys=True),
            gate_status="passed" if report["passed"] else "failed",
            evaluated_count=len(window),
        )
    promote = False
    freeze = False
    reason = "not_ready"
    if violations:
        freeze = True
        reason = "correctness"
    elif held_out_baseline is not None and held_out_latest < held_out_baseline:
        freeze = True
        reason = "held_out"
    elif len(evaluated) < MIN_EVALUATED:
        reason = "evaluated"
    elif not coverage_met(level, evaluated):
        reason = "coverage"
    elif len(reports) < CONSECUTIVE_WINDOWS:
        reason = "windows"
    elif not all(item["passed"] for item in reports[-CONSECUTIVE_WINDOWS:]):
        freeze = True
        reason = "diversity"
    else:
        promote = True
        reason = "passed"
    return {
        "promote": promote,
        "freeze": freeze,
        "reason": reason,
        "evaluated": len(evaluated),
        "windows": reports,
        "violations": violations,
        "level": level,
    }


def _annotated(store, run_id: str, level: int) -> list:
    grouped = {}
    for row in store.validations_for_level(run_id, level):
        grouped.setdefault(row["candidate_id"], []).append(row)
    annotated = []
    for candidate in store.candidates_for_level(run_id, level):
        validations = grouped.get(candidate["id"], [])
        views = [
            ValidationView(
                item["validation_type"],
                item["result"],
                bool(item["accepted"]),
                item["failure_class"],
            )
            for item in validations
        ]
        derived = derive_outcome(views) if views else "unresolved"
        violation = candidate["current_status"] == "quarantined" or derived != candidate["current_status"]
        evaluated = any(counts_as_lean_evaluated(view) for view in views)
        annotated.append(
            dict(candidate, violation=violation, evaluated=evaluated)
        )
    return annotated
