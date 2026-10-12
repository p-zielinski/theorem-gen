"""Parallel Lean checks and the stoppable weight queue."""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for item in (str(ROOT), str(TESTS)):
    if item not in sys.path:
        sys.path.insert(0, item)

from learn_support import accepting_runner, make_engine
from theorem_gen.learn.heldout import HELD_OUT_HASHES
from theorem_gen.learn.train import eligible, progress, sgd, zeros


def _proof():
    return {"accepted": 1, "validation_type": "proof", "lean_certificate_id": None}


class WeightTests(unittest.TestCase):
    def test_a_proved_step_moves_the_bias(self):
        vector = sgd(zeros(), [1.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1.0)
        self.assertGreater(vector[0], 0.0)
        self.assertEqual(len(vector), 6)

    def test_held_out_unresolved_and_descendant_cap_are_skipped(self):
        base = {
            "held_out": 0,
            "structural_hash": "abc",
            "current_status": "proved",
            "ancestor_stable_id": None,
        }
        proof = _proof()
        self.assertTrue(eligible(base, [proof], [], trained_with_ancestor=0))
        self.assertFalse(eligible({**base, "held_out": 1}, [proof], [], trained_with_ancestor=0))
        held_out_hash = next(iter(HELD_OUT_HASHES))
        self.assertFalse(
            eligible(
                {**base, "structural_hash": held_out_hash},
                [proof],
                [],
                trained_with_ancestor=0,
            )
        )
        self.assertFalse(
            eligible({**base, "current_status": "unresolved"}, [proof], [], trained_with_ancestor=0)
        )
        capped = {**base, "ancestor_stable_id": "root"}
        self.assertFalse(eligible(capped, [proof], [], trained_with_ancestor=8))

    def test_queue_trains_once_and_survives_a_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            self._insert(engine, "ok", held_out=0, ancestor="root", count=9)
            self._insert(engine, "held", held_out=1, ancestor=None, count=1)
            first = progress(engine.store, "run-1", drain_limit=100, catchup_limit=100)
            self.assertEqual(first["drained"], 8)
            self.assertEqual(first["weight_step"], 8)
            self.assertEqual(first["train_queued"], 0)
            self.assertGreater(engine.status()["weight_step"], 0)
            self.assertFalse(engine.status()["learning"])
            second = progress(engine.store, "run-1", drain_limit=100, catchup_limit=100)
            self.assertEqual(second["drained"], 0)
            self.assertEqual(second["weight_step"], 8)
            held = engine.store._one(
                """
                SELECT COUNT(*) AS n
                FROM train_items
                JOIN candidates ON candidates.id = train_items.candidate_id
                WHERE candidates.stable_id LIKE 'held-%'
                """
            )
            self.assertEqual(int(held["n"]), 0)

    def test_parallel_lean_checks_overlap(self):
        state = {"current": 0, "peak": 0}
        lock = threading.Lock()
        gate = threading.Event()

        def runner(cmd, timeout, cwd, env):
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
                if state["current"] >= 2:
                    gate.set()
            self.assertTrue(gate.wait(3))
            with lock:
                state["current"] -= 1
            return accepting_runner(cmd, timeout, cwd, env)

        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(
                tmp,
                batch_count=4,
                max_steps=1,
                lean_workers=4,
                runner=runner,
            )
            engine.start()
            self.assertGreaterEqual(state["peak"], 2)
            self.assertGreater(engine.meter.lean_busy, 1)
            self.assertFalse(engine.status()["learning"])
            self.assertGreater(engine.status()["weight_step"], 0)

    def _insert(self, engine, prefix: str, *, held_out: int, ancestor, count: int) -> None:
        now = engine.store.now()
        for index in range(count):
            stable = f"{prefix}-{index}"
            engine.store.conn.execute(
                """
                INSERT INTO candidates (
                  stable_id, run_id, canonical_ast_json, structural_hash, kind, provenance,
                  current_status, curriculum_level, ancestor_stable_id, family, ast_size, depth,
                  proof_method, dependency_depth, held_out, created_at, updated_at
                ) VALUES (?, 'run-1', '{}', ?, 'theorem', '{}', 'unresolved', 1, ?, 'add_zero', 4, 2, 'rfl', 0, ?, ?, ?)
                """,
                (stable, f"hash-{stable}", ancestor, held_out, now, now),
            )
            candidate_id = engine.store.get_by_stable(stable)["id"]
            engine.store.conn.execute(
                """
                INSERT INTO validations (
                  candidate_id, attempt_id, lean_version, toolchain_hash, validation_type,
                  result, accepted, stdout, stderr, message, failure_class, idempotency_key, created_at
                ) VALUES (?, NULL, 'fixture', 'fixture', 'proof', 'accepted', 1, '', '', '', NULL, ?, ?)
                """,
                (candidate_id, f"val-{stable}", now),
            )
            engine.store.conn.execute(
                "UPDATE candidates SET current_status='proved', updated_at=? WHERE id=?",
                (now, candidate_id),
            )


if __name__ == "__main__":
    unittest.main()
