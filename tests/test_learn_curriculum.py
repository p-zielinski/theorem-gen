import hashlib
import json
import sqlite3
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
from theorem_gen.expr import Compare, NatLit
from theorem_gen.learn.astjson import canonical_json, structural_hash
from theorem_gen.learn.batches import build_batch, source_for
from theorem_gen.learn.curriculum import (
    MIN_EVALUATED,
    WINDOW_SIZE,
    CONSECUTIVE_WINDOWS,
    coverage_met,
)
from theorem_gen.learn.heldout import HELD_OUT_HASHES
from theorem_gen.learn.policy import adjudicate, ensure_baseline, learning_claimed, select_training_rows
from theorem_gen.learn.roles import alternate_prompt, retrieve
from theorem_gen.learn.errors import LearnError


class CaptureBackend:
    def __init__(self):
        self.prompts = []
        self.invoked_model = False

    def complete(self, role, prompt):
        self.invoked_model = True
        self.prompts.append((role, prompt))
        return '{"rationale":"keep","verdict":"proved"}'


class CurriculumTests(unittest.TestCase):
    def test_gate_constants_and_levels_do_not_skip(self):
        self.assertEqual(MIN_EVALUATED, 1000)
        self.assertEqual(WINDOW_SIZE, 100)
        self.assertEqual(CONSECUTIVE_WINDOWS, 3)
        level1 = build_batch(1, seed=1, count=2)
        self.assertTrue(level1)
        self.assertTrue(all(item.provenance["generator"] == "generate" for item in level1))
        self.assertTrue(all(not item.needs_roles for item in level1))
        level2 = build_batch(2, seed=1, count=1)
        self.assertTrue(any(item.provenance["generator"] == "generate_general" for item in level2))
        level3 = build_batch(3, seed=1, count=1)
        self.assertTrue(any(item.provenance["generator"] == "wide_ast" for item in level3))
        level5 = build_batch(5, seed=1, count=1)
        self.assertTrue(all(item.provenance["complexity"] for item in level5))
        level6 = build_batch(6, seed=1, count=1)
        self.assertTrue(any(item.candidate_kind == "definition" for item in level6))
        self.assertTrue(all(not item.needs_roles for item in level6))
        self.assertIn("def double", source_for(next(item for item in level6 if item.candidate_kind == "definition")))
        level7 = build_batch(7, seed=1, count=1)
        self.assertTrue(any(item.needs_roles for item in level7))
        with self.assertRaises(LearnError):
            alternate_prompt({"stable_id": "c", "canonical_ast_json": "{}"}, "prove", primary="secret")

    def test_coverage_follows_the_new_surface_and_does_not_grow_with_the_index(self):
        concrete = [_coverage_row("generate")] * MIN_EVALUATED
        general = [_coverage_row("generate_general")] * MIN_EVALUATED
        self.assertFalse(coverage_met(2, concrete))
        self.assertTrue(coverage_met(2, general))
        self.assertFalse(coverage_met(3, concrete))
        self.assertTrue(coverage_met(3, concrete + [_coverage_row("wide_ast")]))
        self.assertTrue(coverage_met(4, concrete))
        self.assertTrue(coverage_met(5, concrete))
        self.assertFalse(coverage_met(6, concrete))
        covered = concrete + [
            _coverage_row("definitions", kind="definition"),
            _coverage_row("definitions", kind="theorem"),
        ]
        self.assertTrue(coverage_met(6, covered))
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            seed_proved_cohort(engine.store, "run-1", 1, MIN_EVALUATED)
            self.assertTrue(engine.maybe_promote())
            engine.publish("promotion")
            seed_proved_cohort(engine.store, "run-1", 2, MIN_EVALUATED, generator="generate")
            self.assertFalse(engine.maybe_promote())
            self.assertEqual(engine.level, 2)
            self.assertFalse(engine.store.get_run("run-1")["advancement_frozen"])
            seed_proved_cohort(
                engine.store,
                "run-1",
                2,
                MIN_EVALUATED,
                start=MIN_EVALUATED,
                generator="generate_general",
            )
            self.assertTrue(engine.maybe_promote())
            self.assertEqual(engine.level, 3)

    def test_timeouts_do_not_fill_the_promotion_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            _seed_timeouts(engine.store, MIN_EVALUATED)
            self.assertFalse(engine.maybe_promote())
            self.assertEqual(engine.level, 1)
            self.assertFalse(engine.store.get_run("run-1")["advancement_frozen"])

    def test_promotion_needs_the_full_gate_and_one_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            engine.store.append_event("run-1", "training_loss", {"loss": 0.01})
            self.assertFalse(engine.maybe_promote())
            self.assertEqual(engine.level, 1)
            self.assertFalse(engine.store.get_run("run-1")["advancement_frozen"])
            seed_proved_cohort(engine.store, "run-1", 1, 999)
            self.assertFalse(engine.maybe_promote())
            self.assertEqual(engine.level, 1)
            self.assertFalse(engine.store.get_run("run-1")["advancement_frozen"])
            seed_one_more(engine)
            self.assertTrue(engine.maybe_promote())
            self.assertEqual(engine.level, 2)
            self.assertFalse(engine.maybe_promote())
            engine.publish("interval")
            self.assertEqual(engine.store.get_run("run-1")["promoted_in_window"], 0)
            self.assertFalse(engine.maybe_promote())
            self.assertEqual(engine.level, 2)

    def test_identical_hashes_and_held_out_regression_freeze_without_erasing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            seed_proved_cohort(engine.store, "run-1", 1, 1000, identical=True)
            before = engine.store.conn.execute("SELECT COUNT(*) FROM validations").fetchone()[0]
            self.assertFalse(engine.maybe_promote())
            self.assertEqual(engine.level, 1)
            self.assertTrue(engine.store.get_run("run-1")["advancement_frozen"])
            after = engine.store.conn.execute("SELECT COUNT(*) FROM validations").fetchone()[0]
            self.assertEqual(after, before)
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            seed_proved_cohort(engine.store, "run-1", 1, 1000)
            engine.store.update_run("run-1", held_out_baseline=1.0, held_out_latest=1.0)

            def regress(source, validation_type):
                return {
                    "accepted": False,
                    "validation_type": validation_type,
                    "result": "rejected",
                    "failure_class": "proof",
                    "lean_version": "fixture",
                    "toolchain_hash": "fixture",
                    "stdout": "",
                    "stderr": "",
                    "message": "regression",
                }

            from theorem_gen.learn import heldout as heldout_module

            original = heldout_module.evaluate_held_out
            # Drive the engine's held-out through a failing validator.
            engine.runner = lambda *args: (1, "", "unsolved goals\n")
            self.assertFalse(engine.maybe_promote())
            self.assertTrue(engine.store.get_run("run-1")["advancement_frozen"])
            self.assertEqual(engine.level, 1)
            self.assertIs(original, heldout_module.evaluate_held_out)

    def test_roles_start_only_at_level_7_and_do_not_grant_proved(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, backend=CaptureBackend(), batch_count=1)
            engine.bootstrap()
            candidate = engine.store.upsert_candidate(
                stable_id="early-theorem",
                run_id="run-1",
                canonical_ast_json=canonical_json(Compare("eq", NatLit(1), NatLit(1))),
                structural_hash=structural_hash(Compare("eq", NatLit(1), NatLit(1))),
                kind="theorem",
                provenance="{}",
                curriculum_level=1,
            )
            engine.queue.enqueue(
                "run-1",
                "prove_primary",
                payload={"candidate_id": candidate["id"]},
                idempotency_key="early-prove",
            )
            engine.run_steps(8)
            state = engine.store._one(
                "SELECT state FROM queue_jobs WHERE idempotency_key='early-prove'"
            )
            self.assertEqual(state["state"], "failed")
            roles = [
                row["role"]
                for row in engine.store.conn.execute("SELECT role FROM attempts").fetchall()
            ]
            self.assertNotIn("prover", roles)
        with tempfile.TemporaryDirectory() as tmp:
            backend = CaptureBackend()
            engine = make_engine(tmp, backend=backend, batch_count=1)
            engine.bootstrap()
            while engine.level < 7:
                _seed_level_gate(engine, engine.level)
                self.assertTrue(engine.maybe_promote(), engine.level)
                engine.publish("promotion")
            self.assertEqual(engine.level, 7)
            statement = Compare("eq", NatLit(3), NatLit(3))
            candidate = engine.store.upsert_candidate(
                stable_id="role-theorem",
                run_id="run-1",
                canonical_ast_json=canonical_json(statement),
                structural_hash=structural_hash(statement),
                kind="theorem",
                provenance="{}",
                curriculum_level=7,
                family="eq",
            )
            engine.store.insert_attempt(
                candidate_id=candidate["id"],
                role="prover",
                model_version="stub",
                prompt_hash="h",
                raw_response="SENTINEL-PRIMARY",
                proof_artifact="SENTINEL-PRIMARY",
                critique_artifact=None,
                idempotency_key="sentinel-primary",
                duration_ms=0,
            )
            engine.queue.enqueue(
                "run-1",
                "prove_alternate_or_critique",
                payload={"candidate_id": candidate["id"], "phase": "prove"},
                idempotency_key="alt-prove",
            )
            engine.run_steps(2)
            self.assertGreaterEqual(len(backend.prompts), 2)
            self.assertNotIn("SENTINEL-PRIMARY", backend.prompts[0][1])
            self.assertIn("SENTINEL-PRIMARY", backend.prompts[1][1])
            self.assertEqual(engine.slot.resident_copies, 1)
            self.assertEqual(engine.store.get_candidate(candidate["id"])["current_status"], "unresolved")
            found = retrieve(
                engine.store,
                "run-1",
                structural_hash="missing",
                family=engine.store.list_candidates("run-1")[0]["family"],
            )
            self.assertTrue(found)
            self.assertNotIn("raw_response", found[0])

    def test_training_selection_and_challenger_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            proved = self._row(engine, "proved-row", "proved", "hash-proved", "add")
            engine.store.insert_validation(
                candidate_id=proved["id"],
                lean_version="fixture",
                toolchain_hash="fixture",
                validation_type="proof",
                result="accepted",
                accepted=True,
                message="ok",
                idempotency_key="train-proof",
                stdout="",
                stderr="",
                failure_class=None,
            )
            unresolved = self._row(engine, "open-row", "unresolved", "hash-open", "add")
            ill = self._row(engine, "bad-row", "ill_formed", "hash-bad", "add")
            bare = self._row(engine, "bare-refuted", "refuted", "hash-bare", "mul")
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.conn.execute(
                    "UPDATE candidates SET current_status='refuted' WHERE id=?",
                    (bare["id"],),
                )
            held = self._row(engine, "held-row", "proved", next(iter(HELD_OUT_HASHES)), "add", held_out=1)
            engine.store.insert_validation(
                candidate_id=held["id"],
                lean_version="fixture",
                toolchain_hash="fixture",
                validation_type="proof",
                result="accepted",
                accepted=True,
                message="ok",
                idempotency_key="held-proof",
                stdout="",
                stderr="",
                failure_class=None,
            )
            for index in range(3):
                child = self._row(
                    engine,
                    f"child-{index}",
                    "proved",
                    f"hash-child-{index}",
                    "mul",
                    ancestor="ancestor-1",
                )
                engine.store.insert_validation(
                    candidate_id=child["id"],
                    lean_version="fixture",
                    toolchain_hash="fixture",
                    validation_type="proof",
                    result="accepted",
                    accepted=True,
                    message="ok",
                    idempotency_key=f"child-proof-{index}",
                    stdout="",
                    stderr="",
                    failure_class=None,
                )
            rows = select_training_rows(engine.store, "run-1", cap=2)
            identifiers = {row["stable_id"] for row in rows}
            self.assertIn("proved-row", identifiers)
            self.assertNotIn("open-row", identifiers)
            self.assertNotIn("bad-row", identifiers)
            self.assertNotIn("bare-refuted", identifiers)
            self.assertNotIn("held-row", identifiers)
            self.assertEqual(len([item for item in rows if item["ancestor_stable_id"] == "ancestor-1"]), 2)
            self.assertTrue(unresolved and ill and bare)
            scores = {
                "correctness": 1.0,
                "solve_rate": 0.5,
                "calibration": 0.5,
                "diversity": 1.0,
                "resource": 1.0,
            }
            ensure_baseline(engine.store, scores)
            engine.store.insert_model(
                version_id="challenger-worse",
                role="challenger",
                scores=dict(scores, solve_rate=0.4),
                path="adapter",
                weight_hash="w",
                adapter_hash="a",
            )
            before = engine.store.latest_known_good("run-1")["seq"]
            self.assertEqual(adjudicate(engine.store, "challenger-worse"), "rolled_back")
            self.assertEqual(engine.store.latest_known_good("run-1")["seq"], before)
            self.assertEqual(engine.store.champion()["version_id"], "champion-generator-v0")
            self.assertEqual(engine.store.get_model("challenger-worse")["role"], "retired")
            self.assertEqual(engine.store.baseline()["role"], "baseline")
            self.assertFalse(learning_claimed(engine.store))
            better = dict(scores, solve_rate=0.8, calibration=0.8)
            engine.store.insert_model(
                version_id="challenger-better",
                role="challenger",
                scores=better,
                path="adapter",
                weight_hash="w2",
                adapter_hash="a2",
            )
            self.assertEqual(engine.promote_model("challenger-better"), "promoted")
            self.assertEqual(engine.store.latest_known_good("run-1")["reason"], "model_promotion")
            self.assertEqual(engine.store.champion()["version_id"], "challenger-better")
            self.assertEqual(engine.store.get_model("champion-generator-v0")["role"], "retired")
            self.assertFalse(learning_claimed(engine.store))
            measured = dict(scores, solve_rate=0.9, calibration=0.9, diversity=1.1)
            engine.store.insert_model(
                version_id="challenger-measured",
                role="challenger",
                scores=measured,
                path="adapter",
                weight_hash="w3",
                adapter_hash="a3",
            )
            self.assertEqual(engine.promote_model("challenger-measured"), "promoted")
            self.assertTrue(learning_claimed(engine.store))

    def _row(self, engine, stable, status, structural, family, *, ancestor=None, held_out=0):
        row = engine.store.upsert_candidate(
            stable_id=stable,
            run_id="run-1",
            canonical_ast_json="{}",
            structural_hash=structural,
            kind="theorem",
            provenance="{}",
            curriculum_level=1,
            family=family,
            ast_size=4,
            depth=2,
            proof_method="rfl",
            ancestor_stable_id=ancestor,
            held_out=held_out,
        )
        if status == "ill_formed":
            engine.store.insert_validation(
                candidate_id=row["id"],
                lean_version="fixture",
                toolchain_hash="fixture",
                validation_type="proof",
                result="ill_formed",
                accepted=False,
                stdout="",
                stderr="unexpected token",
                message="syntax",
                failure_class="syntax",
                idempotency_key=f"ill-{stable}",
            )
            return engine.store.get_candidate(row["id"])
        return row


