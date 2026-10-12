"""Replay walks proved rows already behind the forward cursor, by id."""

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
from theorem_gen.learn.dashboard import snapshot
from theorem_gen.learn.minilm import MiniLMService
from theorem_gen.learn.replay import next_replay


def _plant(engine, stable_id: str, source: str, *, origin: str = "generator", proved: bool = True, held_out: int = 0) -> None:
    now = engine.store.now()
    engine.store.conn.execute(
        """
        INSERT INTO candidates (
          stable_id, run_id, canonical_ast_json, structural_hash, kind, provenance,
          current_status, curriculum_level, ancestor_stable_id, family, ast_size, depth,
          proof_method, dependency_depth, held_out, created_at, updated_at
        ) VALUES (?, 'run-1', '{}', ?, 'theorem', ?,
          'unresolved', 1, NULL, 'eval_eq', 4, 1, 'rfl', 0, ?, ?, ?)
        """,
        (stable_id, stable_id, '{"origin": "%s"}' % origin, held_out, now, now),
    )
    row = engine.store.get_by_stable(stable_id)
    if proved:
        engine.store.insert_validation(
            candidate_id=row["id"],
            idempotency_key="val-" + stable_id,
            lean_version="fixture",
            toolchain_hash="fixture",
            validation_type="proof",
            result="accepted",
            accepted=True,
        )
    engine.queue.enqueue(
        "run-1",
        "lean_validate",
        payload={
            "candidate_id": row["id"],
            "source": source,
            "validation_type": "proof",
            "counterexample_id": None,
        },
        idempotency_key=f"run-1:lean_validate:{stable_id}:proof",
    )


class ReplayTests(unittest.TestCase):
    def test_the_walk_includes_both_origins_and_stops_at_the_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            names = ("gen-a", "model-b", "gen-c", "held", "model-e", "gen-f")
            for name in names:
                _plant(
                    engine,
                    name,
                    f"theorem {name.replace('-', '_')} : (0 = 0) := rfl\n",
                    origin="model" if name.startswith("model") else "generator",
                    held_out=1 if name == "held" else 0,
                )
            ids = {name: engine.store.get_by_stable(name)["id"] for name in names}
            rows, nxt = next_replay(engine.store.conn, "run-1", 0, ids["model-e"])
            self.assertEqual(
                [row["stable_id"] for row in rows],
                ["gen-a", "model-b", "gen-c", "model-e"],
            )
            self.assertEqual(nxt, ids["model-e"])
            self.assertNotIn("gen-f", [row["stable_id"] for row in rows])

    def test_a_hole_does_not_end_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            _plant(engine, "before", "theorem before : (0 = 0) := rfl\n")
            _plant(engine, "open", "theorem open : (1 = 1) := rfl\n", proved=False)
            _plant(engine, "after", "theorem after : (2 = 2) := rfl\n")
            until = engine.store.get_by_stable("after")["id"]
            rows, nxt = next_replay(engine.store.conn, "run-1", 0, until)
            self.assertEqual([row["stable_id"] for row in rows], ["before", "after"])
            self.assertEqual(nxt, until)

    def test_the_service_resumes_after_the_stored_id_and_then_wraps(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            names = ("gen-a", "model-b", "gen-c", "model-e", "gen-f")
            for name in names:
                origin = "model" if name.startswith("model") else "generator"
                _plant(
                    engine,
                    name,
                    f"theorem {name.replace('-', '_')} : (0 = 0) := rfl\n",
                    origin=origin,
                )
            ids = {name: engine.store.get_by_stable(name)["id"] for name in names}
            service = MiniLMService(Path(tmp) / "lm", type("W", (), {"context": 512})())
            fitted = []
            service._fit = lambda docs: fitted.extend(docs) or 0.4
            service.recent_losses = [0.7]
            service.last_loss = 0.7
            service.cursor_id = ids["model-e"]
            service._replay(engine)
            self.assertIn("gen_a", "\n".join(fitted))
            self.assertIn("model_b", "\n".join(fitted))
            self.assertNotIn("gen_f", "\n".join(fitted))
            self.assertEqual(service.replay_id, ids["model-e"])
            self.assertEqual(service.recent_losses, [0.7])
            self.assertEqual(service.last_loss, 0.7)
            self.assertEqual(service.step, 1)
            restored = MiniLMService(Path(tmp) / "lm", type("W", (), {"context": 512})())
            restored._load_state(engine.store, "run-1")
            self.assertEqual(restored.replay_id, ids["model-e"])
            fitted.clear()
            service._replay(engine)
            self.assertEqual(fitted, [])
            self.assertEqual(service.replay_id, 0)
            saved = engine.store._one("SELECT replay_id FROM lm_state WHERE run_id='run-1'")
            self.assertEqual(int(saved["replay_id"]), 0)
            info = snapshot(engine.store.path, "run-1")
            self.assertEqual(info["lm"]["replay_id"], 0)

    def test_new_sentences_stay_ahead_of_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            for index in range(4):
                _plant(engine, f"fresh-{index}", f"theorem t{index} : (0 = 0) := rfl\n")
            service = MiniLMService(Path(tmp) / "lm", type("W", (), {"context": 512})())
            service._fit = lambda docs: 0.2
            service._load_state(engine.store, "run-1")
            service.tick(engine)
            self.assertGreater(service.cursor_id, 0)
            self.assertEqual(service.replay_id, 0)
            self.assertEqual(service.step, 1)

    def test_an_open_check_does_not_start_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            _plant(engine, "only-one", "theorem only_one : (0 = 0) := rfl\n")
            _plant(engine, "still-open", "theorem still_open : (1 = 1) := rfl\n", proved=False)
            service = MiniLMService(Path(tmp) / "lm", type("W", (), {"context": 512})())
            service._fit = lambda docs: 0.2
            service._load_state(engine.store, "run-1")
            service.tick(engine)
            self.assertEqual(service.cursor_id, 0)
            self.assertEqual(service.replay_id, 0)
            self.assertEqual(service.step, 0)
