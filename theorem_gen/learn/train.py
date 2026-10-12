"""Online weight steps for Lean-labeled rows.

The vector is a linear model persisted in SQLite. It is not a champion and it
does not satisfy `learning_claimed`. Held-out rows never enter the queue.
"""

from __future__ import annotations

import hashlib
import json
import math

from theorem_gen.learn.heldout import HELD_OUT_HASHES
from theorem_gen.learn.policy import DESCENDANT_CAP

WIDTH = 6
LEARNING_RATE = 0.05
CATCHUP_LIMIT = 64
DRAIN_LIMIT = 32


def default_lean_workers() -> int:
    """Two Lean processes, so the 50M transformer keeps room on this machine."""
    return 2


def zeros() -> list:
    return [0.0] * WIDTH


def features(row) -> list:
    return [
        1.0,
        int(row["ast_size"]) / 16.0,
        int(row["depth"]) / 8.0,
        _unit(row["family"] or ""),
        _unit(row["proof_method"] or ""),
        int(row["curriculum_level"]) / 7.0,
    ]


def sgd(vector, row_features, label: float, lr: float = LEARNING_RATE) -> list:
    if len(vector) != WIDTH or len(row_features) != WIDTH:
        raise ValueError("weight vector width does not match features")
    score = sum(weight * value for weight, value in zip(vector, row_features))
    score = max(-20.0, min(20.0, score))
    prediction = 1.0 / (1.0 + math.exp(-score))
    error = prediction - float(label)
    return [weight - lr * error * value for weight, value in zip(vector, row_features)]


def eligible(candidate, validations, certificates, *, trained_with_ancestor: int) -> bool:
    if candidate["held_out"] or candidate["structural_hash"] in HELD_OUT_HASHES:
        return False
    status = candidate["current_status"]
    if status == "proved":
        ok = any(item["accepted"] and item["validation_type"] == "proof" for item in validations)
    elif status == "refuted":
        ok = any(item["lean_certificate_id"] for item in certificates) and any(
            item["accepted"] and item["validation_type"] == "counterexample" for item in validations
        )
    else:
        return False
    if not ok:
        return False
    ancestor = candidate["ancestor_stable_id"]
    if ancestor and trained_with_ancestor >= DESCENDANT_CAP:
        return False
    return True


def snapshot(store, run_id: str) -> dict:
    row = store._one(
        "SELECT step, lean_workers, cursor_id FROM online_weights WHERE run_id=?",
        (run_id,),
    )
    queued = store.count_where(
        "SELECT COUNT(*) FROM train_items WHERE run_id=? AND state='queued'",
        (run_id,),
    )
    if row is None:
        return {"weight_step": 0, "lean_workers": None, "train_queued": queued, "cursor_id": 0}
    return {
        "weight_step": int(row["step"]),
        "lean_workers": int(row["lean_workers"]),
        "train_queued": queued,
        "cursor_id": int(row["cursor_id"]),
    }


def remember_workers(store, run_id: str, lean_workers: int) -> None:
    vector, step, cursor, _workers = _load(store, run_id)
    _save(store, run_id, vector, step, cursor, lean_workers)


def enqueue(store, run_id: str, candidate) -> bool:
    """Queue one labeled row. Safe inside an open store transaction."""
    if candidate is None or candidate["run_id"] != run_id:
        return False
    if candidate["held_out"] or candidate["structural_hash"] in HELD_OUT_HASHES:
        return False
    if candidate["current_status"] not in {"proved", "refuted"}:
        return False
    validations = store.list_validations(candidate["id"])
    certificates = store.list_counterexamples(candidate["id"])
    trained = _trained_with_ancestor(store, run_id, candidate["ancestor_stable_id"])
    if not eligible(
        candidate,
        validations,
        certificates,
        trained_with_ancestor=trained,
    ):
        return False
    now = store.now()
    cursor = store.conn.execute(
        """
        INSERT INTO train_items (
          run_id, candidate_id, label, state, idempotency_key, created_at, updated_at
        ) VALUES (?, ?, ?, 'queued', ?, ?, ?)
        ON CONFLICT(idempotency_key) DO NOTHING
        """,
        (
            run_id,
            candidate["id"],
            candidate["current_status"],
            f"{run_id}:train:{candidate['id']}",
            now,
            now,
        ),
    )
    return cursor.rowcount == 1


