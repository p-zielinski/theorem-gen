"""Load the applied SQL migration. The docs copy must stay identical."""

from __future__ import annotations

from pathlib import Path

MIGRATIONS = (
    (1, "initial", "001_initial.sql"),
    (2, "integrity", "002_integrity.sql"),
    (3, "checks", "003_checks.sql"),
    (4, "identity", "004_identity.sql"),
)


def migration_sql(name: str) -> str:
    path = Path(__file__).resolve().parent / "migrations" / name
    return path.read_text(encoding="utf-8")
