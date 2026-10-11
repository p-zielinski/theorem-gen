"""Bounded job queue with leases. Downstream validation outranks new proposals."""

from __future__ import annotations

import json

from theorem_gen.learn.errors import Backpressure, LearnError

PRIORITY = {
    "lean_validate": 100,
    "counterexample_search": 80,
    "prove_alternate_or_critique": 60,
    "prove_primary": 50,
    "propose": 10,
}

INFERENCE_JOBS = ("propose", "prove_primary", "prove_alternate_or_critique")
LEAN_JOBS = ("lean_validate", "counterexample_search")


class JobQueue:
    def __init__(self, store, *, high_water: int = 128, lease_ttl_s: float = 30.0) -> None:
        if isinstance(high_water, bool) or not isinstance(high_water, int) or high_water < 1:
            raise LearnError("high_water must be a positive int")
        if isinstance(lease_ttl_s, bool) or not isinstance(lease_ttl_s, (int, float)) or lease_ttl_s <= 0:
            raise LearnError("lease_ttl_s must be positive")
        self.store = store
        self.high_water = high_water
        self.lease_ttl_s = float(lease_ttl_s)

    def enqueue(self, run_id: str, job_type: str, *, payload: dict, idempotency_key: str) -> dict:
        if job_type not in PRIORITY:
            raise LearnError(f"unknown job type: {job_type}")
        existing = self.store._one(
            "SELECT * FROM queue_jobs WHERE idempotency_key=?",
            (idempotency_key,),
        )
        if existing is not None:
            return existing
        depth = self.occupancy(run_id, job_type)
        if depth >= self.high_water:
            raise Backpressure(job_type)
        now = self.store.now()
        with self.store.transaction():
            self.store.conn.execute(
                """
                INSERT INTO queue_jobs (
                  run_id, job_type, priority, state, payload_json, lease_owner,
                  lease_expiry, heartbeat_at, retry_count, idempotency_key,
                  created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, NULL, NULL, NULL, 0, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    run_id,
                    job_type,
                    PRIORITY[job_type],
                    json.dumps(payload, sort_keys=True),
                    idempotency_key,
                    now,
                    now,
                ),
            )
        return self.store._one(
            "SELECT * FROM queue_jobs WHERE idempotency_key=?",
            (idempotency_key,),
        )

    def occupancy(self, run_id: str, job_type: str) -> int:
        return self.store.count_where(
            """
            SELECT COUNT(*) FROM queue_jobs
            WHERE run_id=? AND job_type=? AND state IN ('queued', 'leased')
            """,
            (run_id, job_type),
        )

    def depth(self, run_id: str, kinds=None) -> int:
        if kinds is None:
            return self.store.count_where(
                "SELECT COUNT(*) FROM queue_jobs WHERE run_id=? AND state='queued'",
                (run_id,),
            )
        marks = tuple(kinds)
        placeholders = ", ".join("?" for _ in marks)
        return self.store.count_where(
            f"""
            SELECT COUNT(*) FROM queue_jobs
            WHERE run_id=? AND state='queued' AND job_type IN ({placeholders})
            """,
            (run_id,) + marks,
        )

    def depths(self, run_id: str) -> dict:
        rows = self.store._all(
            """
            SELECT job_type, state, COUNT(*) AS n
            FROM queue_jobs
            WHERE run_id=?
            GROUP BY job_type, state
            """,
            (run_id,),
        )
        found = {job_type: {"queued": 0, "leased": 0, "done": 0, "failed": 0} for job_type in PRIORITY}
        for row in rows:
            found[row["job_type"]][row["state"]] = row["n"]
        return found

    def dequeue(self, run_id: str, owner: str, kinds, hooks) -> dict:
        marks = tuple(kinds)
        placeholders = ", ".join("?" for _ in marks)
        with self.store.transaction():
            row = self.store._one(
                f"""
                SELECT * FROM queue_jobs
                WHERE run_id=? AND state='queued' AND job_type IN ({placeholders})
                ORDER BY priority DESC, id ASC
                LIMIT 1
                """,
                (run_id,) + marks,
            )
            if row is None:
                return None
            hooks.hit("after_dequeue_before_lease")
            expiry = f"{self.store.clock.time() + self.lease_ttl_s:.6f}"
            self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='leased', lease_owner=?, lease_expiry=?, updated_at=?
                WHERE id=?
                """,
                (owner, expiry, self.store.now(), row["id"]),
            )
            row["state"] = "leased"
            row["lease_owner"] = owner
            row["lease_expiry"] = expiry
            return row

    def complete(self, job: dict) -> None:
        with self.store.transaction():
            cursor = self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='done', lease_owner=NULL, lease_expiry=NULL, updated_at=?
                WHERE id=? AND state='leased' AND lease_owner=?
                """,
                (self.store.now(), job["id"], job["lease_owner"]),
            )
            if cursor.rowcount != 1:
                raise LearnError("job lease was lost before commit")

    def fail(self, job: dict) -> None:
        with self.store.transaction():
            self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='failed', lease_owner=NULL, lease_expiry=NULL, updated_at=?
                WHERE id=? AND state='leased'
                """,
                (self.store.now(), job["id"]),
            )

    def release_job(self, job: dict) -> None:
        with self.store.transaction():
            self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='queued', lease_owner=NULL, lease_expiry=NULL, updated_at=?
                WHERE id=? AND state='leased'
                """,
                (self.store.now(), job["id"]),
            )

    def release_for_retry(self, job: dict) -> None:
        with self.store.transaction():
            cursor = self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='queued', lease_owner=NULL, lease_expiry=NULL,
                    retry_count=retry_count+1, updated_at=?
                WHERE id=? AND state='leased'
                """,
                (self.store.now(), job["id"]),
            )
            if cursor.rowcount != 1:
                raise LearnError("job lease was lost before retry")

    def release_all(self, run_id: str) -> None:
        with self.store.transaction():
            self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='queued', lease_owner=NULL, lease_expiry=NULL, updated_at=?
                WHERE run_id=? AND state='leased'
                """,
                (self.store.now(), run_id),
            )

    def reclaim_abandoned(self, run_id: str) -> int:
        with self.store.transaction():
            cursor = self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='queued', lease_owner=NULL, lease_expiry=NULL,
                    heartbeat_at=NULL, retry_count=retry_count+1, updated_at=?
                WHERE run_id=? AND state='leased'
                """,
                (self.store.now(), run_id),
            )
            return cursor.rowcount

    def reclaim_expired(self, run_id: str, now: float) -> int:
        with self.store.transaction():
            cursor = self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='queued', lease_owner=NULL, lease_expiry=NULL,
                    heartbeat_at=NULL, retry_count=retry_count+1, updated_at=?
                WHERE run_id=? AND state='leased'
                  AND lease_expiry IS NOT NULL
                  AND CAST(lease_expiry AS REAL) <= ?
                """,
                (self.store.now(), run_id, now),
            )
            return cursor.rowcount

    def heartbeat(self, job_id: int, owner: str) -> bool:
        expiry = f"{self.store.clock.time() + self.lease_ttl_s:.6f}"
        with self.store.transaction():
            cursor = self.store.conn.execute(
                """
                UPDATE queue_jobs
                SET lease_expiry=?, heartbeat_at=?, updated_at=?
                WHERE id=? AND state='leased' AND lease_owner=?
                  AND (lease_expiry IS NULL OR CAST(lease_expiry AS REAL) > ?)
                """,
                (
                    expiry,
                    self.store.now(),
                    self.store.now(),
                    job_id,
                    owner,
                    self.store.clock.time(),
                ),
            )
            return cursor.rowcount == 1
