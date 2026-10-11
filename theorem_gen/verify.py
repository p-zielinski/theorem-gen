"""Run Lean on a generated file and classify the process result."""

from __future__ import annotations

import math
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from theorem_gen.config import GeneratorConfig
from theorem_gen.export_lean import export_module
from theorem_gen.theorem import Theorem

MAX_CAPTURE = 64_000

_STATUSES = {"proved", "failed", "timeout", "unavailable"}
_FAILURE_CLASSES = {None, "syntax", "typing", "proof", "rejected", "other"}
_FORBIDDEN = (
    (re.compile(r"#eval\b"), "#eval"),
    (re.compile(r"\brun_io\b"), "run_io"),
    (re.compile(r"\brun_cmd\b"), "run_cmd"),
    (re.compile(r"\bsorry\b"), "sorry"),
    (re.compile(r"\bunsafe\b"), "unsafe"),
    (re.compile(r"\baxiom\b"), "axiom"),
    (re.compile(r"\bopaque\b"), "opaque"),
)


@dataclass(frozen=True)
class VerificationReport:
    status: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    message: str
    failure_class: Optional[str]

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"unknown verification status: {self.status}")
        if self.failure_class not in _FAILURE_CLASSES:
            raise ValueError(f"unknown failure class: {self.failure_class}")


def exit_code_for(report: VerificationReport) -> int:
    return {"proved": 0, "failed": 2, "timeout": 3, "unavailable": 4}[report.status]


def classify_lean_failure(text: str) -> str:
    # Lean also says "Not a definitional equality" when the theorem type is
    # not a proposition. That is a typing error, and it must win over the
    # proof bucket so the statement is not left unresolved.
    if "is not a proposition" in text:
        return "typing"
    # Syntax wins over "unsolved goals": Lean reports both when a tactic token
    # does not parse. "unexpected end of input" and "expected command" are the
    # phrases Lean 4.34.1 actually emits for a broken file.
    if (
        "unexpected end of input" in text
        or "unexpected token" in text
        or "unexpected identifier" in text
        or "expected command" in text
        or "expected term" in text
        or "expected token" in text
    ):
        return "syntax"
    if (
        "Not a definitional equality" in text
        or "unsolved goals" in text
        or "proved that the proposition" in text
    ):
        return "proof"
    if (
        "failed to synthesize" in text
        or "synthInstanceFailed" in text
        or "Type mismatch" in text
        or "Application type mismatch" in text
    ):
        return "typing"
    return "other"


def _toolchain_homes(project_dir: Path) -> tuple:
    return (
        project_dir.parent / ".toolchains" / "elan",
        project_dir / ".toolchains" / "elan",
    )


def find_lake(project_dir: Path, *, path_lookup=shutil.which, environ=None) -> Path:
    environ = os.environ if environ is None else environ
    override = environ.get("THEOREM_GEN_LAKE")
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FileNotFoundError(override)
    for home in _toolchain_homes(project_dir):
        lake = home / "bin" / "lake"
        if lake.is_file():
            return lake
    found = path_lookup("lake") if path_lookup is not None else None
    if found:
        return Path(found)
    raise FileNotFoundError("lake")


def build_lean_env(project_dir: Path, base=None) -> dict:
    env = dict(os.environ if base is None else base)
    for home in _toolchain_homes(project_dir):
        if home.is_dir():
            env["ELAN_HOME"] = str(home)
            bin_dir = str(home / "bin")
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
            break
    return env


def _limit_cpu(cpu_seconds: int):
    import resource

    def preexec() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))

    return preexec


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()


