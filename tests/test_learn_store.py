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

from learn_support import make_engine
from theorem_gen.learn.checkpoint import normalize_interval
from theorem_gen.learn.clock import ManualClock
from theorem_gen.learn.errors import LearnError
from theorem_gen.learn.schema import MIGRATIONS, migration_sql
from theorem_gen.learn.store import Store


class StoreTests(unittest.TestCase):
    def test_migration_is_idempotent_and_pragmas_stick(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.store.migrate()
            self.assertEqual(
                engine.store.conn.execute("PRAGMA journal_mode").fetchone()[0],
                "wal",
            )
            self.assertEqual(engine.store.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertGreaterEqual(
                engine.store.conn.execute("PRAGMA busy_timeout").fetchone()[0],
                5000,
            )
            self.assertEqual(engine.store.integrity(), "ok")
            versions = engine.store.conn.execute("SELECT version, name FROM schema_migrations").fetchall()
            engine.store.migrate()
            again = engine.store.conn.execute("SELECT version, name FROM schema_migrations").fetchall()
            expected = [(version, name) for version, name, _filename in MIGRATIONS]
            self.assertEqual([tuple(row) for row in versions], expected)
            self.assertEqual([tuple(row) for row in again], expected)

    def test_schema_document_matches_the_applied_migration(self):
        root = Path(__file__).resolve().parents[1]
        document = (root / "docs" / "continuous-ai-schema.sql").read_text(encoding="utf-8")
        chunks = []
        for _version, _name, filename in MIGRATIONS:
            text = migration_sql(filename)
            if not text.endswith("\n"):
                text += "\n"
            chunks.append(text)
        self.assertEqual(document, "".join(chunks))

    def test_migrate_recovers_scripts_that_ran_without_version_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "learn.sqlite", clock=ManualClock())
            for _version, _name, filename in MIGRATIONS:
                store.conn.executescript(migration_sql(filename))
            self.assertEqual(store._applied_versions(), set())
            store.migrate()
            self.assertEqual(
                store._applied_versions(),
                {version for version, _name, _filename in MIGRATIONS},
            )
            store.migrate()
            self.assertEqual(store.integrity(), "ok")

    def test_transaction_rollback_keeps_the_event_log_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            before = engine.store.event_cursor("run-1")
            with self.assertRaises(RuntimeError):
                with engine.store.transaction():
                    engine.store.append_event("run-1", "probe", {"n": 1})
                    raise RuntimeError("boom")
            self.assertEqual(engine.store.event_cursor("run-1"), before)

    def test_foreign_key_and_idempotent_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.insert_attempt(
                    candidate_id=999999,
                    role="prover",
                    model_version="none",
                    prompt_hash="abc",
                    raw_response="{}",
                    proof_artifact=None,
                    critique_artifact=None,
                    idempotency_key="missing-candidate",
                    duration_ms=0,
                )
            candidate = engine.store.upsert_candidate(
                stable_id="one",
                run_id="run-1",
                canonical_ast_json="{}",
                structural_hash="h",
                kind="hypothesis",
                provenance="{}",
                curriculum_level=1,
            )
            first = engine.store.insert_attempt(
                candidate_id=candidate["id"],
                role="prover",
                model_version="none",
                prompt_hash="abc",
                raw_response="{}",
                proof_artifact=None,
                critique_artifact=None,
                idempotency_key="attempt-1",
                duration_ms=0,
            )
            second = engine.store.insert_attempt(
                candidate_id=candidate["id"],
                role="prover",
                model_version="none",
                prompt_hash="abc",
                raw_response="other",
                proof_artifact=None,
                critique_artifact=None,
                idempotency_key="attempt-1",
                duration_ms=0,
            )
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(second["raw_response"], "{}")
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.conn.execute("UPDATE attempts SET raw_response='x'")
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.conn.execute("DELETE FROM events")

    def test_checkpoint_interval_bounds(self):
        self.assertEqual(normalize_interval(300), 300)
        self.assertEqual(normalize_interval(600), 600)
        for bad in (299, 601, True, 300.0):
            with self.assertRaises(LearnError):
                normalize_interval(bad)

    def test_status_flags_and_cross_candidate_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.upsert_candidate(
                    stable_id="forged",
                    run_id="run-1",
                    canonical_ast_json="{}",
                    structural_hash="h-forged",
                    kind="hypothesis",
                    provenance="{}",
                    current_status="proved",
                    curriculum_level=1,
                )
            candidate = engine.store.upsert_candidate(
                stable_id="one",
                run_id="run-1",
                canonical_ast_json="{}",
                structural_hash="h-one",
                kind="hypothesis",
                provenance="{}",
                curriculum_level=1,
            )
            other = engine.store.upsert_candidate(
                stable_id="two",
                run_id="run-1",
                canonical_ast_json="{}",
                structural_hash="h-two",
                kind="hypothesis",
                provenance="{}",
                curriculum_level=1,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.conn.execute(
                    "UPDATE candidates SET current_status='proved' WHERE id=?",
                    (candidate["id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.conn.execute(
                    "UPDATE candidates SET canonical_ast_json=? WHERE id=?",
                    ('{"rewritten":true}', candidate["id"]),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.conn.execute(
                    "UPDATE candidates SET structural_hash='rewritten', ast_size=99 WHERE id=?",
                    (candidate["id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.insert_validation(
                    candidate_id=candidate["id"],
                    lean_version="fixture",
                    toolchain_hash="fixture",
                    validation_type="proof",
                    result="rejected",
                    accepted=True,
                    stdout="",
                    stderr="",
                    message="inconsistent",
                    failure_class=None,
                    idempotency_key="inconsistent",
                )
            attempt = engine.store.insert_attempt(
                candidate_id=candidate["id"],
                role="prover",
                model_version="none",
                prompt_hash="abc",
                raw_response="{}",
                proof_artifact=None,
                critique_artifact=None,
                idempotency_key="attempt-owner",
                duration_ms=0,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.insert_validation(
                    candidate_id=other["id"],
                    attempt_id=attempt["id"],
                    lean_version="fixture",
                    toolchain_hash="fixture",
                    validation_type="proof",
                    result="accepted",
                    accepted=True,
                    stdout="",
                    stderr="",
                    message="wrong attempt",
                    failure_class=None,
                    idempotency_key="wrong-attempt",
                )
            certificate = engine.store.insert_validation(
                candidate_id=candidate["id"],
                lean_version="fixture",
                toolchain_hash="fixture",
                validation_type="counterexample",
                result="accepted",
                accepted=True,
                stdout="",
                stderr="",
                message="cert",
                failure_class=None,
                idempotency_key="cert-a",
            )
            witness = engine.store.insert_counterexample(
                candidate_id=other["id"],
                assignment_json="{}",
                instantiated_prop="(1 = 0)",
                proposed_by="python",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.set_certificate(witness["id"], certificate["id"])
            with self.assertRaises(sqlite3.IntegrityError):
                engine.store.conn.execute(
                    """
                    INSERT INTO counterexamples (
                      candidate_id, assignment_json, instantiated_prop,
                      lean_certificate_id, proposed_by, created_at
                    ) VALUES (?, '{}', '(1 = 0)', ?, 'python', ?)
                    """,
                    (other["id"], certificate["id"], engine.store.now()),
                )
            inserted = engine.store.conn.execute(
                """
                INSERT INTO counterexamples (
                  candidate_id, assignment_json, instantiated_prop,
                  lean_certificate_id, proposed_by, created_at
                ) VALUES (?, '{}', '(0 = 1)', ?, 'python', ?)
                """,
                (candidate["id"], certificate["id"], engine.store.now()),
            )
            self.assertGreater(inserted.lastrowid, 0)
            with self.assertRaises(LearnError):
                engine.store.update_run("run-1", curriculum_level=4)
            self.assertEqual(engine.store.get_candidate(other["id"])["current_status"], "unresolved")

    def test_two_connections_share_one_idempotency_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.bootstrap()
            candidate = engine.store.upsert_candidate(
                stable_id="one",
                run_id="run-1",
                canonical_ast_json="{}",
                structural_hash="h",
                kind="hypothesis",
                provenance="{}",
                curriculum_level=1,
            )
            from theorem_gen.learn.store import Store

            other = Store(engine.store.path, clock=engine.store.clock)
            other.migrate()
            payload = dict(
                candidate_id=candidate["id"],
                role="prover",
                model_version="none",
                prompt_hash="abc",
                proof_artifact=None,
                critique_artifact=None,
                idempotency_key="shared-attempt",
                duration_ms=0,
            )
            first = engine.store.insert_attempt(raw_response="first", **payload)
            second = other.insert_attempt(raw_response="second", **payload)
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(second["raw_response"], "first")
            other.close()
