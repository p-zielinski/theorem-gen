import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for item in (str(ROOT), str(TESTS)):
    if item not in sys.path:
        sys.path.insert(0, item)

from learn_support import accepting_runner, make_engine
from theorem_gen.learn.clock import ManualClock
from theorem_gen.learn.engine import ReplayBackend
from theorem_gen.learn.errors import Backpressure, Crash, LearnError
from theorem_gen.learn.queue import JobQueue
from theorem_gen.learn.store import Store


class _ScriptedBackend:
    def __init__(self) -> None:
        self.calls = 0
        self.invoked_model = True

    def complete(self, role, prompt):
        self.calls += 1
        return f"recorded-{self.calls}-{role}"


def _model_raws(store) -> list:
    rows = store._all(
        """
        SELECT attempts.raw_response
        FROM attempts
        JOIN candidates ON candidates.id = attempts.candidate_id
        WHERE candidates.run_id='run-1'
          AND attempts.model_version IS NOT NULL
          AND attempts.model_version != 'generator'
        ORDER BY attempts.id
        """,
    )
    return [row["raw_response"] for row in rows]


class RuntimeTests(unittest.TestCase):
    def test_priority_backpressure_heartbeat_and_expired_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = ManualClock()
            engine = make_engine(tmp, clock=clock, lease_ttl_s=10)
            engine.bootstrap()
            queue = JobQueue(engine.store, high_water=2, lease_ttl_s=10)
            queue.enqueue("run-1", "propose", payload={"n": 1}, idempotency_key="p")
            first = queue.enqueue("run-1", "lean_validate", payload={"n": 2}, idempotency_key="v")
            queue.enqueue("run-1", "lean_validate", payload={"n": 3}, idempotency_key="v2")
            with self.assertRaises(Backpressure):
                queue.enqueue("run-1", "lean_validate", payload={"n": 4}, idempotency_key="v3")
            self.assertEqual(queue.occupancy("run-1", "lean_validate"), 2)
            queued = queue.enqueue(
                "run-1",
                "lean_validate",
                payload={"n": 7},
                idempotency_key="model-lane",
                origin="model",
            )
            self.assertEqual(queued["state"], "queued")
            self.assertEqual(queue.occupancy("run-1", "lean_validate", origin="generator"), 2)
            self.assertEqual(queue.occupancy("run-1", "lean_validate", origin="model"), 1)
            queue.enqueue(
                "run-1",
                "lean_validate",
                payload={"n": 8},
                idempotency_key="model-lane-2",
                origin="model",
            )
            with self.assertRaises(Backpressure):
                queue.enqueue(
                    "run-1",
                    "lean_validate",
                    payload={"n": 9},
                    idempotency_key="model-lane-3",
                    origin="model",
                )
            again = queue.enqueue("run-1", "lean_validate", payload={"n": 9}, idempotency_key="v")
            self.assertEqual(again["id"], first["id"])
            job = queue.dequeue("run-1", "lean", ("lean_validate", "propose"), engine.hooks)
            self.assertEqual(job["job_type"], "lean_validate")
            clock.advance(5)
            self.assertTrue(queue.heartbeat(job["id"], "lean"))
            self.assertEqual(queue.reclaim_expired("run-1", clock.time()), 0)
            clock.advance(11)
            self.assertEqual(queue.reclaim_expired("run-1", clock.time()), 1)
            restored = engine.store._one("SELECT * FROM queue_jobs WHERE id=?", (job["id"],))
            self.assertEqual(restored["state"], "queued")
            self.assertEqual(restored["retry_count"], 1)

    def test_crash_points_do_not_lose_or_duplicate_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._assert_crash(tmp, "before", "after_dequeue_before_lease")
        with tempfile.TemporaryDirectory() as tmp:
            self._assert_crash(tmp, "validate", "after_validate_before_commit")
        with tempfile.TemporaryDirectory() as tmp:
            self._assert_checkpoint_crash(tmp)

    def test_pause_restores_rng_and_releases_leases(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            engine.rng.next_u32()
            engine.pause()
            state = engine.rng.get_state()
            checkpoint = engine.store.latest_known_good("run-1")
            self.assertEqual(int(checkpoint["rng_state"]), state)
            self.assertEqual(engine.store.get_run("run-1")["status"], "paused")
            path = Path(tmp) / "learn.sqlite"
            engine.close()
            restored = make_engine(tmp)
            restored.store = restored.store
            # Reopen the same file. make_engine created a second store on the same path.
            restored.resume()
            self.assertEqual(restored.rng.get_state(), state)
            self.assertEqual(restored.store.get_run("run-1")["status"], "running")
            self.assertTrue(path.is_file())

    def test_workers_stay_busy_while_eligible_work_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=2, max_steps=20)
            engine.bootstrap()
            engine.run_steps(20)
            self.assertGreater(engine.meter.inference_busy, 0)
            self.assertGreater(engine.meter.lean_busy, 0)
            self.assertGreaterEqual(engine.meter.ratio("inference"), 0.8)
            self.assertGreaterEqual(engine.meter.ratio("lean"), 0.8)
            self.assertEqual(engine.slot.resident_copies, 0)

    def test_replay_reproduces_outcomes_without_calling_the_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=2, max_steps=20)
            engine.start()
            from theorem_gen.learn.store import Store
            from theorem_gen.learn.clock import ManualClock

            dest = Store(Path(tmp) / "replay.sqlite", clock=ManualClock())
            matched = engine.replay_into(dest, 1)
            self.assertTrue(matched)
            self.assertEqual(engine.last_replay_backend.calls, 0)
            self.assertFalse(engine.last_replay_backend.invoked_model)
            self.assertGreater(len(engine.store.list_candidates("run-1")), 0)

    def test_replay_backend_returns_recorded_text_without_a_live_model(self):
        backend = ReplayBackend(['{"rationale":"recorded"}'])
        self.assertEqual(backend.complete("prover", "prompt"), '{"rationale":"recorded"}')
        self.assertFalse(backend.invoked_model)
        self.assertEqual(backend.calls, 1)

    def test_backpressure_rewinds_the_scheduler_and_does_not_stall_lean(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=2, high_water=1, max_steps=3)
            engine.bootstrap()
            before = engine.rng.get_state()
            engine.run_steps(3)
            self.assertEqual(engine.rng.get_state(), before)
            self.assertEqual(engine.scheduler["batch_index"], 0)
            self.assertIsNone(engine.scheduler["last_mix"])
            self.assertTrue(engine.scheduler["hold_propose"])
            propose = engine.store._one(
                "SELECT state FROM queue_jobs WHERE idempotency_key='run-1:propose:0'"
            )
            self.assertEqual(propose["state"], "queued")
            self.assertEqual(engine.store.list_candidates("run-1"), [])
            engine.queue.enqueue(
                "run-1",
                "lean_validate",
                payload={"candidate_id": 1},
                idempotency_key="drain-me",
            )
            engine.run_steps(3)
            drained = engine.store._one(
                "SELECT state FROM queue_jobs WHERE idempotency_key='drain-me'"
            )
            self.assertEqual(drained["state"], "failed")

    def test_a_bad_validation_does_not_stop_the_next_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=6)
            engine.bootstrap()
            engine.queue.enqueue(
                "run-1",
                "lean_validate",
                payload={"candidate_id": 1},
                idempotency_key="bad-1",
            )
            engine.queue.enqueue(
                "run-1",
                "lean_validate",
                payload={"candidate_id": 1},
                idempotency_key="bad-2",
            )
            engine.run_steps(6)
            states = [
                row["state"]
                for row in engine.store._all(
                    """
                    SELECT state FROM queue_jobs
                    WHERE idempotency_key IN ('bad-1', 'bad-2')
                    ORDER BY idempotency_key
                    """
                )
            ]
            self.assertEqual(states, ["failed", "failed"])

    def test_resume_keeps_the_scheduler_committed_with_the_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=20)
            engine.bootstrap()
            engine.run_steps(20)
            expected_index = engine.scheduler["batch_index"]
            expected_rng = engine.rng.get_state()
            self.assertGreater(expected_index, 0)
            engine.close()
            restored = make_engine(tmp, batch_count=1, max_steps=20)
            restored.resume()
            self.assertEqual(restored.scheduler["batch_index"], expected_index)
            self.assertEqual(restored.rng.get_state(), expected_rng)

    def test_unbound_or_foreign_proof_cannot_become_proved(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            from theorem_gen.expr import Compare, NatLit
            from theorem_gen.learn.astjson import canonical_json, structural_hash

            statement = Compare("eq", NatLit(0), NatLit(0))
            candidate = engine.store.upsert_candidate(
                stable_id="false-stmt",
                run_id="run-1",
                canonical_ast_json=canonical_json(statement),
                structural_hash=structural_hash(statement),
                kind="hypothesis",
                provenance="{}",
                curriculum_level=1,
            )
            with self.assertRaises(LearnError):
                engine._commit_validation(
                    candidate_id=candidate["id"],
                    source="theorem t : (0 = 0) := rfl\n",
                    validation_type="proof",
                    idempotency_key="swapped-proof",
                )
            self.assertEqual(
                engine.store.get_candidate(candidate["id"])["current_status"],
                "unresolved",
            )
            witness = engine.store.insert_counterexample(
                candidate_id=candidate["id"],
                assignment_json="{}",
                instantiated_prop="(1 = 0)",
                proposed_by="python",
            )
            with self.assertRaises(LearnError):
                engine.certify_witness(candidate["id"], witness["id"])
            self.assertEqual(
                engine.store.get_candidate(candidate["id"])["current_status"],
                "unresolved",
            )

    def test_replay_at_level_7_replays_recorded_role_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = _ScriptedBackend()
            engine = make_engine(tmp, backend=backend, batch_count=1, max_steps=80)
            engine.bootstrap()
            for level in range(1, 7):
                engine.store.upsert_window(
                    run_id="run-1",
                    level=level,
                    window_index=-1,
                    metrics_json="{}",
                    gate_status="passed",
                    evaluated_count=1000,
                )
            engine.store.update_run("run-1", curriculum_level=7)
            engine.publish("interval")
            seq = engine.store.latest_known_good("run-1")["seq"]
            engine.run_steps(80)
            self.assertGreater(backend.calls, 0)
            from theorem_gen.learn.store import Store

            dest = Store(Path(tmp) / "replay.sqlite", clock=engine.store.clock)
            matched = engine.replay_into(dest, seq)
            source_raws = _model_raws(engine.store)
            dest_raws = _model_raws(dest)
            self.assertTrue(matched)
            self.assertEqual(source_raws, dest_raws)
            self.assertGreater(engine.last_replay_backend.calls, 0)
            self.assertEqual(engine.last_replay_backend.calls, len(source_raws))
            self.assertFalse(engine.last_replay_backend.invoked_model)

    def test_unavailable_lean_stays_queued_for_a_later_resume(self):
        def missing_lake(cmd, timeout, cwd, env):
            raise FileNotFoundError("lake")

        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, runner=missing_lake, batch_count=1, max_steps=20)
            with self.assertRaises(LearnError) as caught:
                engine.start()
            self.assertIn("unavailable", str(caught.exception))
            self.assertEqual(engine.meter.lean_busy, 0)
            self.assertGreater(engine.meter.lean_idle, 0)
            self.assertEqual(
                engine.store.conn.execute("SELECT COUNT(*) FROM validations").fetchone()[0],
                0,
            )
            queued = engine.store.conn.execute(
                "SELECT COUNT(*) FROM queue_jobs WHERE job_type='lean_validate' AND state='queued'"
            ).fetchone()[0]
            self.assertGreater(queued, 0)
            self.assertEqual(engine.store.get_run("run-1")["status"], "paused")
            engine.runner = accepting_runner
            engine.resume()
            engine.run_steps(20)
            engine.finish()
            rows = engine.store.list_candidates("run-1")
            self.assertGreater(len(rows), 0)
            self.assertTrue(all(row["current_status"] == "proved" for row in rows))

    def test_a_failed_proposal_stays_queued_and_can_finish(self):
        import theorem_gen.learn.batches as batches_module

        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=20)
            engine.bootstrap()
            real = batches_module.build_batch
            calls = {"n": 0}

            def flaky(*args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("proposal failed")
                return real(*args, **kwargs)

            batches_module.build_batch = flaky
            try:
                engine.run_steps(1)
                job = engine.store._one(
                    "SELECT state, retry_count FROM queue_jobs WHERE idempotency_key='run-1:propose:0'"
                )
                self.assertEqual(job["state"], "queued")
                self.assertEqual(job["retry_count"], 1)
                self.assertEqual(engine.store.list_candidates("run-1"), [])
                engine.run_steps(15)
            finally:
                batches_module.build_batch = real
            self.assertGreater(len(engine.store.list_candidates("run-1")), 0)
            done = engine.store._one(
                "SELECT state FROM queue_jobs WHERE idempotency_key='run-1:propose:0'"
            )
            self.assertEqual(done["state"], "done")

    def test_resume_rebuilds_a_start_that_died_before_the_checkpoint_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.store.create_run("run-1", seed=engine.seed, config=engine._config())
            engine.resume()
            self.assertIsNotNone(engine.store.latest_known_good("run-1"))
            job = engine.store._one(
                "SELECT state FROM queue_jobs WHERE idempotency_key='run-1:propose:0'"
            )
            self.assertEqual(job["state"], "queued")

    def test_resume_reenqueues_a_proposal_that_never_landed(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            engine.store.conn.execute("DELETE FROM queue_jobs")
            engine.resume()
            job = engine.store._one(
                "SELECT state FROM queue_jobs WHERE idempotency_key='run-1:propose:0'"
            )
            self.assertEqual(job["state"], "queued")
            self.assertEqual(engine.store.list_candidates("run-1"), [])

    def test_resume_rejects_a_checkpoint_whose_rng_was_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            row = engine.store.latest_known_good("run-1")
            engine.store.conn.execute(
                "UPDATE checkpoints SET rng_state=? WHERE run_id=? AND seq=?",
                ("999", "run-1", row["seq"]),
            )
            engine.close()
            restored = make_engine(tmp)
            with self.assertRaises(LearnError) as caught:
                restored.resume()
            self.assertIn("rng", str(caught.exception))

    def test_crash_after_checkpoint_replace_keeps_the_previous_known_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=20)
            engine.bootstrap()
            engine.run_steps(20)
            known = engine.store.latest_known_good("run-1")
            before = engine.store.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            engine.hooks.crash_at = "after_replace_before_checkpoint_row"
            with self.assertRaises(Crash):
                engine.publish("pause")
            self.assertEqual(engine.store.latest_known_good("run-1")["seq"], known["seq"])
            orphan = Path(tmp) / "checkpoints" / "run-1" / f"{known['seq'] + 1}.json"
            self.assertTrue(orphan.is_file())
            self.assertIsNone(engine.store.get_checkpoint("run-1", known["seq"] + 1))
            engine.close()
            restored = make_engine(tmp, batch_count=1, max_steps=20)
            restored.resume()
            restored.run_steps(20)
            after = restored.store.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            self.assertEqual(after, before)

    def test_interval_checkpoint_respects_the_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = ManualClock()
            engine = make_engine(tmp, clock=clock)
            engine.bootstrap()
            clock.advance(299)
            engine._maybe_time_checkpoint()
            self.assertEqual(engine.store.latest_known_good("run-1")["seq"], 1)
            clock.advance(1)
            engine._maybe_time_checkpoint()
            row = engine.store.latest_known_good("run-1")
            self.assertEqual(row["seq"], 2)
            self.assertEqual(row["reason"], "interval")

    def test_step_budget_schedules_the_next_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=3, refill_when_idle=True)
            engine.start()
            rows = engine.store.list_candidates("run-1")
            self.assertEqual(len(rows), 3)
            self.assertEqual({row["current_status"] for row in rows}, {"proved"})
            self.assertEqual(len({row["stable_id"] for row in rows}), 3)
            failed = engine.store.count_where(
                "SELECT COUNT(*) FROM queue_jobs WHERE run_id=? AND state='failed'",
                ("run-1",),
            )
            self.assertEqual(failed, 0)
            dest = Store(Path(tmp) / "replay.sqlite", clock=ManualClock())
            self.assertTrue(engine.replay_into(dest, 1))
            self.assertEqual(
                {row["stable_id"]: row["current_status"] for row in dest.list_candidates("run-1")},
                {row["stable_id"]: row["current_status"] for row in rows},
            )

    def test_idle_queue_does_not_spend_the_step_budget_without_refill(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=20)
            engine.start()
            self.assertEqual(len(engine.store.list_candidates("run-1")), 1)

    def test_resume_with_refill_continues_after_the_queue_drains(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=20)
            engine.start()
            first = engine.store.list_candidates("run-1")[0]["stable_id"]
            engine.close()
            restored = make_engine(tmp, batch_count=1, max_steps=2, refill_when_idle=True)
            restored.resume()
            restored.run_steps(2)
            ids = [row["stable_id"] for row in restored.store.list_candidates("run-1")]
            self.assertEqual(ids.count(first), 1)
            self.assertEqual(len(ids), 3)
            self.assertEqual(len(set(ids)), 3)

    def test_refill_stops_when_the_current_propose_key_is_already_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=1, refill_when_idle=True)
            engine.bootstrap()
            engine.run_steps(1)
            self.assertEqual(len(engine.store.list_candidates("run-1")), 1)
            engine.scheduler["batch_index"] = 0
            engine.run_steps(10)
            self.assertEqual(len(engine.store.list_candidates("run-1")), 1)

    def test_level_seven_without_a_model_still_records_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=1)
            engine.bootstrap()
            for level in range(1, 7):
                engine.store.upsert_window(
                    run_id="run-1",
                    level=level,
                    window_index=-1,
                    metrics_json="{}",
                    gate_status="passed",
                    evaluated_count=1000,
                )
            engine.store.update_run("run-1", curriculum_level=7)
            engine.run_steps(1)
            rows = engine.store.list_candidates("run-1")
            self.assertTrue(rows)
            self.assertTrue(all(row["current_status"] == "proved" or row["kind"] != "theorem" for row in rows))
            self.assertTrue(any(row["current_status"] == "proved" for row in rows))
            failed = engine.store.count_where(
                "SELECT COUNT(*) FROM queue_jobs WHERE run_id=? AND state='failed'",
                ("run-1",),
            )
            self.assertEqual(failed, 0)
            roles = engine.store.count_where(
                """
                SELECT COUNT(*) FROM attempts
                WHERE model_version IS NOT NULL AND model_version != 'generator'
                """,
                (),
            )
            self.assertEqual(roles, 0)

    def test_a_higher_level_stores_a_lower_level_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=2, max_steps=1)
            engine.bootstrap()
            engine.store.upsert_window(
                run_id="run-1",
                level=1,
                window_index=-1,
                metrics_json="{}",
                gate_status="passed",
                evaluated_count=1000,
            )
            engine.store.update_run("run-1", curriculum_level=2)
            engine.run_steps(1)
            import json

            rows = engine.store.list_candidates("run-1")
            reviews = [row for row in rows if json.loads(row["provenance"]).get("review") is True]
            self.assertTrue(reviews)
            self.assertTrue(all(json.loads(row["provenance"])["source_level"] == 1 for row in reviews))
            self.assertTrue(all(row["current_status"] == "proved" for row in reviews))
            self.assertTrue(
                any(json.loads(row["provenance"]).get("generator") == "generate_general" for row in rows)
            )

    def test_step_budget_finishes_the_batch_it_already_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=4, max_steps=2, refill_when_idle=True)
            engine.start()
            rows = engine.store.list_candidates("run-1")
            self.assertEqual(len(rows), 4)
            self.assertEqual({row["current_status"] for row in rows}, {"proved"})
            self.assertEqual(engine.queue.depth("run-1"), 0)

    def test_zero_step_budget_does_not_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=4, max_steps=0, refill_when_idle=True)
            engine.start()
            self.assertEqual(engine.store.list_candidates("run-1"), [])
            self.assertEqual(engine.queue.depth("run-1"), 1)

    def test_real_lean_budget_proves_successive_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(
                tmp,
                run_id="real-budget",
                seed=1,
                batch_count=1,
                max_steps=2,
                lean_timeout_s=90,
                refill_when_idle=True,
                runner=None,
                project_dir=ROOT / "lean",
            )
            engine.start()
            rows = engine.store.list_candidates("real-budget")
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["current_status"] for row in rows}, {"proved"})
            self.assertEqual(len({row["stable_id"] for row in rows}), 2)

    def _assert_crash(self, tmp, label, point):
        engine = make_engine(tmp, batch_count=1, max_steps=20)
        engine.bootstrap()
        engine.hooks.crash_at = point
        with self.assertRaises(Crash):
            engine.run_steps(5)
        self.assertFalse((Path(tmp) / "checkpoints" / "run-1" / "2.json").exists())
        engine.close()
        restored = make_engine(tmp, batch_count=1, max_steps=20)
        restored.resume()
        restored.run_steps(20)
        attempts = restored.store.conn.execute(
            """
            SELECT idempotency_key FROM attempts
            JOIN candidates ON candidates.id = attempts.candidate_id
            WHERE candidates.run_id='run-1'
            """
        ).fetchall()
        keys = [row[0] for row in attempts]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), 1, label)
        validations = restored.store.conn.execute("SELECT idempotency_key FROM validations").fetchall()
        validation_keys = [row[0] for row in validations]
        self.assertEqual(len(validation_keys), len(set(validation_keys)))
        self.assertEqual(len(validation_keys), 1, label)

    def _assert_checkpoint_crash(self, tmp):
        engine = make_engine(tmp, batch_count=1, max_steps=20)
        engine.bootstrap()
        engine.run_steps(20)
        before = engine.store.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        known = engine.store.latest_known_good("run-1")
        engine.hooks.crash_at = "during_checkpoint_write"
        with self.assertRaises(Crash):
            engine.publish("pause")
        self.assertEqual(engine.store.latest_known_good("run-1")["seq"], known["seq"])
        self.assertFalse((Path(tmp) / "checkpoints" / "run-1" / f"{known['seq'] + 1}.json").exists())
        engine.close()
        restored = make_engine(tmp, batch_count=1, max_steps=20)
        restored.resume()
        restored.run_steps(20)
        after = restored.store.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        self.assertEqual(after, before)
        self.assertGreater(before, 0)
