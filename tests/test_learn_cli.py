import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for item in (str(ROOT), str(TESTS)):
    if item not in sys.path:
        sys.path.insert(0, item)

from argparse import Namespace

from theorem_gen.learn.__main__ import _resume_limits, main
from theorem_gen.learn.memory import RAM_BUDGET_BYTES, report


class CliTests(unittest.TestCase):
    def test_start_pause_resume_status_and_replay_without_a_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "learn.sqlite"
            started = self._run(
                [
                    "start",
                    "--run-id",
                    "cli",
                    "--curriculum",
                    "1",
                    "--db",
                    str(database),
                    "--seed",
                    "3",
                    "--count",
                    "1",
                    "--max-steps",
                    "0",
                ]
            )
            self.assertEqual(started[0], 0)
            self.assertIn("status: paused", started[1])
            self.assertIn("curriculum_level: 1", started[1])
            self.assertIn("learning: no", started[1])
            status = self._run(["status", "--run-id", "cli", "--db", str(database)])
            self.assertEqual(status[0], 0)
            self.assertIn("checkpoint_seq: ", status[1])
            paused = self._run(["pause", "--run-id", "cli", "--db", str(database)])
            self.assertEqual(paused[0], 0)
            resumed = self._run(
                ["resume", "--run-id", "cli", "--db", str(database), "--max-steps", "0"]
            )
            self.assertEqual(resumed[0], 0)
            self.assertIn("status: paused", resumed[1])
            replayed = self._run(
                [
                    "replay",
                    "--run-id",
                    "cli",
                    "--db",
                    str(database),
                    "--from-checkpoint",
                    "1",
                ]
            )
            self.assertEqual(replayed[0], 0)
            self.assertIn("replay_match: yes", replayed[1])
            refused = self._run(
                [
                    "start",
                    "--run-id",
                    "skipped",
                    "--curriculum",
                    "4",
                    "--db",
                    str(Path(tmp) / "other.sqlite"),
                    "--max-steps",
                    "0",
                ]
            )
            self.assertEqual(refused[0], 1)
            self.assertIn("curriculum level 1", refused[2])
            missing = self._run(["status", "--run-id", "missing", "--db", str(database)])
            self.assertEqual(missing[0], 1)
            self.assertIn("unknown run", missing[2])
            again = self._run(
                [
                    "start",
                    "--run-id",
                    "cli",
                    "--db",
                    str(database),
                    "--max-steps",
                    "0",
                ]
            )
            self.assertEqual(again[0], 1)
            self.assertIn("already exists", again[2])
            out_of_range = self._run(
                [
                    "replay",
                    "--run-id",
                    "cli",
                    "--db",
                    str(database),
                    "--from-checkpoint",
                    "99",
                ]
            )
            self.assertEqual(out_of_range[0], 1)
            self.assertIn("checkpoint not found", out_of_range[2])
            conflict = self._run(
                [
                    "replay",
                    "--run-id",
                    "cli",
                    "--db",
                    str(database),
                    "--from-checkpoint",
                    "1",
                ]
            )
            self.assertEqual(conflict[0], 1)
            self.assertIn("already exists", conflict[2])
            bounded = self._run(
                [
                    "start",
                    "--run-id",
                    "bounds",
                    "--db",
                    str(Path(tmp) / "bounds.sqlite"),
                    "--max-steps",
                    "0",
                    "--checkpoint-interval",
                    "10",
                ]
            )
            self.assertEqual(bounded[0], 1)
            corrupt_path = Path(tmp) / "corrupt.sqlite"
            corrupt_path.write_bytes(b"this is not a sqlite database")
            corrupt = self._run(["status", "--run-id", "cli", "--db", str(corrupt_path)])
            self.assertEqual(corrupt[0], 1)

    def test_resume_limits_keep_a_continuous_run_unbounded(self):
        steps, until, refill = _resume_limits(
            Namespace(until_pause=False, max_steps=None),
            {"until_pause": True},
        )
        self.assertIsNone(steps)
        self.assertTrue(until)
        self.assertTrue(refill)
        bounded, until_bounded, refill_bounded = _resume_limits(
            Namespace(until_pause=False, max_steps=None),
            {"until_pause": False},
        )
        self.assertEqual((bounded, until_bounded, refill_bounded), (50, False, True))
        explicit, until_explicit, refill_explicit = _resume_limits(
            Namespace(until_pause=False, max_steps=0),
            {"until_pause": True},
        )
        self.assertEqual((explicit, until_explicit, refill_explicit), (0, False, True))

    def test_memory_report_stays_inside_the_budget_without_weights(self):
        info = report()
        self.assertLess(info["peak_rss_bytes"], RAM_BUDGET_BYTES)
        self.assertFalse(info["weights_loaded"])
        self.assertEqual(info["resident_copies"], 0)
        code, stdout, _stderr = self._run(["memory"])
        self.assertEqual(code, 0)
        self.assertIn("weights_loaded: no", stdout)
        self.assertIn("peak_rss_bytes", stdout)
        self.assertIn("within_budget: yes", stdout)

    def _run(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()
