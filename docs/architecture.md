# Architecture

> Last updated: 2026-10-11
> Code in force: stages 0-8. The default CLI path still generates the concrete theorems of stage 1. A separate SQLite loop is described in `docs/continuous-ai-architecture.md` and does not change this contract. That loop trains its own transformer on sentences Lean has accepted and may append equations from the model. The `proved` verdict still belongs to Lean.

The generator builds theorems as a tree, not as pasted text. Lean receives a finished, narrow fragment of the language and checks the proof itself.

```
GeneratorConfig + LCG
        │
        ▼
   construction rules
        │
        ▼
  Compare : Prop          Metadata (id, kind, rules, status)
        │
        ▼
   Lean 4 export  ──►  lake env lean  ──►  VerificationReport
```

## Modules

| Module | Role |
|--------|------|
| `theorem_gen/rng.py` | LCG. The same sequence on every CPython. |
| `theorem_gen/expr.py` | AST: `Nat`, `Int`, variables, `succ`, `neg`, quantifier, implication, atom. |
| `theorem_gen/config.py` | `GeneratorConfig`, concrete and general rules, complexity bounds. |
| `theorem_gen/theorem.py` | Theorem, optional proof, metadata, `claimed_true`. |
| `theorem_gen/export_lean.py` | The only writer of Lean syntax, including definitions and `#check`. |
| `theorem_gen/generate.py` | Concrete sentences about `Nat`. |
| `theorem_gen/general.py` | Universal sentences, conditionals, and expressions with no proof. |
| `theorem_gen/complexity.py` | Structural measures. |
| `theorem_gen/registry.py` | Identifiers, dependencies, cycles, replay. |
| `theorem_gen/definitions.py` | The `double` definition and a theorem that uses it. |
| `theorem_gen/hypothesis.py` | Hypothesis assessment, separate from generation. |
| `theorem_gen/explore.py` | Four exploration templates and four different verdicts. |
| `theorem_gen/verify.py` | The Lean process, limits, result classification. |
| `theorem_gen/__main__.py` | The `generate` CLI. |
| `lean/` | A Lake project without Mathlib. |

## Stage 1 types

- `Nat`: a non-negative literal, or `+` / `*` of two `Nat` expressions.
- `Prop`: a comparison of two `Nat` expressions (`=`, `<=`, `<`).

The constructor rejects a negative literal, a `bool` value, a foreign operator, and a child of the wrong type. The exporter does not repair such a tree, because the tree is never built. A false but well-typed sentence (`1 = 0`) can be exported without changing its meaning; the generator itself does not create it. Lean rejects it.

## Proof

| Sentence | Method in the generator | Lean |
|----------|-------------------------|------|
| equality of concrete `Nat` with `+` and `*` | `rfl` | definitional equality |
| `<=`, `<` | `by decide` | decidable comparison |

The exporter prints the method it was given. It does not swap `rfl` for `decide` or the reverse. `sorry` is not a proof method.

## Generator

Rules: `eval_eq`, `add_zero`, `zero_add`, `mul_one`, `one_mul`, `mul_zero`, `zero_mul`, `add_comm`, `mul_comm`, `le_between`, `lt_between`, `le_refl`.

A candidate is dropped when a rule does not apply inside the bounds (for example `a < b` at `max_literal = 0`), when either side exceeds `max_value`, or when `unique` sees a repeated structural key. After the attempts run out, the result is `GenerationError`. That is a configuration limit, not a verdict that the sentence is false.

The identifier `gen_s<seed>_<index>` is stable for a position in the result. A negative seed gets the token `neg`.

## Verification

The command, with no shell:

```text
lake --dir <project> env lean <file>
```

- exit 0 and no `sorry` warning → `proved`
- exit 0 and `declaration uses sorry` → `failed` / `proof`
- a positive exit code → `failed` and a class: `proof`, `syntax`, `typing`, or `other`
- timeout or a negative exit code (the process was killed by a limit) → `timeout`, an undecided result
- no `lake`, or a launch error → `unavailable`

Before the process starts, fragments outside stage 1 that could execute something or accept an unfinished proof are rejected: `#eval`, `run_io`, `run_cmd`, `sorry`, `unsafe`, `axiom`, `opaque`. That is a safety gate, not a check of truth.

The time limit is a parameter. The process gets its own group, so a timeout also kills `lake`'s children. `RLIMIT_CPU` is set as well. `RLIMIT_AS` does not work on this interpreter (stage 0).

`verify_source` is an interface for trusted code produced by the stage 1 exporter, not a sandbox for arbitrary Lean. The exporter does not print imports, commands, or declarations of its own beyond theorems. Before launch, the project path and the file path are made absolute, so a change of the Lake process `cwd` does not change the file that was named.

The verification status is written onto a copy of the metadata. Objects returned by the generator stay `unverified` until someone runs Lean.

## File format

The header repeats the seed, the theorem count, and the configuration parameters. The body is only `rfl` and `decide` theorems. Reproducing the file requires the same generator code, the same config, and the same LCG.

## After stage 1

The concrete generator does not draw variables. General sentences are built in `generate_general`, definitions in `definitions`, and open results in `explore`. The exporter still rejects a kind it does not know how to write. `verify_theorems` attaches a Lean status only to theorems that have a proof.

The four exploration verdicts are disjoint: citing a lemma, a counterexample, no proof, and no rule for an atom in this fragment. A Lean process timeout stays an undecided result and is not falsehood.

`ExplorationResult.status == "proved"` means only that a lemma was cited (`discovered=False`). That is not `claimed_true` and it does not replace `VerificationReport.status` after `verify_source`. The complexity filter for `generate` and `generate_general` goes through the shared `complexity.candidate_within_bounds`.

## Extending

A new construction should get a tree variant, a typing test, an export test, and a Lean test. Do not quietly change the concrete theorems of stage 1 or the golden file `lean/TheoremGen/Generated.lean`.

The `theorem_gen.learn` loop adds a queue, a checkpoint, and a status derived from Lean. Its description, curriculum gates, and RAM budget are in `docs/continuous-ai-architecture.md`.
