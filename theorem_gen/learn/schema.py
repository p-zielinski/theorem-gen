"""Load the applied SQL migration. The docs copy must stay identical."""

from __future__ import annotations

from pathlib import Path

MIGRATIONS = (
    (1, "initial", "001_initial.sql"),
    (2, "integrity", "002_integrity.sql"),
    (3, "checks", "003_checks.sql"),
    (4, "identity", "004_identity.sql"),
    (5, "parallel", "005_parallel.sql"),
    (6, "qlora", "006_qlora.sql"),
    (7, "minilm", "007_minilm.sql"),
    (8, "lean_ms", "008_lean_ms.sql"),
    (9, "context_block", "009_context_block.sql"),
    (10, "sample_burst", "010_sample_burst.sql"),
    (11, "replay", "011_replay.sql"),
    (12, "attempt_context", "012_attempt_context.sql"),
    (13, "attempt_shape", "013_attempt_shape.sql"),
    (14, "probe", "014_probe.sql"),
    (15, "repair", "015_repair.sql"),
)


def migration_sql(name: str) -> str:
    path = Path(__file__).resolve().parent / "migrations" / name
    return path.read_text(encoding="utf-8")
