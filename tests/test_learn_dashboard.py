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

from learn_support import make_engine, seed_proved_cohort
from theorem_gen.learn.dashboard import (
    _PAGE,
    acceptance_series,
    attempt_trend,
    own_equation_summary,
    resolve_run_id,
    snapshot,
    visible_text,
)
from theorem_gen.learn.effort import effort_level, lean_time_band, statement_depth, statement_measures


class EffortTests(unittest.TestCase):
    def test_grades_follow_shape_and_proof_method(self):
        self.assertEqual(effort_level("decide", 3, 1), 1)
        self.assertEqual(effort_level("rfl", 4, 1), 2)
        self.assertEqual(effort_level("rfl", 9, 3), 3)
        self.assertEqual(effort_level("lemma", 5, 2), 3)
        self.assertEqual(effort_level("rewrite", 12, 4), 4)
        self.assertIsNone(effort_level("model", 40, 1))
        self.assertIsNone(effort_level("", 3, 1))

    def test_statement_depth_follows_the_tree_and_ignores_the_numeral(self):
        from theorem_gen.complexity import _depth, _operators, _size
        from theorem_gen.export_lean import export_prop
        from theorem_gen.expr import BinOp, Compare, Const, Implies, IntLit, NatLit, UnaryOp, Var

        bare = Compare("eq", NatLit(100000), NatLit(100000))
        added = Compare("eq", BinOp("add", Var("a", "Nat"), NatLit(0)), Var("a", "Nat"))
        nested = Compare(
            "eq",
            BinOp(
                "add",
                BinOp("add", NatLit(7), NatLit(6)),
                BinOp("add", NatLit(5), NatLit(2)),
            ),
            NatLit(20),
        )
        succ = Compare("eq", UnaryOp("succ", NatLit(0)), NatLit(1))
        negated = Compare("eq", UnaryOp("neg", IntLit(5)), IntLit(-5))
        called = Compare("eq", Const("double", "Nat", (NatLit(1),)), NatLit(2))
        implied = Implies(bare, added)
        for expr in (bare, added, nested, succ, negated, called, implied):
            text = export_prop(expr)
            found = statement_measures(text)
            self.assertEqual(
                (found["depth"], found["operators"], found["size"]),
                (_depth(expr), _operators(expr), _size(expr)),
                text,
            )
        from theorem_gen.expr import Forall

        quantified = Forall((Var("a", "Nat"),), added)
        found = statement_measures("forall (a : Nat), ((a + 0) = a)")
        self.assertEqual(
            (found["depth"], found["operators"], found["size"]),
            (_depth(quantified), _operators(quantified), _size(quantified)),
        )
        self.assertEqual(statement_depth("Nat) : ((a + 0) = a)"), 2)
        self.assertEqual(statement_depth("(1 + 1 = 2)"), 2)
        self.assertIsNone(statement_measures("not an equation !!!"))
        self.assertEqual(statement_depth("not an equation !!!"), 0)

    def test_lean_time_bands(self):
        self.assertIsNone(lean_time_band(None))
        self.assertEqual(lean_time_band(40), "fast")
        self.assertEqual(lean_time_band(250), "normal")
        self.assertEqual(lean_time_band(900), "slow")
        self.assertEqual(lean_time_band(4000), "heavy")


class SnapshotTests(unittest.TestCase):
    def test_a_preview_drops_control_bytes_and_stays_short(self):
        shown = visible_text("a\x10b\n" + ("x" * 200))
        self.assertNotIn("\x10", shown)
        self.assertNotIn("\n", shown)
        self.assertTrue(shown.startswith("ab "))
        self.assertLessEqual(len(shown), 72)
        self.assertTrue(shown.endswith("…"))
        self.assertEqual(visible_text("\x00\x01"), "(not printable)")

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
            self.assertEqual(info["material_cap"], 128)
            self.assertFalse(info["generator_waiting"])

    def test_new_material_above_128_marks_the_generator_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            seed_proved_cohort(engine.store, "run-1", 1, 129)
            info = snapshot(engine.store.path, "run-1")
            self.assertEqual(info["unread"], 129)
            self.assertTrue(info["generator_waiting"])
            self.assertIn("Above 128", _PAGE)
            self.assertIn("generator_waiting", _PAGE)

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
            self.assertEqual(info["own"]["accepted"], 2)
            self.assertEqual(info["own"]["finished"], 5)
            self.assertEqual(info["recent_attempts"][0]["disposition"], "refuted")
            self.assertIsNone(info["recent_attempts"][0]["lm_step"])


