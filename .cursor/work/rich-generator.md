# A richer equation generator

> Last updated: 2026-10-12
> Branch: `main`
> Status: done

## Problem & goal

The current generator exhausted shallow concrete `Nat` (depth 2, `rfl`). Beside it a second generator runs: general equalities with variables, distributivity, and a proof of several steps. Every `run-1` proposal adds one such sentence to the old batch.

## Scope

- **In scope:** `theorem_gen/richgen.py`, wiring one sentence per batch into `theorem_gen.learn`, tests, a short mention in the README.
- **Out of scope:** changing `generate()`, the golden `lean/TheoremGen/Generated.lean`. The loss gate for model samples was out of scope here; it later landed in the continuous loop.

## Key files & context

| Area | Path | Role |
|------|------|------|
| Generator | `theorem_gen/richgen.py` | `rich_theorem(seed, index)` in O(1), AC and rewrite families |
| Queue | `theorem_gen/learn/batches.py` `rich_items` | One sentence, `origin: generator`, `generator: richgen`, `needs_roles` false |
| Engine | `theorem_gen/learn/engine.py` | Appends `rich_items` to the old batch and the review |
| Training | `theorem_gen/learn/minilm.py` `theorem_block` | A multiline proof enters `<|prove|>` |
| Tests | `tests/test_richgen.py` | Rules, determinism, the queue, one Lean call |
| Old generator | `theorem_gen/generate.py` | Unchanged |

## Decisions

- 2026-10-12: Families `ac_add`, `ac_mul`, `ac_mix`, `rewrite`. The proof is `conv` plus `rw` on the left side, then `ac_rfl`. No Mathlib and no `import`.
- 2026-10-12: Order inside a batch is fixed every 4. Depth at least 3. The index has its own seed (splitmix), so index 74000 does not reproduce earlier ones.
- 2026-10-12: AC families take a random leaf order and a numeral 2–9, not a sorted multiset. Otherwise almost every batch would have the same sentence and the novelty filter would drop it.
- 2026-10-12: In the queue, one sentence per batch, `origin` stays `generator`, and the distinction is `generator: richgen`. `needs_roles` is false. `canonical_ast_json` is `{"generator","statement"}`, not a tree of the old AST.

## Progress

- [x] Rule and batch tests
- [x] Implementation and Lean acceptance
- [x] Wired into the queue beside the old generator

## Next steps

1. The loss gate for model writing is implemented in the continuous loop: 10 losses under 0.45, then 10 equations, then 200 study steps. See `.cursor/work/continuous-lean-ai.md`.

## Blockers / open questions

- None. The live `var/learn.sqlite` is not reset. After a code change the single `run-1` writer gets SIGTERM and `resume --lean-workers 4 --lm`.

## Verification

`python3 -m unittest tests.test_richgen tests.test_learn_minilm.RoleTests` — OK, including Lean on the seed 1 batch and one engine step with both generators.
