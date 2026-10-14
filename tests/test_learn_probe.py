"""The hundred-draw rhythm and the nucleus pick."""

from __future__ import annotations

import sys
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
from theorem_gen.learn.minilm import BYTE, END, PROPOSE_TAG, encode
from theorem_gen.learn.probe import (
    DRAW_COUNT,
    FORMULA_DRAW,
    REPAIR_WIDTH,
    formula_progress,
    lean_error_at,
    next_draw,
    open_repairs,
    pick_token,
)


class PickTests(unittest.TestCase):
    def test_temperature_zero_is_the_largest_score(self):
        self.assertEqual(pick_token([0.1, 3.0, 2.9], 0.0, 0.9, 0.99), 1)

    def test_a_narrow_nucleus_keeps_the_peak(self):
        self.assertEqual(pick_token([0.0, 5.0, 1.0], 1.0, 0.5, 0.99), 1)

    def test_a_wide_draw_can_leave_the_peak(self):
        chosen = pick_token([0.0, 5.0, 1.0], 1.0, 1.0, 0.999)
        self.assertEqual(chosen, 0)


class DrawTests(unittest.TestCase):
    def test_the_hundred_come_before_the_argmax(self):
        draw_left, greedy_left = DRAW_COUNT, 1
        kinds = []
        for _ in range(DRAW_COUNT + 1):
            kind, draw_left, greedy_left = next_draw(draw_left, greedy_left)
            kinds.append(kind)
        self.assertEqual(kinds.count("sample"), DRAW_COUNT)
        self.assertEqual(kinds[-1], "argmax")
        self.assertEqual(next_draw(draw_left, greedy_left), ("", 0, 0))


class RhythmTests(unittest.TestCase):
    def _service(self):
        service = MiniLMService(Path("var") / "unused-probe", probe=True)
        service._save_state = lambda *_args, **_kwargs: None
        return service

    def _engine(self):
        return type("E", (), {"store": None, "run_id": "run-1", "seed": 1})()

    def test_a_finished_run_keeps_reading_and_does_not_draw(self):
        service = self._service()
        service.phase = "done"
        service.cycles = 200
        calls = []
        service._train_page = lambda *_args, **_kwargs: calls.append("train") or "trained"
        service._replay = lambda *_args, **_kwargs: calls.append("replay") or "trained"
        service._sample = lambda *_args, **_kwargs: calls.append("sample")
        service._probe_tick(self._engine())
        self.assertEqual(calls, ["train"])
        self.assertEqual(service.phase, "done")
        self.assertEqual(service.draw_left, 0)

    def test_a_finished_run_replays_when_the_page_is_idle(self):
        service = self._service()
        service.phase = "done"
        calls = []
        service._train_page = lambda *_args, **_kwargs: calls.append("train") or "idle"
        service._replay = lambda *_args, **_kwargs: calls.append("replay") or "trained"
        service._sample = lambda *_args, **_kwargs: calls.append("sample")
        service._probe_tick(self._engine())
        self.assertEqual(calls, ["train", "replay"])
        self.assertEqual(service.phase, "done")

    def test_an_idle_corpus_does_not_draw(self):
        service = self._service()
        service._train_page = lambda *_args, **_kwargs: "idle"
        service._replay = lambda *_args, **_kwargs: "idle"
        service._probe_tick(self._engine())
        self.assertEqual(service.phase, "train")
        self.assertEqual(service.draw_left, 0)

    def test_one_trained_step_opens_the_hundred(self):
        service = self._service()
        service._train_page = lambda *_args, **_kwargs: "trained"
        service._replay = lambda *_args, **_kwargs: "idle"
        service._probe_tick(self._engine())
        self.assertEqual(service.phase, "draw")
        self.assertEqual((service.draw_left, service.greedy_left), (DRAW_COUNT, 1))

    def test_samples_finish_before_the_argmax_and_then_the_cycle_waits(self):
        service = self._service()
        seen = []
        service._sample = lambda _engine, decoder="argmax": seen.append(decoder)
        service.phase = "draw"
        service.draw_left = 1
        service.greedy_left = 1
        engine = self._engine()
        service._probe_tick(engine)
        service._probe_tick(engine)
        self.assertEqual(seen, ["sample", "argmax"])
        self.assertEqual(service.phase, "wait")

    def test_a_judged_cycle_with_nothing_accepted_returns_to_training(self):
        service = self._service()
        service.phase = "wait"
        service._cycle_waiting = lambda _engine: False
        service._teach_one = lambda _engine: False
        engine = self._engine()
        service._probe_tick(engine)
        self.assertEqual(service.phase, "teach")
        service._probe_tick(engine)
        self.assertEqual(service.cycles, 1)
        self.assertEqual(service.phase, "train")


