"""Lean validation adapter. Status is never taken from a role's text."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from theorem_gen.export_lean import export_prop
from theorem_gen.expr import Forall, NatLit, substitute
from theorem_gen.hypothesis import find_counterexample
from theorem_gen.learn.astjson import load_prop
from theorem_gen.learn.classify import map_report
from theorem_gen.verify import MAX_CAPTURE, VerificationReport, forbidden_construct, verify_source

_IMPORT = re.compile(r"(?m)^\s*import\b")


def screen_source(source: str):
    if _IMPORT.search(source):
        return "import"
    return forbidden_construct(source)


def toolchain_identity(project_dir: Path) -> tuple:
    path = Path(project_dir) / "lean-toolchain"
    text = path.read_text(encoding="utf-8").strip() if path.is_file() else "unknown"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, digest


def negation_source(prop_source: str, stable_id: str) -> str:
    digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:12]
    return f"theorem cert_{digest} : Not {prop_source} := by\n  decide\n"


def false_proposition(statement, witness: dict):
    if isinstance(statement, Forall):
        environment = {name: NatLit(int(value)) for name, value in witness.items()}
        return substitute(statement.body, environment)
    return statement


def validate_source(
    source: str,
    *,
    validation_type: str,
    project_dir: Path,
    timeout_s: float,
    runner=None,
) -> dict:
    refused = screen_source(source)
    if refused is not None:
        report = VerificationReport(
            status="failed",
            exit_code=None,
            stdout="",
            stderr="",
            message=f"Refused to run Lean: source contains a forbidden construct ({refused}).",
            failure_class="rejected",
        )
    else:
        with tempfile.TemporaryDirectory(prefix="theorem-gen-learn-") as tmp:
            destination = Path(tmp) / "Candidate.lean"
            report = verify_source(
                source,
                destination=destination,
                project_dir=Path(project_dir),
                timeout_s=timeout_s,
                runner=runner,
            )
    view = map_report(report, validation_type)
    version, digest = toolchain_identity(project_dir)
    return {
        "lean_version": version,
        "toolchain_hash": digest,
        "validation_type": validation_type,
        "result": view.result,
        "accepted": view.accepted,
        "stdout": report.stdout[:MAX_CAPTURE],
        "stderr": report.stderr[:MAX_CAPTURE],
        "message": report.message[:MAX_CAPTURE],
        "failure_class": view.failure_class,
    }


def python_witness(statement) -> dict:
    """A Python witness is a proposal. It is not a refutation."""
    witness = find_counterexample(statement, 5)
    if witness is None:
        return None
    proposition = false_proposition(statement, witness)
    return {
        "assignment": witness,
        "instantiated_prop": export_prop(proposition),
    }


def load_candidate_prop(canonical_ast_json: str):
    return load_prop(canonical_ast_json)