def progress(
    store,
    run_id: str,
    *,
    lean_workers: int = 1,
    catchup_limit: int = CATCHUP_LIMIT,
    drain_limit: int = DRAIN_LIMIT,
) -> dict:
    """Catch up historical rows, then apply a bounded number of queued steps."""
    caught = _catchup(store, run_id, catchup_limit, lean_workers)
    drained = _drain(store, run_id, drain_limit, lean_workers)
    info = snapshot(store, run_id)
    info["caught"] = caught
    info["drained"] = drained
    return info


def _catchup(store, run_id: str, limit: int, lean_workers: int) -> int:
    _vector, _step, cursor, _workers = _load(store, run_id)
    rows = store._all(
        """
        SELECT * FROM candidates
        WHERE run_id=? AND id>?
        ORDER BY id
        LIMIT ?
        """,
        (run_id, cursor, limit),
    )
    if not rows:
        return 0
    last = int(rows[-1]["id"])
    with store.transaction():
        for row in rows:
            enqueue(store, run_id, row)
        vector, step, _cursor, _workers = _load(store, run_id)
        _save(store, run_id, vector, step, last, lean_workers)
    return len(rows)


def _drain(store, run_id: str, limit: int, lean_workers: int) -> int:
    rows = store._all(
        """
        SELECT
          train_items.id AS train_id,
          train_items.label AS train_label,
          candidates.ast_size AS ast_size,
          candidates.depth AS depth,
          candidates.family AS family,
          candidates.proof_method AS proof_method,
          candidates.curriculum_level AS curriculum_level
        FROM train_items
        JOIN candidates ON candidates.id = train_items.candidate_id
        WHERE train_items.run_id=? AND train_items.state='queued'
        ORDER BY train_items.id
        LIMIT ?
        """,
        (run_id, limit),
    )
    if not rows:
        return 0
    vector, step, cursor, _workers = _load(store, run_id)
    now = store.now()
    with store.transaction():
        for row in rows:
            label = 1.0 if row["train_label"] == "proved" else 0.0
            vector = sgd(vector, features(row), label)
            store.conn.execute(
                """
                UPDATE train_items
                SET state='done', updated_at=?
                WHERE id=? AND state='queued'
                """,
                (now, row["train_id"]),
            )
        _save(store, run_id, vector, step + len(rows), cursor, lean_workers)
    return len(rows)


def _trained_with_ancestor(store, run_id: str, ancestor) -> int:
    if not ancestor:
        return 0
    return store.count_where(
        """
        SELECT COUNT(*)
        FROM train_items
        JOIN candidates ON candidates.id = train_items.candidate_id
        WHERE train_items.run_id=? AND candidates.ancestor_stable_id=?
        """,
        (run_id, ancestor),
    )


def _load(store, run_id: str):
    row = store._one("SELECT * FROM online_weights WHERE run_id=?", (run_id,))
    if row is None:
        return zeros(), 0, 0, None
    return json.loads(row["vector_json"]), int(row["step"]), int(row["cursor_id"]), int(row["lean_workers"])


def _save(store, run_id: str, vector, step: int, cursor: int, lean_workers: int) -> None:
    store.conn.execute(
        """
        INSERT INTO online_weights (
          run_id, step, vector_json, cursor_id, lean_workers, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
          step=excluded.step,
          vector_json=excluded.vector_json,
          cursor_id=excluded.cursor_id,
          lean_workers=excluded.lean_workers,
          updated_at=excluded.updated_at
        """,
        (
            run_id,
            int(step),
            json.dumps(vector),
            int(cursor),
            int(lean_workers),
            store.now(),
        ),
    )


def _unit(text: str) -> float:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:2], "big") / 65535.0
