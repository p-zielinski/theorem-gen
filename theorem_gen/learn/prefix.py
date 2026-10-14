"""The training cursor walks a closed prefix. An in-flight check is a stop, not a hole."""

from __future__ import annotations

# Proved sentences the first read has not reached. Above this, the generator
# opens no new batch. One batch may already be queued and waits with it.
MATERIAL_CAP = 128


def generator_waits(unread: int, cap: int = MATERIAL_CAP) -> bool:
    """True while new material is above the cap. At the cap, a batch may open."""
    return int(unread) > int(cap)


def _job_keys(run_id: str, stable_id: str) -> tuple:
    return (
        f"{run_id}:lean_validate:{stable_id}:proof",
        f"{run_id}:lean_validate:{stable_id}:check",
        f"{run_id}:cert:{stable_id}",
    )


def is_in_flight(conn, run_id: str, candidate) -> bool:
    """True while Lean has not finished this sentence. A stored verdict is not in flight."""
    if candidate["current_status"] != "unresolved":
        return False
    keys = _job_keys(run_id, candidate["stable_id"])
    marks = ",".join("?" for _ in keys)
    row = conn.execute(
        f"""
        SELECT 1 FROM queue_jobs
        WHERE state IN ('queued', 'leased') AND idempotency_key IN ({marks})
        LIMIT 1
        """,
        keys,
    ).fetchone()
    return row is not None


def blocking_id(conn, run_id: str, after: int):
    """Smallest id past `after` whose Lean check is still queued or leased."""
    row = conn.execute(
        """
        SELECT c.id AS id
        FROM candidates c
        WHERE c.run_id=? AND c.id>? AND c.current_status='unresolved'
          AND EXISTS (
            SELECT 1 FROM queue_jobs q
            WHERE q.state IN ('queued', 'leased')
              AND q.idempotency_key IN (
                c.run_id || ':lean_validate:' || c.stable_id || ':proof',
                c.run_id || ':lean_validate:' || c.stable_id || ':check',
                c.run_id || ':cert:' || c.stable_id
              )
          )
        ORDER BY c.id
        LIMIT 1
        """,
        (run_id, after),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"])


def unread_in_prefix(conn, run_id: str, after: int) -> int:
    """Proved sentences the cursor can read without crossing an open check."""
    block = blocking_id(conn, run_id, after)
    if block is None:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM candidates
            WHERE run_id=? AND id>? AND held_out=0 AND current_status='proved'
            """,
            (run_id, after),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM candidates
            WHERE run_id=? AND id>? AND id<? AND held_out=0 AND current_status='proved'
            """,
            (run_id, after, block),
        ).fetchone()
    return int(row["n"] or 0)
