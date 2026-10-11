import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.config import GeneratorConfig
from theorem_gen.generate import generate
from theorem_gen.verify import (
    MAX_CAPTURE,
    build_lean_env,
    exit_code_for,
    find_lake,
    run_process,
    verify_source,
    verify_theorems,
)


def proved_runner(cmd, timeout, cwd, env):
    return 0, "", ""


class VerifyTests(unittest.TestCase):
    def test_exit_zero_is_proved_even_if_stdout_contains_error(self):
        def runner(cmd, timeout, cwd, env):
            return 0, "error: this string is not a compiler status\n", ""

        report = self.verify("theorem t : (0 = 0) := rfl\n", runner)
        self.assertEqual(report.status, "proved")
        self.assertIsNone(report.failure_class)
        self.assertIn("exit code 0", report.message)
        self.assertEqual(exit_code_for(report), 0)

    def test_non_proposition_is_typing_even_with_definitional_text(self):
        stderr = (
            "error: Not a definitional equality: the conclusion should be an equality, but is `Nat`\n"
            "error: Type mismatch\n"
            "error: type of theorem `bad` is not a proposition\n"
            "  Nat\n"
        )
        report = self.verify("theorem bad : Nat := rfl\n", lambda *args: (1, "", stderr))
        self.assertEqual(report.failure_class, "typing")

    def test_lean_syntax_phrases_beat_an_unsolved_goal(self):
        end = self.verify(
            "theorem bad : (0 = 0) := \n",
            lambda *args: (1, "", "error: unexpected end of input\n"),
        )
        garbage = self.verify(
            "this is not lean\n",
            lambda *args: (1, "", "error: unexpected identifier; expected command\n"),
        )
        mixed = self.verify(
            "theorem bad : (0 = 0) := by\n  ???\n",
            lambda *args: (
                1,
                "",
                "error: unsolved goals\n⊢ 0 = 0\nerror: unexpected token '?'; expected 'binder_predicate'\n",
            ),
        )
        self.assertEqual(end.failure_class, "syntax")
        self.assertEqual(garbage.failure_class, "syntax")
        self.assertEqual(mixed.failure_class, "syntax")

    def test_definitional_failure_is_a_proof_failure_despite_type_mismatch_text(self):
        stderr = (
            "error: Not a definitional equality: the left-hand side\n"
            "  1\n"
            "is not definitionally equal to the right-hand side\n"
            "  0\n"
            "error: Type mismatch\n"
        )
        report = self.verify("theorem t : (1 = 0) := rfl\n", lambda *args: (1, "", stderr))
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.failure_class, "proof")
        self.assertIn("Not a definitional equality", report.message)
        self.assertEqual(exit_code_for(report), 2)

    def test_syntax_and_typing_are_separate_from_proof(self):
        syntax = self.verify(
            "theorem t : (1 = := rfl\n",
            lambda *args: (1, "", "error: unexpected token ':='; expected term\n"),
        )
        typing = self.verify(
            "theorem t : (True + 1 = 1) := rfl\n",
            lambda *args: (
                1,
                "",
                "error(lean.synthInstanceFailed): failed to synthesize instance of type class\n",
            ),
        )
        other = self.verify(
            "theorem t : (1 = 1) := rfl\n",
            lambda *args: (1, "", "error(lean.unknownIdentifier): Unknown identifier `this`\n"),
        )
        decided_false = self.verify(
            "theorem t : (0 < 0) := by\n  decide\n",
            lambda *args: (
                1,
                "error: Tactic `decide` proved that the proposition\n  0 < 0\nis false\n",
                "",
            ),
        )
        self.assertEqual(syntax.failure_class, "syntax")
        self.assertEqual(typing.failure_class, "typing")
        self.assertEqual(other.failure_class, "other")
        self.assertEqual(decided_false.failure_class, "proof")
        self.assertEqual(decided_false.status, "failed")

    def test_sorry_warning_with_exit_zero_is_not_proved(self):
        report = self.verify(
            "theorem t : (1 = 1) := rfl\n",
            lambda *args: (0, "", "warning: declaration uses `sorry`\n"),
        )
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.failure_class, "proof")
        self.assertNotEqual(report.status, "proved")

    def test_forbidden_source_is_not_executed(self):
        called = []

        def runner(*args):
            called.append(args)
            return 0, "", ""

        report = self.verify("theorem t : (1 = 0) := sorry\n", runner)
        self.assertEqual(called, [])
        self.assertEqual(report.status, "failed")
        self.assertEqual(report.failure_class, "rejected")
        self.assertIn("sorry", report.message)

    def test_signal_death_is_inconclusive(self):
        report = self.verify(
            "theorem t : (0 = 0) := rfl\n",
            lambda *args: (-9, "", "Killed"),
        )
        self.assertEqual(report.status, "timeout")
        self.assertEqual(report.exit_code, -9)
        self.assertIn("inconclusive", report.message)
        self.assertNotIn("false", report.message.lower())
        self.assertNotIn("rejected", report.message.lower())
        self.assertEqual(exit_code_for(report), 3)

    def test_timeout_is_inconclusive(self):
        def runner(cmd, timeout, cwd, env):
            raise subprocess.TimeoutExpired(cmd, timeout)

        report = self.verify("theorem t : (0 = 0) := rfl\n", runner)
        self.assertEqual(report.status, "timeout")
        self.assertIn("inconclusive", report.message)
        self.assertNotIn("false", report.message.lower())
        self.assertEqual(exit_code_for(report), 3)

    def test_missing_and_unexpected_process_errors_are_unavailable(self):
        def missing_runner(*args):
            raise FileNotFoundError("lake")

        def broken_runner(*args):
            raise OSError("boom")

        missing_report = self.verify("theorem t : (0 = 0) := rfl\n", missing_runner)
        broken_report = self.verify("theorem t : (0 = 0) := rfl\n", broken_runner)
        self.assertEqual(missing_report.status, "unavailable")
        self.assertEqual(broken_report.status, "unavailable")
        self.assertIn("boom", broken_report.message)
        self.assertEqual(exit_code_for(missing_report), 4)

    def test_timeout_must_be_positive(self):
        called = []

        def runner(*args):
            called.append(args)
            return 0, "", ""

        with self.assertRaises(ValueError):
            self.verify("theorem t : (0 = 0) := rfl\n", runner, timeout_s=0)
        self.assertEqual(called, [])

    def test_command_is_an_argument_list(self):
        seen = {}

        def runner(cmd, timeout, cwd, env):
            seen["cmd"] = cmd
            seen["timeout"] = timeout
            seen["cwd"] = cwd
            seen["env"] = env
            return 0, "", ""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "lean"
            project.mkdir()
            lake = root / ".toolchains" / "elan" / "bin" / "lake"
            lake.parent.mkdir(parents=True)
            lake.write_text("", encoding="utf-8")
            destination = root / "T.lean"
            report = verify_source(
                "theorem t : (0 = 0) := rfl\n",
                destination=destination,
                project_dir=project,
                timeout_s=12,
                runner=runner,
            )
            self.assertEqual(report.status, "proved")
            self.assertIsInstance(seen["cmd"], list)
            self.assertEqual(seen["cmd"][0], str(lake.resolve()))
            self.assertEqual(
                seen["cmd"][1:5], ["--dir", str(project.resolve()), "env", "lean"]
            )
            self.assertEqual(seen["cmd"][5], str(destination.resolve()))
            self.assertEqual(seen["timeout"], 12)
            self.assertEqual(seen["cwd"], project.resolve())
            self.assertEqual(
                seen["env"]["ELAN_HOME"],
                str((root / ".toolchains" / "elan").resolve()),
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), "theorem t : (0 = 0) := rfl\n")

    def test_relative_destination_is_made_absolute_before_changing_cwd(self):
        seen = {}

        def runner(cmd, timeout, cwd, env):
            seen["cmd"] = cmd
            seen["cwd"] = cwd
            return 0, "", ""

        destination = Path("lean/TheoremGen/Relative.lean")
        report = verify_source(
            "theorem t : (0 = 0) := rfl\n",
            destination=destination,
            project_dir=ROOT / "lean",
            runner=runner,
            lake_bin=Path("/tmp/lake"),
        )
        try:
            self.assertEqual(report.status, "proved")
            self.assertTrue(Path(seen["cmd"][-1]).is_absolute())
            self.assertEqual(Path(seen["cmd"][-1]), ROOT / destination)
            self.assertEqual(seen["cwd"], ROOT / "lean")
        finally:
            (ROOT / destination).unlink(missing_ok=True)

    def test_large_compiler_output_is_truncated(self):
        report = self.verify(
            "theorem t : (1 = 0) := rfl\n",
            lambda *args: (1, "x" * (MAX_CAPTURE + 10), "y"),
        )
        self.assertLessEqual(len(report.stdout), MAX_CAPTURE)
        self.assertIn("truncated", report.message)

    def test_verify_theorems_copies_status_and_keeps_the_original(self):
        config = GeneratorConfig(seed=1, count=1, rules=("add_zero",))
        theorems = generate(config)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "lean"
            project.mkdir()
            destination = root / "T.lean"
            report, marked = verify_theorems(
                theorems,
                config,
                destination=destination,
                project_dir=project,
                runner=proved_runner,
                lake_bin=Path("/tmp/lake"),
            )
            written = destination.read_text(encoding="utf-8")
        self.assertEqual(report.status, "proved")
        self.assertEqual(theorems[0].metadata.verification, "unverified")
        self.assertEqual(marked[0].metadata.verification, "proved")
        self.assertIn("((8 + 0) = 8)", written)

    def test_find_lake_and_env_use_the_local_toolchain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "lean"
            project.mkdir()
            lake = root / ".toolchains" / "elan" / "bin" / "lake"
            lake.parent.mkdir(parents=True)
            lake.write_text("", encoding="utf-8")
            self.assertEqual(find_lake(project, path_lookup=lambda name: None), lake)
            env = build_lean_env(project)
            self.assertEqual(env["ELAN_HOME"], str(root / ".toolchains" / "elan"))
            self.assertTrue(env["PATH"].startswith(str(lake.parent)))
            isolated = root / "isolated" / "lean"
            isolated.mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                find_lake(isolated, path_lookup=lambda name: None)

    def test_run_process_decodes_unexpected_bytes_and_times_out(self):
        code, stdout, stderr = run_process(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([255, 254]))"],
            timeout=5,
            cwd=ROOT,
            env=os.environ.copy(),
            cpu_seconds=None,
        )
        self.assertEqual(code, 0)
        self.assertIn("\ufffd", stdout)
        self.assertEqual(stderr, "")

        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                timeout=0.4,
                cwd=ROOT,
                env=os.environ.copy(),
                cpu_seconds=None,
            )
        self.assertLess(time.monotonic() - started, 5)

    def test_run_process_applies_cpu_limit(self):
        code, stdout, stderr = run_process(
            [
                sys.executable,
                "-c",
                "import resource,sys; sys.stdout.write(str(resource.getrlimit(resource.RLIMIT_CPU)[0]))",
            ],
            timeout=5,
            cwd=ROOT,
            env=os.environ.copy(),
            cpu_seconds=3,
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout.strip(), "3")

    def verify(self, source, runner, timeout_s=5):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "lean"
            project.mkdir()
            destination = root / "T.lean"
            return verify_source(
                source,
                destination=destination,
                project_dir=project,
                timeout_s=timeout_s,
                runner=runner,
                lake_bin=Path("/tmp/lake"),
            )


if __name__ == "__main__":
    unittest.main()
