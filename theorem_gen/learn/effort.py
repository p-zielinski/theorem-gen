"""Monitor grades for this Lean fragment.

The numeral in an equation is not the difficulty. The grade uses the proof
method together with the shape already stored on the candidate: `ast_size`
and `depth`. Rows whose `proof_method` is `model` stored a character count in
`ast_size`, so they stay ungraded until Lean time is the signal.
"""

from __future__ import annotations

from typing import Optional


def effort_level(proof_method: str, ast_size: int, depth: int) -> Optional[int]:
    """Return 1..4, or None when this row has no structural grade."""
    method = proof_method or ""
    if method in {"", "model"}:
        return None
    if method == "rewrite" or ast_size >= 12 or depth >= 4:
        return 4
    if method == "lemma" or ast_size >= 8 or depth >= 3:
        return 3
    if method == "rfl" or ast_size >= 5 or depth >= 2:
        return 2
    return 1


def lean_time_band(lean_ms: Optional[int]) -> Optional[str]:
    """How long one Lean process took. None means the row predates the column."""
    if lean_ms is None:
        return None
    if lean_ms < 100:
        return "fast"
    if lean_ms < 500:
        return "normal"
    if lean_ms < 2000:
        return "slow"
    return "heavy"
