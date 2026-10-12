"""Champion and challenger bookkeeping. No online fine-tune.

A version is learning only when `learning_claimed` is true: the active champion
is not the generator baseline and its stored held-out scores beat that baseline.
Filling SQLite is experiment memory, not that claim.
"""

from __future__ import annotations

import json

from theorem_gen.learn.errors import LearnError
from theorem_gen.learn.heldout import HELD_OUT_HASHES

METRICS = ("correctness", "solve_rate", "calibration", "diversity", "resource")
DESCENDANT_CAP = 8
BASELINE_ID = "generator-v0"
CHAMPION_ID = "champion-generator-v0"


def admit_descendant(store, ancestor_stable_id: str, *, cap: int = DESCENDANT_CAP) -> bool:
    if not ancestor_stable_id:
        return True
    return store.count_descendants(ancestor_stable_id) < cap


def ensure_baseline(store, scores: dict) -> None:
    if store.get_model(BASELINE_ID) is None:
        store.insert_model(
            version_id=BASELINE_ID,
            role="baseline",
            scores=scores,
            path="generator",
            weight_hash=BASELINE_ID,
            adapter_hash="",
        )
    if store.champion() is None:
        store.insert_model(
            version_id=CHAMPION_ID,
            role="champion",
            scores=dict(scores),
            path="generator",
            weight_hash=BASELINE_ID,
            adapter_hash="",
        )


def _placeholder_pair(scores: dict) -> bool:
    """Generator bookkeeping uses diversity=1 and resource=1 without measuring a model."""
    return float(scores["diversity"]) == 1.0 and float(scores["resource"]) == 1.0


def learning_claimed(store) -> bool:
    champion = store.champion()
    baseline = store.baseline()
    if champion is None or baseline is None:
        return False
    if champion["version_id"] == CHAMPION_ID:
        return False
    current = json.loads(champion["eval_scores_json"])
    reference = json.loads(baseline["eval_scores_json"])
    if _placeholder_pair(current) and _placeholder_pair(reference):
        return False
    return current["solve_rate"] > reference["solve_rate"] and all(
        current[metric] >= reference[metric] for metric in METRICS
    )


def adjudicate(store, challenger_id: str) -> str:
    champion = store.champion()
    challenger = store.get_model(challenger_id)
    if champion is None or challenger is None:
        raise LearnError("champion and challenger must both exist")
    if challenger["role"] not in {"challenger", "champion"}:
        raise LearnError("version is not a challenger")
    current = json.loads(champion["eval_scores_json"])
    proposed = json.loads(challenger["eval_scores_json"])
    regresses = any(proposed[metric] < current[metric] for metric in METRICS)
    improves = proposed["solve_rate"] > current["solve_rate"]
    if regresses or not improves:
        store.set_model_role(challenger_id, "retired")
        return "rolled_back"
    store.set_model_role(champion["version_id"], "retired")
    store.set_model_role(challenger_id, "champion")
    return "promoted"


def select_training_rows(store, run_id: str, *, cap: int = DESCENDANT_CAP) -> list:
    """Lean-validated proved/refuted rows only. Held-out hashes are excluded."""
    kept = []
    per_ancestor = {}
    for candidate in store.list_candidates(run_id):
        if candidate["held_out"] or candidate["structural_hash"] in HELD_OUT_HASHES:
            continue
        if candidate["current_status"] not in {"proved", "refuted"}:
            continue
        validations = store.list_validations(candidate["id"])
        if candidate["current_status"] == "proved":
            if not any(
                item["accepted"] and item["validation_type"] == "proof" for item in validations
            ):
                continue
        else:
            certificates = store.list_counterexamples(candidate["id"])
            if not any(item["lean_certificate_id"] for item in certificates):
                continue
            if not any(
                item["accepted"] and item["validation_type"] == "counterexample"
                for item in validations
            ):
                continue
        ancestor = candidate["ancestor_stable_id"]
        if ancestor:
            used = per_ancestor.get(ancestor, 0)
            if used >= cap:
                continue
            per_ancestor[ancestor] = used + 1
        kept.append(candidate)
    return _balance(kept)


def _practice_level(row) -> int:
    """Earlier level named on a review row, otherwise the row's own level."""
    raw = row["provenance"]
    try:
        payload = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict) and payload.get("review") is True:
        source = payload.get("source_level")
        if isinstance(source, int) and not isinstance(source, bool):
            return source
    return int(row["curriculum_level"])


def _difficulty_band(ast_size: int) -> str:
    if ast_size <= 2:
        return "small"
    if ast_size <= 6:
        return "mid"
    return "large"


def _balance(rows: list) -> list:
    buckets = {}
    for row in rows:
        band = _difficulty_band(int(row["ast_size"]))
        buckets.setdefault(
            (_practice_level(row), row["family"], row["current_status"], band),
            [],
        ).append(row)
    ordered = []
    keys = sorted(buckets)
    while any(buckets.values()):
        for key in keys:
            if buckets[key]:
                ordered.append(buckets[key].pop(0))
    return ordered
