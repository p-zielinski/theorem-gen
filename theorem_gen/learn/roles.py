"""Three roles exchange immutable artifacts. Agreement is not a verdict.

Sharing a prompt, a backend, or a conclusion cannot make a statement proved.
Only an accepted Lean validation can.
"""

from __future__ import annotations

import json

from theorem_gen.learn.errors import LearnError


def retrieve(store, run_id: str, *, structural_hash: str, family: str, limit: int = 3) -> list:
    preferred = store._all(
        """
        SELECT stable_id, current_status, family FROM candidates
        WHERE run_id=? AND current_status IN ('proved', 'refuted')
          AND structural_hash!=? AND family=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (run_id, structural_hash, family, limit),
    )
    if preferred:
        return [dict(row) for row in preferred]
    fallback = store._all(
        """
        SELECT stable_id, current_status, family FROM candidates
        WHERE run_id=? AND current_status IN ('proved', 'refuted')
          AND structural_hash!=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (run_id, structural_hash, limit),
    )
    return [dict(row) for row in fallback]


def proposer_prompt(candidate: dict, found: list) -> str:
    body = {
        "role": "theorem_proposer",
        "candidate": {
            "stable_id": candidate["stable_id"],
            "ast": candidate["canonical_ast_json"],
        },
        "retrieval": found,
    }
    return json.dumps(body, sort_keys=True)


def prover_prompt(candidate: dict) -> str:
    return json.dumps(
        {
            "role": "prover",
            "candidate": candidate["stable_id"],
            "ast": candidate["canonical_ast_json"],
        },
        sort_keys=True,
    )


def alternate_prompt(candidate: dict, phase: str, primary=None, alternate=None) -> str:
    if phase == "prove":
        if primary is not None:
            raise LearnError("alternate prover must not see the primary proof")
        return json.dumps(
            {
                "role": "alternate_prover",
                "phase": "prove",
                "candidate": candidate["stable_id"],
                "ast": candidate["canonical_ast_json"],
            },
            sort_keys=True,
        )
    return json.dumps(
        {
            "role": "alternate_prover_critic",
            "phase": "critique",
            "candidate": candidate["stable_id"],
            "primary": primary,
            "alternate": alternate,
        },
        sort_keys=True,
    )
