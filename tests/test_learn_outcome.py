import hashlib
import sqlite3
import subprocess
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
from theorem_gen.expr import Compare, NatLit
from theorem_gen.learn.astjson import canonical_json, load_expr, structural_hash
from theorem_gen.learn.batches import build_batch, source_for
from theorem_gen.learn.classify import (
    ValidationView,
    counts_as_lean_evaluated,
    derive_outcome,
    map_hypothesis_status,
    mathematical_outcome,
)
from theorem_gen.learn.validate import negation_source, validate_source
from theorem_gen.verify import find_lake


def lake_available() -> bool:
    project = ROOT / "lean"
    if not project.is_dir():
        return False
    try:
        find_lake(project)
    except FileNotFoundError:
        return False
    return True


class OutcomeTests(unittest.TestCase):
    def test_hypothesis_vocabulary_and_check_is_not_a_proof(self):
        self.assertEqual(map_hypothesis_status("invalid_syntax"), "ill_formed")
        self.assertEqual(map_hypothesis_status("invalid_type"), "ill_formed")
        self.assertEqual(map_hypothesis_status("proved"), "proved")
        self.assertEqual(map_hypothesis_status("refuted"), "refuted")
        self.assertEqual(map_hypothesis_status("unresolved"), "unresolved")
        self.assertEqual(
            derive_outcome([ValidationView("check", "accepted", True, None)]),
            "unresolved",
        )
        self.assertEqual(
            derive_outcome([ValidationView("check", "accepted", False, None)]),
            "unresolved",
        )
        self.assertFalse(counts_as_lean_evaluated(ValidationView("proof", "timeout", False, None)))
        self.assertFalse(counts_as_lean_evaluated(ValidationView("proof", "unavailable", False, None)))
        self.assertFalse(counts_as_lean_evaluated(ValidationView("proof", "ill_formed", False, "rejected")))
        self.assertTrue(counts_as_lean_evaluated(ValidationView("proof", "rejected", False, "proof")))
        self.assertTrue(counts_as_lean_evaluated(ValidationView("check", "accepted", False, None)))
        self.assertIsNone(mathematical_outcome("quarantined"))

    def test_role_agreement_cannot_mark_a_lean_rejection_proved(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            candidate = self._candidate(engine, Compare("eq", NatLit(1), NatLit(1)))
            for role in ("theorem_proposer", "prover", "alternate_prover_critic"):
                engine.store.insert_attempt(
                    candidate_id=candidate["id"],
                    role=role,
                    model_version="stub",
                    prompt_hash="h",
                    raw_response='{"verdict":"proved"}',
                    proof_artifact='{"verdict":"proved"}',
                    critique_artifact=None,
                    idempotency_key=f"agree-{role}",
                    duration_ms=0,
                )
            engine.store.insert_validation(
                candidate_id=candidate["id"],
                lean_version="fixture",
                toolchain_hash="fixture",
                validation_type="proof",
                result="rejected",
                accepted=False,
                stdout="",
                stderr="unsolved goals",
                message="proof failed",
                failure_class="proof",
                idempotency_key="rejected-proof",
            )
            self.assertEqual(engine.store.get_candidate(candidate["id"])["current_status"], "unresolved")

    def test_python_witness_stays_unresolved_until_lean_certifies_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            statement = Compare("eq", NatLit(1), NatLit(0))
            candidate = self._candidate(engine, statement, kind="hypothesis")
            witness = engine.note_witness(candidate["id"])
            self.assertIsNotNone(witness)
            self.assertIsNone(witness["lean_certificate_id"])
            self.assertEqual(engine.store.get_candidate(candidate["id"])["current_status"], "unresolved")
            self.assertEqual(witness["instantiated_prop"], "(1 = 0)")
            status = engine.certify_witness(candidate["id"], witness["id"])
            self.assertEqual(status, "refuted")
            stored = engine.store.list_counterexamples(candidate["id"])[0]
            self.assertIsNotNone(stored["lean_certificate_id"])
            validation = engine.store.list_validations(candidate["id"])[0]
            self.assertEqual(validation["validation_type"], "counterexample")
            self.assertEqual(validation["accepted"], 1)

    def test_syntax_is_ill_formed_and_timeout_is_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            syntax = self._candidate(engine, Compare("eq", NatLit(1), NatLit(1)), stable="syntax")

            def syntax_runner(cmd, timeout, cwd, env):
                return 1, "", "unexpected token ':='\n"

            self._validate(engine, syntax["id"], "theorem t : (1 = := rfl\n", "proof", syntax_runner, "syntax-key")
            self.assertEqual(engine.store.get_candidate(syntax["id"])["current_status"], "ill_formed")
            timeout = self._candidate(engine, Compare("eq", NatLit(2), NatLit(2)), stable="timeout")

            def timeout_runner(cmd, timeout, cwd, env):
                raise subprocess.TimeoutExpired(cmd="lean", timeout=1)

            self._validate(engine, timeout["id"], "theorem t : (2 = 2) := rfl\n", "proof", timeout_runner, "timeout-key")
            self.assertEqual(engine.store.get_candidate(timeout["id"])["current_status"], "unresolved")
            typing = self._candidate(engine, Compare("eq", NatLit(3), NatLit(3)), stable="typing")

            def typing_runner(cmd, timeout, cwd, env):
                return 1, "", "Type mismatch\n"

            self._validate(engine, typing["id"], "theorem t : (3 = 3) := rfl\n", "proof", typing_runner, "typing-key")
            self.assertEqual(engine.store.get_candidate(typing["id"])["current_status"], "ill_formed")

    def test_forbidden_constructs_are_rejected_even_if_roles_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            candidate = self._candidate(engine, Compare("eq", NatLit(1), NatLit(1)), stable="sorry")
            engine.store.insert_attempt(
                candidate_id=candidate["id"],
                role="prover",
                model_version="stub",
                prompt_hash="h",
                raw_response='{"verdict":"proved"}',
                proof_artifact=None,
                critique_artifact=None,
                idempotency_key="sorry-role",
                duration_ms=0,
            )
            called = {"runner": False}

            def runner(*args):
                called["runner"] = True
                return 0, "", ""

            recorded = validate_source(
                "theorem t : (1 = 1) := sorry\n",
                validation_type="proof",
                project_dir=ROOT / "lean",
                timeout_s=5,
                runner=runner,
            )
            self.assertFalse(called["runner"])
            self.assertEqual(recorded["result"], "ill_formed")
            self.assertEqual(recorded["failure_class"], "rejected")
            engine.store.insert_validation(candidate_id=candidate["id"], idempotency_key="sorry-val", **recorded)
            self.assertEqual(engine.store.get_candidate(candidate["id"])["current_status"], "ill_formed")
            imported = validate_source(
                "import Mathlib.Data.Nat.Basic\ntheorem t : (1 = 1) := rfl\n",
                validation_type="proof",
                project_dir=ROOT / "lean",
                timeout_s=5,
                runner=runner,
            )
            self.assertEqual(imported["failure_class"], "rejected")
            self.assertFalse(called["runner"])
            samples = {
                "sorry": "theorem t : (1 = 1) := sorry\n",
                "axiom": "axiom t : (1 = 1)\n",
                "opaque": "opaque t : Nat := 1\n",
                "unsafe": "unsafe def t : Nat := 1\n",
                "#eval": "#eval 1\n",
                "run_io": "def t : Unit := run_io (pure ())\n",
                "run_cmd": "run_cmd (pure ())\n",
            }
            for name, source in samples.items():
                recorded = validate_source(
                    source,
                    validation_type="proof",
                    project_dir=ROOT / "lean",
                    timeout_s=5,
                    runner=runner,
                )
                self.assertEqual(recorded["failure_class"], "rejected", name)
                self.assertFalse(recorded["accepted"], name)
                self.assertFalse(called["runner"], name)

    def test_ast_round_trip_and_ill_formed_json(self):
        statement = Compare("eq", NatLit(2), NatLit(2))
        restored = load_expr(__import__("json").loads(canonical_json(statement)))
        self.assertEqual(structural_hash(restored), structural_hash(statement))
        with self.assertRaises(Exception):
            load_expr({"type": "NatLit", "value": -1})

    def test_quarantine_keeps_both_certificates(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            candidate = self._candidate(engine, Compare("eq", NatLit(0), NatLit(0)), stable="both")
            for name, kind in (("proof", "proof"), ("counterexample", "counterexample")):
                engine.store.insert_validation(
                    candidate_id=candidate["id"],
                    lean_version="fixture",
                    toolchain_hash="fixture",
                    validation_type=kind,
                    result="accepted",
                    accepted=True,
                    stdout="",
                    stderr="",
                    message="accepted",
                    failure_class=None,
                    idempotency_key=name,
                )
            self.assertEqual(engine.store.get_candidate(candidate["id"])["current_status"], "quarantined")
            self.assertEqual(len(engine.store.list_validations(candidate["id"])), 2)

    def test_successful_check_is_stored_and_is_not_proved(self):
        definition = next(
            item
            for item in build_batch(6, seed=1, count=1, run_id="run-1")
            if item.candidate_kind == "definition"
        )
        source = source_for(definition)
        seen = {}

        def runner(cmd, timeout, cwd, env):
            seen["path"] = Path(cmd[-1])
            self.assertIn("theorem-gen-learn-", str(seen["path"]))
            return accepting_runner(cmd, timeout, cwd, env)

        recorded = validate_source(
            source,
            validation_type="check",
            project_dir=ROOT / "lean",
            timeout_s=5,
            runner=runner,
        )
        self.assertFalse(seen["path"].exists())
        self.assertEqual(recorded["result"], "accepted")
        self.assertFalse(recorded["accepted"])
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            candidate = engine.store.upsert_candidate(
                stable_id=definition.stable_id,
                run_id="run-1",
                canonical_ast_json=definition.canonical_ast_json,
                structural_hash=definition.structural_hash,
                kind="definition",
                provenance="{}",
                curriculum_level=6,
            )
            engine.store.insert_validation(
                candidate_id=candidate["id"],
                idempotency_key="def-check",
                **recorded,
            )
            stored = engine.store.get_candidate(candidate["id"])
            self.assertEqual(stored["current_status"], "unresolved")
            row = engine.store.list_validations(candidate["id"])[0]
            self.assertEqual(row["validation_type"], "check")
            self.assertEqual(row["accepted"], 0)
            forged = dict(recorded, accepted=True)
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.insert_validation(
                    candidate_id=candidate["id"],
                    idempotency_key="forged-check",
                    **forged,
                )

    def test_level_six_records_a_definition_check_without_proving_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=1, max_steps=40)
            engine.bootstrap()
            for level in range(1, 6):
                engine.store.upsert_window(
                    run_id="run-1",
                    level=level,
                    window_index=-1,
                    metrics_json="{}",
                    gate_status="passed",
                    evaluated_count=1000,
                )
            engine.store.update_run("run-1", curriculum_level=6)
            engine.run_steps(40)
            failed = engine.store.count_where(
                "SELECT COUNT(*) FROM queue_jobs WHERE run_id=? AND state='failed'",
                ("run-1",),
            )
            self.assertEqual(failed, 0)
            rows = engine.store.list_candidates("run-1")
            definitions = [row for row in rows if row["kind"] == "definition"]
            self.assertEqual(len(definitions), 1)
            self.assertEqual(definitions[0]["current_status"], "unresolved")
            validation = engine.store.list_validations(definitions[0]["id"])[0]
            self.assertEqual(validation["validation_type"], "check")
            self.assertEqual(validation["result"], "accepted")
            self.assertEqual(validation["accepted"], 0)
            self.assertTrue(all(engine.store.list_validations(row["id"]) for row in rows))

    @unittest.skipUnless(lake_available(), "lake is not installed or lean/ is missing")
    def test_real_lean_accepts_a_proof_and_a_negation_certificate(self):
        toolchain = (ROOT / "lean" / "lean-toolchain").read_text(encoding="utf-8").strip()
        true = validate_source(
            "theorem heldout_true : (0 = 0) := rfl\n",
            validation_type="proof",
            project_dir=ROOT / "lean",
            timeout_s=120,
        )
        false = validate_source(
            negation_source("(1 = 0)", "real-false"),
            validation_type="counterexample",
            project_dir=ROOT / "lean",
            timeout_s=120,
        )
        true_negation = validate_source(
            negation_source("(0 = 0)", "real-true"),
            validation_type="counterexample",
            project_dir=ROOT / "lean",
            timeout_s=120,
        )
        typing = validate_source(
            "theorem bad : Nat := rfl\n",
            validation_type="proof",
            project_dir=ROOT / "lean",
            timeout_s=120,
        )
        definition = next(
            item
            for item in build_batch(6, seed=1, count=1, run_id="real")
            if item.candidate_kind == "definition"
        )
        checked = validate_source(
            source_for(definition),
            validation_type="check",
            project_dir=ROOT / "lean",
            timeout_s=120,
        )
        self.assertTrue(true["accepted"])
        self.assertEqual(true["result"], "accepted")
        self.assertEqual(true["lean_version"], toolchain)
        self.assertEqual(
            true["toolchain_hash"],
            hashlib.sha256(toolchain.encode("utf-8")).hexdigest(),
        )
        self.assertIn("4.34.1", true["lean_version"])
        self.assertTrue(false["accepted"])
        self.assertFalse(true_negation["accepted"])
        self.assertEqual(true_negation["result"], "rejected")
        self.assertEqual(typing["result"], "ill_formed")
        self.assertEqual(typing["failure_class"], "typing")
        syntax = validate_source(
            "theorem bad : (0 = 0) := \n",
            validation_type="proof",
            project_dir=ROOT / "lean",
            timeout_s=120,
        )
        garbage = validate_source(
            "this is not lean\n",
            validation_type="proof",
            project_dir=ROOT / "lean",
            timeout_s=120,
        )
        self.assertEqual(syntax["failure_class"], "syntax")
        self.assertEqual(syntax["result"], "ill_formed")
        self.assertEqual(derive_outcome([
            ValidationView(
                syntax["validation_type"],
                syntax["result"],
                syntax["accepted"],
                syntax["failure_class"],
            )
        ]), "ill_formed")
        self.assertEqual(garbage["failure_class"], "syntax")
        self.assertEqual(garbage["result"], "ill_formed")
        self.assertEqual(checked["result"], "accepted")
        self.assertFalse(checked["accepted"])

    @unittest.skipUnless(lake_available(), "lake is not installed or lean/ is missing")
    def test_real_lean_timeout_stays_unresolved(self):
        recorded = validate_source(
            "theorem spin : True := by\n  repeat (first | done | skip)\n",
            validation_type="proof",
            project_dir=ROOT / "lean",
            timeout_s=2,
        )
        self.assertEqual(recorded["result"], "timeout")
        self.assertFalse(recorded["accepted"])

    def _candidate(self, engine, statement, *, kind="hypothesis", stable="cand"):
        return engine.store.upsert_candidate(
            stable_id=stable,
            run_id="run-1",
            canonical_ast_json=canonical_json(statement),
            structural_hash=structural_hash(statement),
            kind=kind,
            provenance="{}",
            curriculum_level=1,
            family="eq",
            ast_size=3,
            depth=1,
            proof_method="",
        )

    def _validate(self, engine, candidate_id, source, validation_type, runner, key):
        recorded = validate_source(
            source,
            validation_type=validation_type,
            project_dir=ROOT / "lean",
            timeout_s=5,
            runner=runner,
        )
        engine.store.insert_validation(candidate_id=candidate_id, idempotency_key=key, **recorded)


class LevelOneTests(unittest.TestCase):
    def test_level_one_uses_concrete_generate_and_marks_lean_accepted_proofs(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, batch_count=2, max_steps=20)
            engine.start()
            rows = engine.store.list_candidates("run-1")
            self.assertGreaterEqual(len(rows), 1)
            self.assertTrue(all(row["current_status"] == "proved" for row in rows))
            self.assertTrue(all('"generator": "generate"' in row["provenance"] for row in rows))
            self.assertEqual(engine.slot.resident_copies, 0)
            self.assertEqual(engine.status()["learning"], False)
            self.assertEqual(engine.store.get_run("run-1")["status"], "paused")