class ProbePageTests(unittest.TestCase):
    def test_the_page_counts_the_hundred_apart_from_the_argmax(self):
        with __import__("tempfile").TemporaryDirectory() as tmp:
            engine = make_engine(tmp, max_steps=0)
            engine.start()
            service = MiniLMService(Path(tmp) / "lm", probe=True)
            service.phase = "draw"
            service.cycle = 0
            service.cycles = 0
            service.draw_left = 97
            service._save_state(engine.store, "run-1")
            now = "1000"
            for index, (decoder, disposition, equation) in enumerate(
                (
                    ("sample", "duplicate", "same"),
                    ("sample", "duplicate", "same"),
                    ("sample", "ill_formed", "name-only"),
                    ("sample", "proved", "0 = 0"),
                    ("argmax", "duplicate", "greedy-name"),
                )
            ):
                engine.store.conn.execute(
                    """
                    INSERT INTO model_attempts (
                      run_id, equation, equation_hash, origin, disposition, candidate_id,
                      created_at, decoder, cycle
                    ) VALUES ('run-1', ?, ?, 'model', ?, NULL, ?, ?, 0)
                    """,
                    (equation, f"hash-{index}", disposition, now, decoder),
                )
            info = snapshot(engine.store.path, "run-1", now=2000)
            probe = info["probe"]
            self.assertTrue(probe["on"])
            self.assertEqual(probe["distinct"], 3)
            self.assertEqual(probe["sample_n"], 4)
            self.assertEqual(probe["accepted"], 1)
            self.assertEqual(probe["greedy"], "Repeated something we already had")
            self.assertEqual(info["attempts"]["duplicate"]["all"], 2)
            self.assertEqual(info["attempts"]["proved"]["all"], 1)


class RepairRuleTests(unittest.TestCase):
    def test_progress_is_the_formula_characters_before_the_error(self):
        body = "abXcd"
        source = f"theorem model_eq : {body} := rfl\n"
        start = source.index(body)
        message = f"Candidate.lean:1:{start + 3}: error: unexpected token"
        at = lean_error_at(message, source)
        self.assertEqual(formula_progress(source, body, at), 2)
        self.assertIsNone(formula_progress(source, body, source.index("rfl")))
        self.assertIsNone(formula_progress(source, body, 1))

    def test_a_hand_written_theorem_uses_the_same_span(self):
        body = "abXcd"
        source = f"theorem t : {body} := rfl\n"
        start = source.index(body)
        at = lean_error_at(f"Candidate.lean:1:{start + 4}: error: x", source)
        self.assertEqual(formula_progress(source, body, at), 3)

    def test_the_first_round_is_four_and_the_second_needs_a_longer_prefix(self):
        self.assertEqual(open_repairs(0, 0, []), 0)
        self.assertEqual(open_repairs(0, 4, []), REPAIR_WIDTH)
        self.assertEqual(open_repairs(1, 4, [4, 3]), 0)
        self.assertEqual(open_repairs(1, 4, [6]), REPAIR_WIDTH)
        self.assertEqual(open_repairs(2, 6, [9]), 0)


