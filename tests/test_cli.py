import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from theorem_gen.__main__ import main
from theorem_gen.verify import VerificationReport


class CliTests(unittest.TestCase):
    def test_generate_writes_the_deterministic_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "Out.lean"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "generate",
                        "--seed",
                        "1",
                        "--count",
                        "2",
                        "--rules",
                        "add_zero",
                        "--out",
                        str(destination),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("generated 2 theorems", stdout.getvalue())
            text = destination.read_text(encoding="utf-8")
            self.assertIn("((8 + 0) = 8)", text)
            self.assertIn("((7 + 0) = 7)", text)

    def test_generation_error_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "Out.lean"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = main(
                    [
                        "generate",
                        "--seed",
                        "1",
                        "--count",
                        "2",
                        "--max-literal",
                        "0",
                        "--rules",
                        "le_refl",
                        "--out",
                        str(destination),
                    ]
                )
            self.assertEqual(code, 1)
            self.assertFalse(destination.exists())
            self.assertIn("unique", stderr.getvalue())

    def test_allow_duplicates_permits_a_repeated_fact(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "Out.lean"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "generate",
                        "--seed",
                        "1",
                        "--count",
                        "3",
                        "--max-literal",
                        "0",
                        "--rules",
                        "le_refl",
                        "--allow-duplicates",
                        "--out",
                        str(destination),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(destination.read_text(encoding="utf-8").count("(0 <= 0)"), 3)

    def test_verify_exit_codes(self):
        cases = (
            ("proved", 0),
            ("failed", 2),
            ("timeout", 3),
            ("unavailable", 4),
        )
        for status, expected in cases:
            with self.subTest(status=status):
                def verify_path(path, timeout, status=status):
                    self.assertTrue(path.is_file())
                    message = "The result is inconclusive." if status == "timeout" else status
                    return VerificationReport(
                        status=status,
                        exit_code=None,
                        stdout="",
                        stderr="",
                        message=message,
                        failure_class=None,
                    )

                stdout = io.StringIO()
                with tempfile.TemporaryDirectory() as temporary:
                    destination = Path(temporary) / "Out.lean"
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "generate",
                                "--seed",
                                "1",
                                "--count",
                                "1",
                                "--rules",
                                "add_zero",
                                "--out",
                                str(destination),
                                "--verify",
                                "--timeout",
                                "9",
                            ],
                            verify_path=verify_path,
                        )
                self.assertEqual(code, expected)
                if status == "timeout":
                    self.assertIn("inconclusive", stdout.getvalue())

    def test_module_entrypoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "T.lean"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "theorem_gen",
                    "generate",
                    "--seed",
                    "1",
                    "--count",
                    "1",
                    "--rules",
                    "add_zero",
                    "--out",
                    str(destination),
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("((8 + 0) = 8)", destination.read_text(encoding="utf-8"))

    def test_help_and_missing_command(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as help_exit:
                main(["generate", "--help"])
        self.assertEqual(help_exit.exception.code, 0)
        self.assertIn("--seed", stdout.getvalue())
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as missing:
                main([])
        self.assertEqual(missing.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