def run_process(cmd, timeout, cwd, env, cpu_seconds=None):
    process = subprocess.Popen(
        list(cmd),
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        preexec_fn=_limit_cpu(cpu_seconds) if cpu_seconds is not None else None,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise
    return (
        process.returncode,
        stdout.decode("utf-8", "replace"),
        stderr.decode("utf-8", "replace"),
    )


def forbidden_construct(source: str) -> Optional[str]:
    for pattern, name in _FORBIDDEN:
        if pattern.search(source):
            return name
    return None


def _clip(text: str) -> tuple:
    if len(text) <= MAX_CAPTURE:
        return text, False
    return text[:MAX_CAPTURE], True


def interpret_lean_result(returncode: int, stdout: str, stderr: str) -> VerificationReport:
    stdout, stdout_cut = _clip(stdout)
    stderr, stderr_cut = _clip(stderr)
    note = " Output was truncated." if stdout_cut or stderr_cut else ""
    combined = stdout + "\n" + stderr
    if returncode == 0 and "declaration uses `sorry`" in combined:
        return VerificationReport(
            status="failed",
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            message=(
                "Lean exited 0 but reported an incomplete proof (sorry). "
                "This is not an accepted proof." + note
            ),
            failure_class="proof",
        )
    if returncode == 0:
        return VerificationReport(
            status="proved",
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            message="Lean accepted the file with exit code 0." + note,
            failure_class=None,
        )
    if returncode < 0:
        return VerificationReport(
            status="timeout",
            exit_code=returncode,
            stdout=stdout,
            stderr=stderr,
            message=(
                f"Lean process was killed (exit code {returncode}). "
                "The result is inconclusive; a resource limit does not decide the statement."
                + note
            ),
            failure_class=None,
        )
    return VerificationReport(
        status="failed",
        exit_code=returncode,
        stdout=stdout,
        stderr=stderr,
        message=f"Lean rejected the file with exit code {returncode}.\n{stderr}{stdout}{note}",
        failure_class=classify_lean_failure(combined),
    )


def verify_source(
    source: str,
    *,
    destination: Path,
    project_dir: Path,
    timeout_s: float = 60,
    runner=None,
    lake_bin: Path = None,
    path_lookup=shutil.which,
) -> VerificationReport:
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    refused = forbidden_construct(source)
    if refused is not None:
        return VerificationReport(
            status="failed",
            exit_code=None,
            stdout="",
            stderr="",
            message=f"Refused to run Lean: source contains a forbidden construct ({refused}).",
            failure_class="rejected",
        )
    destination = Path(destination).resolve()
    project_dir = Path(project_dir).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8")
    try:
        lake = Path(lake_bin) if lake_bin is not None else find_lake(project_dir, path_lookup=path_lookup)
    except FileNotFoundError as exc:
        return _unavailable(exc)
    command = [str(lake), "--dir", str(project_dir), "env", "lean", str(destination)]
    env = build_lean_env(project_dir)
    try:
        if runner is None:
            code, stdout, stderr = run_process(
                command,
                timeout_s,
                project_dir,
                env,
                cpu_seconds=max(1, math.ceil(timeout_s)),
            )
        else:
            code, stdout, stderr = runner(command, timeout_s, project_dir, env)
    except subprocess.TimeoutExpired:
        return VerificationReport(
            status="timeout",
            exit_code=None,
            stdout="",
            stderr="",
            message=(
                f"Lean timed out after {timeout_s}s. The result is inconclusive; "
                "a timeout does not decide the statement."
            ),
            failure_class=None,
        )
    except FileNotFoundError as exc:
        return _unavailable(exc)
    except OSError as exc:
        return _unavailable(exc)
    return interpret_lean_result(code, stdout, stderr)


def verify_theorems(
    theorems: Sequence[Theorem],
    config: GeneratorConfig,
    **kwargs,
) -> tuple:
    source = export_module(tuple(theorems), config)
    report = verify_source(source, **kwargs)
    marked = tuple(
        theorem.with_verification(report.status)
        if theorem.proof is not None
        else theorem
        for theorem in theorems
    )
    return report, marked


def _unavailable(exc: BaseException) -> VerificationReport:
    return VerificationReport(
        status="unavailable",
        exit_code=None,
        stdout="",
        stderr="",
        message=f"Lean toolchain is unavailable: {exc}",
        failure_class=None,
    )