def _coverage_row(generator: str, kind: str = "theorem") -> dict:
    return {"provenance": json.dumps({"generator": generator}), "kind": kind}


def _seed_level_gate(engine, level: int) -> None:
    generator = "generate_general" if level == 2 else "cohort"
    seed_proved_cohort(engine.store, "run-1", level, MIN_EVALUATED, generator=generator)
    if level == 3:
        seed_proved_cohort(
            engine.store,
            "run-1",
            level,
            1,
            start=MIN_EVALUATED,
            generator="wide_ast",
        )
    if level == 6:
        seed_proved_cohort(
            engine.store,
            "run-1",
            level,
            1,
            start=MIN_EVALUATED,
            generator="definitions",
            kind="definition",
        )
        seed_proved_cohort(
            engine.store,
            "run-1",
            level,
            1,
            start=MIN_EVALUATED + 1,
            generator="definitions",
            kind="theorem",
        )


def _seed_timeouts(store, count: int) -> None:
    """Diverse rows whose only Lean result is a timeout. They must not promote."""
    now = store.now()
    families = ("add_zero", "eval_eq", "le_refl", "mul_one")
    methods = ("rfl", "decide")
    candidates = []
    validations = []
    for index in range(count):
        stable = f"timeout-{index}"
        structural = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        candidates.append(
            (
                stable,
                "run-1",
                "{}",
                structural,
                "theorem",
                "{}",
                "unresolved",
                1,
                None,
                families[index % len(families)],
                5,
                2,
                methods[index % len(methods)],
                0,
                0,
                now,
                now,
            )
        )
    with store.transaction():
        store.conn.executemany(
            """
            INSERT INTO candidates (
              stable_id, run_id, canonical_ast_json, structural_hash, kind, provenance,
              current_status, curriculum_level, ancestor_stable_id, family, ast_size, depth,
              proof_method, dependency_depth, held_out, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            candidates,
        )
        found = store.conn.execute(
            "SELECT id, stable_id FROM candidates WHERE stable_id LIKE 'timeout-%' ORDER BY id"
        ).fetchall()
        for row in found:
            validations.append(
                (
                    row["id"],
                    None,
                    "fixture",
                    "fixture",
                    "proof",
                    "timeout",
                    0,
                    "",
                    "",
                    "timed out",
                    None,
                    f"timeout-val-{row['stable_id']}",
                    now,
                )
            )
        store.conn.executemany(
            """
            INSERT INTO validations (
              candidate_id, attempt_id, lean_version, toolchain_hash, validation_type,
              result, accepted, stdout, stderr, message, failure_class, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            validations,
        )


def seed_one_more(engine) -> None:
    seed_proved_cohort_offset(engine.store)


def seed_proved_cohort_offset(store) -> None:
    """The 1000th level-1 candidate uses a distinct stable id from the first 999."""
    from learn_support import seed_proved_cohort as seed

    # Inserting count=1 with the helper would reuse cohort-1-0. Write the missing row.
    now = store.now()
    import hashlib

    stable = "cohort-1-999"
    structural = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    with store.transaction():
        store.conn.execute(
            """
            INSERT INTO candidates (
              stable_id, run_id, canonical_ast_json, structural_hash, kind, provenance,
              current_status, curriculum_level, ancestor_stable_id, family, ast_size, depth,
              proof_method, dependency_depth, held_out, created_at, updated_at
            ) VALUES (?, 'run-1', '{}', ?, 'theorem', '{}', 'unresolved', 1, NULL, 'add_zero', 4, 2, 'rfl', 0, 0, ?, ?)
            """,
            (stable, structural, now, now),
        )
        row_id = store.conn.execute(
            "SELECT id FROM candidates WHERE stable_id=?",
            (stable,),
        ).fetchone()["id"]
        store.conn.execute(
            """
            INSERT INTO validations (
              candidate_id, attempt_id, lean_version, toolchain_hash, validation_type,
              result, accepted, stdout, stderr, message, failure_class, idempotency_key, created_at
            ) VALUES (?, NULL, 'fixture', 'fixture', 'proof', 'accepted', 1, '', '', 'cohort', NULL, ?, ?)
            """,
            (row_id, f"cohort-val-{stable}", now),
        )
        store.conn.execute(
            """
            UPDATE candidates
            SET current_status='proved', updated_at=?
            WHERE stable_id=?
            """,
            (now, stable),
        )