class RepairRhythmTests(unittest.TestCase):
    def _service(self):
        service = MiniLMService(Path("var") / "unused-repair", repair=True)
        service._save_state = lambda *_args, **_kwargs: None
        return service

    def _engine(self):
        return type("E", (), {"store": None, "run_id": "run-3", "seed": 1})()

    def test_one_trained_step_opens_twenty_formulas(self):
        service = self._service()
        service._train_page = lambda *_args, **_kwargs: "trained"
        service._replay = lambda *_args, **_kwargs: "idle"
        service._probe_tick(self._engine())
        self.assertEqual(service.phase, "draw")
        self.assertEqual((service.draw_left, service.greedy_left), (FORMULA_DRAW, 1))
        self.assertNotEqual(FORMULA_DRAW, DRAW_COUNT)

    def test_a_judged_twenty_opens_four_endings_from_the_furthest_prefix(self):
        service = self._service()
        service.phase = "wait"
        service._cycle_waiting = lambda _engine: False
        service._cycle_proved = lambda _engine: False
        service._best_progress = lambda _engine, ply: {"equation": "abcdEFG", "error_at": 4}
        service._probe_tick(self._engine())
        self.assertEqual(service.phase, "repair")
        self.assertEqual(service.repair_left, REPAIR_WIDTH)
        self.assertEqual(service.repair_prefix, "abcd")
        self.assertEqual(service.repair_ply, 1)

    def test_an_accepted_formula_skips_endings(self):
        service = self._service()
        service.phase = "wait"
        service._cycle_waiting = lambda _engine: False
        service._cycle_proved = lambda _engine: True
        service._probe_tick(self._engine())
        self.assertEqual(service.phase, "teach")
        self.assertEqual(service.repair_left, 0)

    def test_the_second_round_opens_only_when_an_ending_got_further(self):
        service = self._service()
        service.phase = "wait"
        service.repair_ply = 1
        service.repair_at = 4
        service.repair_prefix = "abcd"
        service._cycle_waiting = lambda _engine: False
        service._cycle_proved = lambda _engine: False
        service._progress_values = lambda _engine, ply: [4, 3]
        service._probe_tick(self._engine())
        self.assertEqual(service.phase, "teach")

        service.phase = "wait"
        service.repair_ply = 1
        service.repair_at = 4
        service._progress_values = lambda _engine, ply: [6]
        service._best_progress = lambda _engine, ply: {"equation": "abcdefZZ", "error_at": 6}
        service._probe_tick(self._engine())
        self.assertEqual(service.phase, "repair")
        self.assertEqual(service.repair_left, REPAIR_WIDTH)
        self.assertEqual(service.repair_prefix, "abcdef")
        self.assertEqual(service.repair_ply, 2)

    def test_an_ending_continues_the_kept_letters_and_still_goes_to_lean_as_a_formula(self):
        service = self._service()
        service.seen_ready = True
        captured = {}

        def enqueue(_engine, body, digest, source):
            captured["body"] = body
            captured["source"] = source
            return "queued"

        service._enqueue = enqueue
        service._hash_known = lambda *_args: False
        service._record = lambda *_args, **_kwargs: None

        class Trainer:
            def complete(self, prompt, max_new=96, temperature=0.0, top_p=1.0):
                self.prompt = list(prompt)
                return list(prompt) + [BYTE + ord("Z"), END]

        trainer = Trainer()
        service.trainer = trainer
        encoded, length = encode(f"{PROPOSE_TAG}\nab", 64)
        service._sample(
            self._engine(),
            decoder="sample",
            prompt_ids=encoded[:length],
            prefix="ab",
        )
        self.assertEqual(trainer.prompt[0], encoded[0])
        self.assertEqual(captured["body"], "abZ")
        self.assertTrue(captured["source"].startswith("theorem model_eq : abZ := rfl"))
