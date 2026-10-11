"""SQLite store. Outcome columns are rewritten only by derive_outcome."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from theorem_gen.learn.classify import ValidationView, derive_outcome
from theorem_gen.learn.clock import Clock
from theorem_gen.learn.curriculum import level_is_justified
from theorem_gen.learn.errors import LearnError
from theorem_gen.learn.schema import MIGRATIONS, migration_sql

_RUN_FIELDS = {
    "status",
    "curriculum_level",
    "model_version",
    "checkpoint_window",
    "promoted_in_window",
    "advancement_frozen",
    "held_out_baseline",
    "held_out_latest",
}


class Store:
    def __init__(self, path, clock=None) -> None:
        self.path = Path(path)
        self.clock = Clock() if clock is None else clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self._txn = False
        self._apply_pragmas()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _apply_pragmas(self) -> None:
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def now(self) -> str:
        return f"{self.clock.time():.6f}"

    @contextmanager
    def transaction(self):
        if self._txn:
            yield self.conn
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._txn = True
        try:
            yield self.conn
            self.conn.execute("COMMIT")
        except Exception:
            if self._txn:
                self.conn.execute("ROLLBACK")
            raise
        finally:
            self._txn = False

    def migrate(self) -> None:
        applied = self._applied_versions()
        for version, name, filename in MIGRATIONS:
            if version in applied:
                continue
            self.conn.executescript(migration_sql(filename))
            self._apply_pragmas()
            self.conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, self.now()),
            )

    def _applied_versions(self) -> set:
        try:
            rows = self.conn.execute("SELECT version FROM schema_migrations").fetchall()
        except sqlite3.OperationalError:
            return set()
        return {row["version"] for row in rows}

    def integrity(self) -> str:
        row = self.conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            return "integrity_check failed" if row is None else str(row[0])
        foreign = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            return "foreign_key_check failed"
        return "ok"

    def create_run(
        self,
        run_id: str,
        *,
        seed: int,
        config: dict,
        curriculum_level: int = 1,
    ) -> dict:
        if not isinstance(run_id, str) or not run_id:
            raise LearnError("run_id must be a non-empty string")
        if curriculum_level != 1:
            raise LearnError("a new run starts at curriculum level 1")
        now = self.now()
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO runs (
                  run_id, status, seed, config_json, curriculum_level, model_version,
                  checkpoint_window, promoted_in_window, advancement_frozen,
                  held_out_baseline, held_out_latest, created_at, updated_at
                ) VALUES (?, 'created', ?, ?, ?, NULL, 0, 0, 0, NULL, NULL, ?, ?)
                """,
                (run_id, seed, json.dumps(config, sort_keys=True), curriculum_level, now, now),
            )
            self._append_event(run_id, "run_created", {"curriculum_level": curriculum_level})
        return self.get_run(run_id)

    def get_run(self, run_id: str):
        return self._one("SELECT * FROM runs WHERE run_id=?", (run_id,))

    def update_run(self, run_id: str, **fields) -> None:
        unknown = set(fields) - _RUN_FIELDS
        if unknown:
            raise LearnError("unknown run field: " + ", ".join(sorted(unknown)))
        if not fields:
            return
        fields = dict(fields)
        if "curriculum_level" in fields and not level_is_justified(
            self, run_id, int(fields["curriculum_level"])
        ):
            raise LearnError("curriculum level is not justified by passed gates")
        fields["updated_at"] = self.now()
        assignments = ", ".join(f"{key}=?" for key in fields)
        with self.transaction():
            self.conn.execute(
                f"UPDATE runs SET {assignments} WHERE run_id=?",
                tuple(fields.values()) + (run_id,),
            )

    def upsert_candidate(self, **fields) -> dict:
        existing = self._one(
            "SELECT * FROM candidates WHERE stable_id=?",
            (fields["stable_id"],),
        )
        if existing is not None:
            return existing
        now = self.now()
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO candidates (
                  stable_id, run_id, canonical_ast_json, structural_hash, kind,
                  provenance, current_status, curriculum_level, ancestor_stable_id,
                  family, ast_size, depth, proof_method, dependency_depth, held_out,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["stable_id"],
                    fields["run_id"],
                    fields["canonical_ast_json"],
                    fields["structural_hash"],
                    fields["kind"],
                    fields["provenance"],
                    fields.get("current_status", "unresolved"),
                    fields["curriculum_level"],
                    fields.get("ancestor_stable_id"),
                    fields.get("family", ""),
                    fields.get("ast_size", 0),
                    fields.get("depth", 0),
                    fields.get("proof_method", ""),
                    fields.get("dependency_depth", 0),
                    1 if fields.get("held_out") else 0,
                    now,
                    now,
                ),
            )
        return self._one("SELECT * FROM candidates WHERE stable_id=?", (fields["stable_id"],))

    def get_candidate(self, candidate_id: int):
        return self._one("SELECT * FROM candidates WHERE id=?", (candidate_id,))

    def get_by_stable(self, stable_id: str):
        return self._one("SELECT * FROM candidates WHERE stable_id=?", (stable_id,))

    def list_candidates(self, run_id: str) -> list:
        return self._all(
            "SELECT * FROM candidates WHERE run_id=? ORDER BY id",
            (run_id,),
        )

    def candidates_for_level(self, run_id: str, level: int) -> list:
        return self._all(
            """
            SELECT * FROM candidates
            WHERE run_id=? AND curriculum_level=?
            ORDER BY id
            """,
            (run_id, level),
        )

    def insert_attempt(self, **fields) -> dict:
        existing = self._idempotent_row("attempts", fields["idempotency_key"], fields["candidate_id"])
        if existing is not None:
            return existing
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO attempts (
                  candidate_id, role, model_version, prompt_hash, raw_response,
                  proof_artifact, critique_artifact, idempotency_key, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    fields["candidate_id"],
                    fields["role"],
                    fields.get("model_version"),
                    fields["prompt_hash"],
                    fields["raw_response"],
                    fields.get("proof_artifact"),
                    fields.get("critique_artifact"),
                    fields["idempotency_key"],
                    fields["duration_ms"],
                    self.now(),
                ),
            )
        return self._idempotent_row("attempts", fields["idempotency_key"], fields["candidate_id"])

    def list_attempts(self, candidate_id: int) -> list:
        return self._all(
            "SELECT * FROM attempts WHERE candidate_id=? ORDER BY id",
            (candidate_id,),
        )

    def attempt_responses(self, run_id: str) -> list:
        rows = self._all(
            """
            SELECT attempts.raw_response
            FROM attempts
            JOIN candidates ON candidates.id = attempts.candidate_id
            WHERE candidates.run_id=?
            ORDER BY attempts.id
            """,
            (run_id,),
        )
        return [row["raw_response"] for row in rows]

    def insert_validation(self, **fields) -> dict:
        existing = self._idempotent_row(
            "validations", fields["idempotency_key"], fields["candidate_id"]
        )
        if existing is not None:
            return existing
        with self.transaction():
            cursor = self.conn.execute(
                """
                INSERT INTO validations (
                  candidate_id, attempt_id, lean_version, toolchain_hash, validation_type,
                  result, accepted, stdout, stderr, message, failure_class,
                  idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    fields["candidate_id"],
                    fields.get("attempt_id"),
                    fields["lean_version"],
                    fields["toolchain_hash"],
                    fields["validation_type"],
                    fields["result"],
                    1 if fields["accepted"] else 0,
                    fields.get("stdout", ""),
                    fields.get("stderr", ""),
                    fields.get("message", ""),
                    fields.get("failure_class"),
                    fields["idempotency_key"],
                    self.now(),
                ),
            )
            if cursor.rowcount == 1:
                self.recompute(fields["candidate_id"])
        return self._idempotent_row(
            "validations", fields["idempotency_key"], fields["candidate_id"]
        )

    def list_validations(self, candidate_id: int) -> list:
        return self._all(
            "SELECT * FROM validations WHERE candidate_id=? ORDER BY id",
            (candidate_id,),
        )

    def validations_for_level(self, run_id: str, level: int) -> list:
        return self._all(
            """
            SELECT validations.*
            FROM validations
            JOIN candidates ON candidates.id = validations.candidate_id
            WHERE candidates.run_id=? AND candidates.curriculum_level=?
            ORDER BY validations.id
            """,
            (run_id, level),
        )

    def recompute(self, candidate_id: int) -> str:
        """Set current_status from accepted validations. Attempts are not read."""
        rows = self.list_validations(candidate_id)
        views = [
            ValidationView(
                row["validation_type"],
                row["result"],
                bool(row["accepted"]),
                row["failure_class"],
            )
            for row in rows
        ]
        status = derive_outcome(views)
        current = self.get_candidate(candidate_id)
        if current is None:
            raise LearnError(f"missing candidate {candidate_id}")
        if current["current_status"] != status:
            with self.transaction():
                self.conn.execute(
                    "UPDATE candidates SET current_status=?, updated_at=? WHERE id=?",
                    (status, self.now(), candidate_id),
                )
                self._append_event(
                    current["run_id"],
                    "status_derived",
                    {"candidate_id": candidate_id, "status": status},
                )
        return status

    def insert_counterexample(self, **fields) -> dict:
        with self.transaction():
            cursor = self.conn.execute(
                """
                INSERT INTO counterexamples (
                  candidate_id, assignment_json, instantiated_prop,
                  lean_certificate_id, proposed_by, created_at
                ) VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (
                    fields["candidate_id"],
                    fields["assignment_json"],
                    fields["instantiated_prop"],
                    fields["proposed_by"],
                    self.now(),
                ),
            )
            row_id = cursor.lastrowid
        return self._one("SELECT * FROM counterexamples WHERE id=?", (row_id,))

    def set_certificate(self, counterexample_id: int, validation_id: int) -> None:
        with self.transaction():
            cursor = self.conn.execute(
                """
                UPDATE counterexamples
                SET lean_certificate_id=?
                WHERE id=? AND lean_certificate_id IS NULL
                """,
                (validation_id, counterexample_id),
            )
            if cursor.rowcount != 1:
                raise LearnError("certificate was not attached")

    def list_counterexamples(self, candidate_id: int) -> list:
        return self._all(
            "SELECT * FROM counterexamples WHERE candidate_id=? ORDER BY id",
            (candidate_id,),
        )

    def insert_dependency(self, from_id: int, to_id: int, relation: str) -> None:
        with self.transaction():
            self.conn.execute(
                """
                INSERT OR IGNORE INTO dependencies (from_id, to_id, relation)
                VALUES (?, ?, ?)
                """,
                (from_id, to_id, relation),
            )

    def list_dependencies(self, from_id: int) -> list:
        return self._all(
            "SELECT * FROM dependencies WHERE from_id=? ORDER BY id",
            (from_id,),
        )

    def append_event(self, run_id: str, kind: str, payload: dict) -> int:
        with self.transaction():
            return self._append_event(run_id, kind, payload)

    def _append_event(self, run_id: str, kind: str, payload: dict) -> int:
        body = json.dumps(payload, sort_keys=True)
        now = self.now()
        for _ in range(8):
            seq = self.event_cursor(run_id) + 1
            cursor = self.conn.execute(
                """
                INSERT INTO events (run_id, seq, kind, payload_json, created_at)
                SELECT ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                  SELECT 1 FROM events WHERE run_id=? AND seq=?
                )
                """,
                (run_id, seq, kind, body, now, run_id, seq),
            )
            if cursor.rowcount == 1:
                return seq
        raise LearnError("could not append event")

    def event_cursor(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM events WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return int(row["seq"])

    def list_events(self, run_id: str) -> list:
        return self._all(
            "SELECT * FROM events WHERE run_id=? ORDER BY seq",
            (run_id,),
        )

    def upsert_window(self, **fields) -> None:
        now = self.now()
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO curriculum_progress (
                  run_id, level, window_index, metrics_json, gate_status,
                  evaluated_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id, level, window_index) DO UPDATE SET
                  metrics_json=excluded.metrics_json,
                  gate_status=excluded.gate_status,
                  evaluated_count=excluded.evaluated_count
                """,
                (
                    fields["run_id"],
                    fields["level"],
                    fields["window_index"],
                    fields["metrics_json"],
                    fields["gate_status"],
                    fields["evaluated_count"],
                    now,
                ),
            )

    def passed_gate(self, run_id: str, level: int) -> bool:
        row = self._one(
            """
            SELECT 1 AS ok FROM curriculum_progress
            WHERE run_id=? AND level=? AND window_index=-1 AND gate_status='passed'
            LIMIT 1
            """,
            (run_id, level),
        )
        return row is not None

    def windows_for(self, run_id: str, level: int) -> list:
        return self._all(
            """
            SELECT * FROM curriculum_progress
            WHERE run_id=? AND level=?
            ORDER BY window_index
            """,
            (run_id, level),
        )

    def insert_model(self, **fields) -> dict:
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO model_versions (
                  version_id, path, weight_hash, adapter_hash, eval_scores_json, role, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["version_id"],
                    fields.get("path", ""),
                    fields.get("weight_hash", ""),
                    fields.get("adapter_hash", ""),
                    json.dumps(fields["scores"], sort_keys=True),
                    fields["role"],
                    self.now(),
                ),
            )
        return self.get_model(fields["version_id"])

    def get_model(self, version_id: str):
        return self._one(
            "SELECT * FROM model_versions WHERE version_id=?",
            (version_id,),
        )

    def set_model_role(self, version_id: str, role: str) -> None:
        with self.transaction():
            self.conn.execute(
                "UPDATE model_versions SET role=? WHERE version_id=?",
                (role, version_id),
            )

    def champion(self):
        return self._one(
            "SELECT * FROM model_versions WHERE role='champion' ORDER BY created_at LIMIT 1"
        )

    def baseline(self):
        return self._one(
            "SELECT * FROM model_versions WHERE role='baseline' ORDER BY created_at LIMIT 1"
        )

    def next_checkpoint_seq(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS seq FROM checkpoints WHERE run_id=?",
            (run_id,),
        ).fetchone()
        return int(row["seq"]) + 1

    def insert_checkpoint(self, **fields) -> dict:
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO checkpoints (
                  run_id, seq, event_cursor, scheduler_state_json, rng_state,
                  curriculum_state_json, artifact_hashes_json, known_good, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    fields["run_id"],
                    fields["seq"],
                    fields["event_cursor"],
                    fields["scheduler_state_json"],
                    fields["rng_state"],
                    fields["curriculum_state_json"],
                    fields["artifact_hashes_json"],
                    fields["reason"],
                    self.now(),
                ),
            )
        return self.get_checkpoint(fields["run_id"], fields["seq"])

    def get_checkpoint(self, run_id: str, seq: int):
        return self._one(
            "SELECT * FROM checkpoints WHERE run_id=? AND seq=?",
            (run_id, seq),
        )

    def latest_known_good(self, run_id: str):
        return self._one(
            """
            SELECT * FROM checkpoints
            WHERE run_id=? AND known_good=1
            ORDER BY seq DESC
            LIMIT 1
            """,
            (run_id,),
        )

    def attempt_cursor(self, run_id: str) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(MAX(attempts.id), 0) AS n
            FROM attempts
            JOIN candidates ON candidates.id = attempts.candidate_id
            WHERE candidates.run_id=?
            """,
            (run_id,),
        ).fetchone()
        return int(row["n"])

    def count_descendants(self, ancestor_stable_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM candidates WHERE ancestor_stable_id=?",
            (ancestor_stable_id,),
        ).fetchone()
        return int(row["n"])

    def count_where(self, sql: str, params=()) -> int:
        row = self.conn.execute(sql, params).fetchone()
        return int(row[0])

    def _idempotent_row(self, table: str, key: str, candidate_id: int):
        if table not in {"attempts", "validations"}:
            raise LearnError(f"unknown idempotent table: {table}")
        row = self._one(f"SELECT * FROM {table} WHERE idempotency_key=?", (key,))
        if row is None:
            return None
        if row["candidate_id"] != candidate_id:
            raise LearnError("idempotency key belongs to another candidate")
        return row

    def _one(self, sql: str, params=()):
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(row)

    def _all(self, sql: str, params=()) -> list:
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]