class OwnEquationTests(unittest.TestCase):
    def test_a_repeat_is_judged_and_a_waiting_row_is_not(self):
        summary = own_equation_summary(
            _attempts(proved={"all": 2}, duplicate={"all": 3}, queued={"all": 4})
        )
        self.assertEqual(summary, {"accepted": 2, "finished": 5, "waiting": 4})

    def test_the_recent_share_falls_after_a_good_start(self):
        rise = [(1000 + i, "proved") for i in range(10)]
        fall = [(2000 + i, "duplicate") for i in range(10)]
        points = acceptance_series([(1, "queued")] + rise + fall)
        self.assertEqual(len(points), 20)
        self.assertEqual(points[9]["recent"], 1)
        self.assertEqual(points[9]["overall"], 1)
        self.assertEqual(points[19]["recent"], 0)
        self.assertEqual(points[19]["overall"], 0.5)
        self.assertLess(points[0]["t"], points[19]["t"])

    def test_freedom_follows_the_latest_block_and_returns_to_baseline(self):
        from theorem_gen.learn.balance import freedom_plan

        self.assertEqual(freedom_plan(["proved"] * 19)["level"], 0)
        self.assertEqual(freedom_plan(["proved"] * 19)["burst"], 40)
        self.assertEqual(freedom_plan(["proved"] * 14 + ["duplicate"] * 6)["level"], 0)
        wider = freedom_plan(["proved"] * 16 + ["duplicate"] * 4)
        self.assertEqual((wider["level"], wider["burst"], wider["study"]), (1, 80, 20))
        widest = freedom_plan(["proved"] * 20)
        self.assertEqual((widest["level"], widest["burst"], widest["study"], widest["weak"]), (2, 160, 10, 16))
        self.assertEqual(freedom_plan(["proved"] * 40)["level"], 2)
        average = ["proved"] * 20 + ["proved"] * 10 + ["duplicate"] * 10
        self.assertEqual(freedom_plan(average)["level"], 0)
        self.assertEqual(freedom_plan(average)["burst"], 40)
        deep_bonus = [("proved", 3)] * 16 + [("duplicate", 1)] * 4
        self.assertEqual(freedom_plan(deep_bonus)["level"], 2)
        shallow_same = [("proved", 1)] * 16 + [("duplicate", 1)] * 4
        self.assertEqual(freedom_plan(shallow_same)["level"], 1)
        mediocre_deep = [("proved", 3)] * 10 + [("duplicate", 3)] * 10
        self.assertEqual(freedom_plan(mediocre_deep)["level"], 0)

    def test_a_clear_rise_widens_the_next_turn(self):
        from theorem_gen.learn.minilm import MiniLMService

        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            now = float(engine.store.now())
            climb = ["duplicate"] * 18 + ["proved"] * 2
            climb += ["proved"] * 12 + ["duplicate"] * 8
            climb += ["proved"] * 20
            for index, disposition in enumerate(climb):
                engine.store.conn.execute(
                    """
                    INSERT INTO model_attempts (
                      run_id, equation, equation_hash, origin, disposition, candidate_id, created_at
                    ) VALUES ('run-1', ?, ?, 'model', ?, NULL, ?)
                    """,
                    (disposition, f"hash-{index}", disposition, f"{now + index:.6f}"),
                )
            service = MiniLMService(Path(tmp) / "lm", type("W", (), {"context": 8})())
            service._load_state(engine.store, "run-1")
            service.recent_losses = [0.2] * 10
            service.burst_left = 0
            service.study_left = 0
            service.hold = False
            service._save_state(engine.store, "run-1")
            service._sample = lambda _engine: "queued"
            service.tick(engine)
            self.assertEqual(service.burst_left, 159)
            info = snapshot(engine.store.path, "run-1")
            self.assertEqual(info["freedom"]["level"], 2)
            self.assertEqual(len(info["freedom"]["blocks"]), 3)
            self.assertIn("t", info["freedom"]["blocks"][0])

    def test_an_attempt_remembers_the_step_and_loss(self):
        from theorem_gen.learn.minilm import MiniLMService

        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            service = MiniLMService(Path(tmp) / "lm", type("W", (), {"context": 8})())
            service._load_state(engine.store, "run-1")
            service.step = 40
            service.last_loss = 0.41
            service._record(engine, "1 = 1", "hash-one", "duplicate", None)
            service.step = 41
            service.last_loss = 0.39
            service._record(engine, "2 = 2", "hash-two", "ill_formed", None)
            info = snapshot(engine.store.path, "run-1")
            self.assertEqual(info["own"], {"accepted": 0, "finished": 2, "waiting": 0})
            self.assertEqual(info["recent_attempts"][0]["equation"], "2 = 2")
            self.assertEqual(info["recent_attempts"][0]["lm_step"], 41)
            self.assertAlmostEqual(info["recent_attempts"][0]["loss"], 0.39)
            self.assertEqual(info["recent_attempts"][1]["lm_step"], 40)
            self.assertEqual(info["recent_attempts"][0]["expr_depth"], 1)
            self.assertEqual(info["recent_attempts"][0]["expr_operators"], 0)
            self.assertEqual(info["recent_attempts"][0]["expr_size"], 3)
            self.assertEqual(info["complexity"]["accepted"], 0)
            self.assertEqual(info["accepted_formulas"], [])

    def test_accepted_formulas_stay_listed_apart_from_other_tries(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            now = float(engine.store.now())
            rows = (
                ("1 = 1", "proved", 0, "sample"),
                ("not a formula", "ill_formed", 0, "sample"),
                ("2 = 2", "proved", 1, "sample"),
            )
            for index, (equation, disposition, ply, decoder) in enumerate(rows):
                engine.store.conn.execute(
                    """
                    INSERT INTO model_attempts (
                      run_id, equation, equation_hash, origin, disposition, candidate_id,
                      created_at, repair_ply, decoder, cycle, lm_step, loss
                    ) VALUES ('run-1', ?, ?, 'model', ?, NULL, ?, ?, ?, 4, 12, 0.5)
                    """,
                    (equation, f"hash-{index}", disposition, f"{now + index:.6f}", ply, decoder),
                )
            engine.store.conn.commit()
            info = snapshot(engine.store.path, "run-1")
            self.assertEqual(
                [row["equation"] for row in info["accepted_formulas"]],
                ["2 = 2", "1 = 1"],
            )
            self.assertEqual(info["accepted_formulas"][0]["repair_ply"], 1)
            self.assertEqual(info["accepted_formulas"][0]["cycle"], 4)
            self.assertEqual(info["recent_attempts"][0]["disposition"], "proved")
            engine.close()

    def test_accepted_depth_is_a_mean_with_an_interval(self):
        from theorem_gen.learn.dashboard import complexity_series
        from theorem_gen.learn.effort import remember_shapes

        shallow = [(1000 + i, "proved", 1, 0, 3) for i in range(10)]
        deep = [(2000 + i, "proved", 3, 2, 7) for i in range(10)]
        found = complexity_series(
            [(1, "queued", 9, 9, 9), (2, "duplicate", 4, 3, 9)] + shallow + deep
        )
        self.assertEqual(found["accepted"], 20)
        self.assertEqual(found["points"][9]["recent"], 1)
        self.assertEqual(found["points"][19]["recent"], 3)
        self.assertEqual(found["points"][19]["overall"], 2)
        self.assertAlmostEqual(found["depth_blocks"][0]["mean"], 2)
        self.assertLess(found["depth_blocks"][0]["low"], 2)
        self.assertGreater(found["depth_blocks"][0]["high"], 2)
        flat = complexity_series([(i, "proved", 1, 0, 3) for i in range(20)])
        self.assertEqual(flat["depth_blocks"][0]["low"], 1)
        self.assertEqual(flat["depth_blocks"][0]["high"], 1)
        skipped = complexity_series([(1, "proved", None, None, None)])
        self.assertEqual(skipped["accepted"], 0)
        self.assertEqual(skipped["unmeasured"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            engine.store.conn.execute(
                """
                INSERT INTO model_attempts (
                  run_id, equation, equation_hash, origin, disposition, candidate_id, created_at
                ) VALUES ('run-1', '(1 + 1 = 2)', 'hash-shape', 'model', 'proved', NULL, '1')
                """
            )
            remember_shapes(engine.store.conn)
            row = engine.store.conn.execute(
                "SELECT expr_depth, expr_operators, expr_size FROM model_attempts"
            ).fetchone()
            self.assertEqual(tuple(row), (2, 1, 5))
            info = snapshot(engine.store.path, "run-1")
            self.assertEqual(info["complexity"]["points"][0]["depth"], 2)
            self.assertEqual(info["complexity"]["points"][0]["operators"], 1)


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


class RunningRunTests(unittest.TestCase):
    def _runs(self, directory, rows):
        engine = make_engine(directory, max_steps=0)
        for run_id, status, stamp in rows:
            engine.store.conn.execute(
                """
                INSERT INTO runs (
                  run_id, status, seed, config_json, curriculum_level, created_at, updated_at
                ) VALUES (?, ?, 1, '{}', 1, ?, ?)
                """,
                (run_id, status, stamp, stamp),
            )
        engine.store.conn.commit()
        return engine

    def test_a_running_run_wins_over_a_requested_paused_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._runs(
                tmp,
                (("run-2", "paused", "2000"), ("run-3", "running", "1000")),
            )
            self.assertEqual(resolve_run_id(engine.store.conn, "run-2"), "run-3")
            engine.close()

    def test_the_newest_running_row_wins_when_two_are_marked(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._runs(
                tmp,
                (("run-2", "running", "2000"), ("run-3", "running", "3000")),
            )
            self.assertEqual(resolve_run_id(engine.store.conn, "run-2"), "run-3")
            engine.close()

    def test_a_paused_request_is_used_only_when_nothing_is_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._runs(
                tmp,
                (("run-2", "paused", "2000"), ("run-3", "paused", "3000")),
            )
            self.assertEqual(resolve_run_id(engine.store.conn, "run-2"), "run-2")
            self.assertEqual(resolve_run_id(engine.store.conn, None), "run-3")
            engine.close()


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
