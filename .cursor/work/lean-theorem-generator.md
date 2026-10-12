# Evolutionary Lean 4 theorem generator

> Last updated: 2026-10-11
> Branch: `main`
> Status: done

## Problem & goal

The generator builds theorems as structures, exports them to a narrow subset of Lean 4, and hands the proof to the compiler. "Done" for the series 0–8: concrete arithmetic, general sentences, a wider AST, a registry, complexity, definitions, hypotheses, and an exploration that can leave a sentence unresolved. Lean checks what has a proof. Lack of a proof is not falsehood.

## Scope

- **In scope:** stages 0–8 according to `docs/stages.md`.
- **Out of scope:** Mathlib, a full Lean parser, a durable registry on disk, new Python dependencies.

## Key files & context

| Area | Path | Role |
|------|------|------|
| Reports | `docs/stage-0.md` … `docs/stage-8.md` | Scope, tests, commands, limits |
| Architecture | `docs/architecture.md` | Modules and the verification contract |
| Criteria | `docs/stages.md` | Definition of done |
| Package | `theorem_gen/` | Generation, export, registry, hypotheses, exploration |
| Tests | `tests/test_stage2.py` … `tests/test_stage8.py`, `tests/test_lean_integration.py` | unittest and real Lean |
| Lean project | `lean/` | Lake, no Mathlib; the stage 1 golden file |
| Toolchain | `.toolchains/elan/` | Local Lean 4.34.1, outside git |

## Decisions

- 2026-10-11: Python generates and exports, Lean only checks. No Lean parser and no Mathlib.
- 2026-10-11: Elan is local (`.toolchains/elan`, `--no-modify-path`). Pinned version: Lean 4.34.1, Lake 5.0.0.
- 2026-10-11: An LCG instead of `random.Random`, so the seed does not depend on the Python version.
- 2026-10-11: `sorry` at exit code 0 is not a proof. `RLIMIT_AS` is skipped, because CPython 3.9 on this macOS cannot set it; the timeout and `RLIMIT_CPU` remain.
- 2026-10-11: Tests use `unittest` from the standard library, with no new Python dependencies.
- 2026-10-11: File and project paths are resolved before Lake's `cwd` changes.
- 2026-10-11: `rules=None` means something different in `generate` (concrete rules) and in `generate_general` (general rules). General export uses `config_for_export`.
- 2026-10-11: `pred` is rejected, because a truncated predecessor on `Nat` changes the meaning of zero.
- 2026-10-11: A citation and a use of a definition have `discovered=False`.
- 2026-10-11: Exploration has four templates. `no_proof`, `refuted`, and `unprovable_in_fragment` are disjoint. The status `proved` in exploration means a lemma citation; the Lean file is still checked separately.
- 2026-10-11: Lean's `decide` message "proved that the proposition … is false" is class `proof`.
- 2026-10-11: Complexity bounds cover all six measures. `variables` selects a general sentence, and `dependencies` and `definitions` require the explicit rule `use_definition`, outside the default set.
- 2026-10-11: After the audit: the unknown-`kind` message in the export was fixed; a shared `candidate_within_bounds` filter; README/architecture explain the three meanings of `proved`.

## Progress

- [x] Stage 0: environment, architecture, criteria
- [x] Stage 1: concrete `Nat`, export, Lean, report
- [x] Stage 2: universal, conditional, expression
- [x] Stage 3: a wider AST and rejection of bad types
- [x] Stage 4: registry, cycles, replay
- [x] Stage 5: measures and generation bounds
- [x] Stage 6: the `double` definition checked in Lean
- [x] Stage 7: hypotheses and diversity metrics
- [x] Stage 8: exploration of four verdicts

## Next steps

1. Do not start another stage in this series. Stages 0–8 are closed.
2. The separate SQLite + Lean loop is in `.cursor/work/continuous-lean-ai.md`. It does not rewrite the 0–8 generator.

## Blockers / open questions

- None. Lean 4.34.1 is installed locally.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m theorem_gen generate --seed 1 --count 8 \
  --out lean/TheoremGen/Generated.lean --verify --timeout 120
python3 -m compileall -q theorem_gen tests
git diff --check
```

Result: 134 tests `OK` (after the post-audit fixes). CLI `verification: proved`, golden `Generated.lean` matches. Combined report: `docs/stage-8.md`.
