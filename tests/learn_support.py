"""Helpers for the continuous-loop tests. Not collected by unittest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from theorem_gen.learn.classify import ValidationView, derive_outcome
from theorem_gen.learn.clock import ManualClock
from theorem_gen.learn.engine import Engine
from theorem_gen.learn.store import Store

FAMILIES = ("add_zero", "eval_eq", "le_refl", "mul_one")
METHODS = ("rfl", "decide")


def accepting_runner(cmd, timeout, cwd, env):
    source = Path(cmd[-1]).read_text(encoding="utf-8")
    if re.search(r"\b(sorry|axiom|opaque|unsafe)\b", source):
        return 1, "", "unexpected token\n"
    if "Not " in source or "¬" in source:
        return 0, "", ""
    if re.search(r"\b1 = 0\b", source):
        return 1, "", "unsolved goals\n"
    return 0, "", ""


def make_engine(directory, **kwargs) -> Engine:
    clock = kwargs.pop("clock", None) or ManualClock()
    store = Store(Path(directory) / "learn.sqlite", clock=clock)
    store.migrate()
    options = dict(
        run_id="run-1",
        seed=1,
        batch_count=2,
        max_steps=20,
        runner=accepting_runner,
    )
    options.update(kwargs)
    return Engine(store, **options)


def seed_proved_cohort(
    store,
    run_id: str,
    level: int,
    count: int,
    *,
    identical: bool = False,
    start: int = 0,
    generator: str = "cohort",
    kind: str = "theorem",
) -> None:
    outcome = derive_outcome([ValidationView("proof", "accepted", True, None)])
    if outcome != "proved":
        raise AssertionError(outcome)
    now = store.now()
    with store.transaction():
        candidate_rows = []
        for index in range(start, start + count):
            stable = f"cohort-{level}-{index}"
            material = "same-statement" if identical else stable
            structural = hashlib.sha256(material.encode("utf-8")).hexdigest()
            candidate_rows.append(
                (
                    stable,
                    run_id,
                    "{}",
                    structural,
                    kind,
                    json.dumps({"generator": generator}, sort_keys=True),
                    "unresolved",
                    level,
                    None,
                    FAMILIES[index % len(FAMILIES)],
                    3 + (index % 4),
                    2,
                    METHODS[index % len(METHODS)],
                    0,
                    0,
                    now,
                    now,
                )
            )
        store.conn.executemany(
            """
            INSERT INTO candidates (
              stable_id, run_id, canonical_ast_json, structural_hash, kind, provenance,
              current_status, curriculum_level, ancestor_stable_id, family, ast_size, depth,
              proof_method, dependency_depth, held_out, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            candidate_rows,
        )
        inserted = {row[0] for row in candidate_rows}
        found = [
            row
            for row in store.conn.execute(
                """
                SELECT id, stable_id FROM candidates
                WHERE run_id=? AND curriculum_level=? AND stable_id LIKE ?
                ORDER BY id
                """,
                (run_id, level, f"cohort-{level}-%"),
            )
            if row["stable_id"] in inserted
        ]
        validations = [
            (
                row["id"],
                None,
                "fixture",
                "fixture",
                "proof",
                "accepted",
                1,
                "",
                "",
                "cohort fixture derived as an accepted proof",
                None,
                f"cohort-val-{row['stable_id']}",
                now,
            )
            for row in found
        ]
        store.conn.executemany(
            """
            INSERT INTO validations (
              candidate_id, attempt_id, lean_version, toolchain_hash, validation_type,
              result, accepted, stdout, stderr, message, failure_class, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            validations,
        )
        store.conn.execute(
            """
            UPDATE candidates
            SET current_status='proved', updated_at=?
            WHERE run_id=? AND curriculum_level=? AND stable_id LIKE ?
            """,
            (now, run_id, level, f"cohort-{level}-%"),
        )
