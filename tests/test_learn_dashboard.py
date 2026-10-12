"""Effort grades and the read-only run summary."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for item in (str(ROOT), str(TESTS)):
    if item not in sys.path:
        sys.path.insert(0, item)

from learn_support import make_engine
from theorem_gen.learn.dashboard import attempt_trend, reading_eta, snapshot
from theorem_gen.learn.effort import effort_level, lean_time_band


class EffortTests(unittest.TestCase):
    def test_grades_follow_shape_and_proof_method(self):
        self.assertEqual(effort_level("decide", 3, 1), 1)
        self.assertEqual(effort_level("rfl", 4, 1), 2)
        self.assertEqual(effort_level("rfl", 9, 3), 3)
        self.assertEqual(effort_level("lemma", 5, 2), 3)
        self.assertEqual(effort_level("rewrite", 12, 4), 4)
        self.assertIsNone(effort_level("model", 40, 1))
        self.assertIsNone(effort_level("", 3, 1))

    def test_lean_time_bands(self):
        self.assertIsNone(lean_time_band(None))
        self.assertEqual(lean_time_band(40), "fast")
        self.assertEqual(lean_time_band(250), "normal")
        self.assertEqual(lean_time_band(900), "slow")
        self.assertEqual(lean_time_band(4000), "heavy")


class SnapshotTests(unittest.TestCase):
    def test_summary_counts_queues_and_effort_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            now = engine.store.now()
            engine.store.conn.execute(
                """
                INSERT INTO candidates (
                  stable_id, run_id, canonical_ast_json, structural_hash, kind, provenance,
                  current_status, curriculum_level, ancestor_stable_id, family, ast_size, depth,
                  proof_method, dependency_depth, held_out, created_at, updated_at
                ) VALUES ('t', 'run-1', '{}', 'h', 'theorem', '{"origin": "generator"}',
                  'unresolved', 1, NULL, 'eval_eq', 9, 3, 'rfl', 0, 0, ?, ?)
                """,
                (now, now),
            )
            candidate_id = engine.store.get_by_stable("t")["id"]
            engine.store.insert_validation(
                candidate_id=candidate_id,
                idempotency_key="val-t",
                lean_version="fixture",
                toolchain_hash="fixture",
                validation_type="proof",
                result="accepted",
                accepted=True,
                lean_ms=250,
            )
            info = snapshot(Path(tmp) / "learn.sqlite", "run-1", now=float(now) + 1)
            self.assertEqual(info["statuses"]["proved"], 1)
            self.assertEqual(info["effort"]["generator"]["3"]["proved"], 1)
            self.assertEqual(info["lean_bands"]["normal"], 1)
            self.assertEqual(info["recent_candidates"], 1)
            self.assertEqual(info["recent_validations"], 1)
            self.assertEqual(info["attempt_trend"]["direction"], "none")
            self.assertEqual(info["unread"], 1)
            self.assertEqual(info["study_total"], 1)
            self.assertEqual(info["updates_left"], 1)

    def test_unread_counts_proved_rows_past_the_read_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            now = engine.store.now()

            def add(stable_id, held_out, proved):
                engine.store.conn.execute(
                    """
                    INSERT INTO candidates (
                      stable_id, run_id, canonical_ast_json, structural_hash, kind, provenance,
                      current_status, curriculum_level, ancestor_stable_id, family, ast_size, depth,
                      proof_method, dependency_depth, held_out, created_at, updated_at
                    ) VALUES (?, 'run-1', '{}', ?, 'theorem', '{"origin": "generator"}',
                      'unresolved', 1, NULL, 'eval_eq', 4, 1, 'rfl', 0, ?, ?, ?)
                    """,
                    (stable_id, stable_id, held_out, now, now),
                )
                row_id = engine.store.get_by_stable(stable_id)["id"]
                if proved:
                    engine.store.insert_validation(
                        candidate_id=row_id,
                        idempotency_key="val-" + stable_id,
                        lean_version="fixture",
                        toolchain_hash="fixture",
                        validation_type="proof",
                        result="accepted",
                        accepted=True,
                    )
                return row_id

            first = add("seen", 0, True)
            add("later", 0, True)
            add("exam", 1, True)
            add("open", 0, False)
            engine.store.conn.execute(
                """
                INSERT INTO lm_state (
                  run_id, step, epoch, cursor_id, pass_cursor, sequences,
                  last_loss, hold, weak_streak, last_error, weights_path, updated_at
                ) VALUES ('run-1', 10, 0, ?, 0, 0, 1.0, 0, 0, NULL, 'weights', ?)
                """,
                (first, now),
            )
            info = snapshot(Path(tmp) / "learn.sqlite", "run-1", now=float(now) + 1)
            self.assertEqual(info["unread"], 1)
            self.assertEqual(info["study_total"], 2)
            self.assertEqual(info["updates_left"], 1)

    def test_attempt_windows_compare_the_last_two_ten_minute_spans(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            now = 1_700_000_000.0

            def add(disposition, age):
                engine.store.conn.execute(
                    """
                    INSERT INTO model_attempts (
                      run_id, equation, equation_hash, origin, disposition, candidate_id, created_at
                    ) VALUES ('run-1', ?, ?, 'model', ?, NULL, ?)
                    """,
                    (disposition, disposition + str(age), disposition, f"{now - age:.6f}"),
                )

            add("proved", 100)
            add("duplicate", 200)
            add("queued", 300)
            add("proved", 700)
            add("ill_formed", 800)
            add("refuted", 2000)
            info = snapshot(Path(tmp) / "learn.sqlite", "run-1", now=now)
            self.assertEqual(info["attempts"]["proved"], {"all": 2, "recent": 1, "previous": 1})
            self.assertEqual(info["attempts"]["duplicate"]["recent"], 1)
            self.assertEqual(info["attempts"]["queued"]["recent"], 1)
            self.assertEqual(info["attempts"]["refuted"], {"all": 1, "recent": 0, "previous": 0})
            self.assertEqual(info["attempt_trend"]["direction"], "same")
            self.assertEqual(info["attempt_trend"]["recent_done"], 2)
            self.assertEqual(info["attempt_trend"]["previous_done"], 2)


class ReadingEtaTests(unittest.TestCase):
    def test_eta_uses_the_net_shrink_of_the_unread_pile(self):
        self.assertEqual(reading_eta(120, 240, 10), 10)
        self.assertEqual(reading_eta(0, 10, 5), 0)
        self.assertIsNone(reading_eta(10, 10, 5))
        self.assertIsNone(reading_eta(12, 10, 5))
        self.assertIsNone(reading_eta(10, 20, 0))


class AttemptTrendTests(unittest.TestCase):
    def test_direction_ignores_tries_still_waiting_for_lean(self):
        waiting = _attempts(queued={"recent": 3})
        self.assertEqual(attempt_trend(waiting)["direction"], "waiting")
        self.assertEqual(attempt_trend(_attempts())["direction"], "none")
        self.assertEqual(
            attempt_trend(_attempts(proved={"previous": 1}))["direction"],
            "quiet",
        )
        self.assertEqual(
            attempt_trend(_attempts(proved={"recent": 1}))["direction"],
            "first",
        )
        self.assertEqual(
            attempt_trend(_attempts(proved={"recent": 2, "previous": 1}, duplicate={"recent": 1, "previous": 2}))["direction"],
            "better",
        )
        self.assertEqual(
            attempt_trend(_attempts(proved={"recent": 1, "previous": 2}, duplicate={"recent": 2, "previous": 1}))["direction"],
            "weaker",
        )


def _attempts(**overrides):
    rows = {
        name: {"all": 0, "recent": 0, "previous": 0}
        for name in ("duplicate", "queued", "proved", "unresolved", "ill_formed", "refuted")
    }
    for name, windows in overrides.items():
        rows[name].update(windows)
    return rows


if __name__ == "__main__":
    unittest.main()
