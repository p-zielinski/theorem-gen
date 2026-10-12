"""A second walk over sentences the forward cursor has already read.

Generator rows and model rows are the same list. The walk goes by id, upward,
and does not pass the forward cursor. The stored id is the last one included.
"""

from __future__ import annotations

from theorem_gen.learn.heldout import HELD_OUT_HASHES


def next_replay(conn, run_id: str, after: int, until: int, limit: int = 4) -> tuple:
    """Proved rows with `after < id <= until`, and the id to store.

    An empty page with id 0 means the next pass starts at the beginning.
    A hole that is not proved is passed. It does not end the page early.
    """
    if until <= after:
        return [], 0
    chosen = []
    cursor = after
    while len(chosen) < limit:
        row = conn.execute(
            """
            SELECT * FROM candidates
            WHERE run_id=? AND id>? AND id<=?
            ORDER BY id
            LIMIT 1
            """,
            (run_id, cursor, until),
        ).fetchone()
        if row is None:
            break
        cursor = int(row["id"])
        if int(row["held_out"]) or row["structural_hash"] in HELD_OUT_HASHES:
            continue
        if row["current_status"] != "proved":
            continue
        chosen.append(row)
    if not chosen and cursor == after:
        return [], 0
    return chosen, cursor
