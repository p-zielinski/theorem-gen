# Stage 1: a minimal arithmetic generator

> Completed: 2026-10-11
> Status: done

## 1. What was implemented

- a typed, immutable AST: `NatLit`, `BinOp`, `Compare`
- types `Nat` and `Prop`; operators `+`, `*`, `=`, `<=`, `<`
- 12 explicit rules that build true sentences about concrete numbers
- separation of the sentence, the proof (`rfl` / `decide`), and the metadata
- a deterministic 32-bit LCG, stable across Python versions
- configuration of the result count, bounds, depth, rules, and uniqueness
- export of a bounded Lean 4 subset without changing the meaning of the AST
- CLI `python3 -m theorem_gen generate`
- verification by real Lean with a timeout, a CPU limit, and killing the process group
- explicit statuses `proved`, `failed`, `timeout`, `unavailable`
- a separate error classification: `syntax`, `typing`, `proof`, `rejected`, `other`
- a ready example `lean/TheoremGen/Generated.lean`

Stage 1 itself did not add variables, quantifiers, assumptions, a dependency registry, or hypothesis generation. Those arrived in stages 2-8 and do not change the default generator of concrete theorems.

## 2. TDD path

1. Before the `theorem_gen` package, tests were written for the AST, RNG, generator, export, CLI, and verifier.
2. The first run:

   ```text
   Ran 7 tests
   FAILED (errors=7)
   ModuleNotFoundError: No module named 'theorem_gen'
   ```

3. After a minimal implementation the unit suite found a bug in the RNG sequence test itself (a new instance was created for each number). The test was fixed so it examines one sequence.
4. After the integration was implemented the first full suite gave `67 tests ... OK`.
5. An audit added a test of a process killed by a signal and a `lake build` test; the suite grew to 69.
6. The final, real CLI command with a relative `--out` found a regression: Lean looked for `lean/lean/TheoremGen/Generated.lean`. The test `test_relative_destination_is_made_absolute_before_changing_cwd` was added first and confirmed red, then the verifier began resolving paths before changing the process directory.
7. The final suite has 70 tests.

## 3. Tests added

- unit: AST, typing, evaluation, structural keys, RNG, export
- determinism: a golden sequence and configuration repeatability
- edges: zero results, a negative seed, `max_literal = 0`, uniqueness exhaustion, an empty rule set, the attempt limit
- regression: a relative file path under a different `cwd`, a signal or process limit, `sorry` at exit code 0, proof-error priority over the text `Type mismatch`
- property tests with no external dependency: many seeds give true, unique sentences with no `sorry`; an extra probe of 100 seeds of 8 theorems
- integration: a correct batch, a false equality, a type error, a syntax error, byte accuracy of the saved example, CLI with `--verify`, a clean `lake build`

## 4. Commands actually run

From the repository root:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"

python3 -m unittest discover -s tests -v
python3 -m theorem_gen generate \
  --seed 1 \
  --count 8 \
  --out lean/TheoremGen/Generated.lean \
  --verify \
  --timeout 120
```

From `lean/`:

```sh
export ELAN_HOME="$PWD/../.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
lake clean
lake build
```

Also:

```sh
python3 -m compileall -q theorem_gen tests
git diff --check
```

## 5. Results

```text
Python 3.9.6
Lean 4.34.1
Lake 5.0.0-src+5045d00

Ran 70 tests
OK

generated 8 theorems
wrote lean/TheoremGen/Generated.lean
verification: proved
Lean accepted the file with exit code 0.

Build completed successfully (4 jobs).
100 seeds x 8: OK
```

The example matches `export_module(generate(...))` byte for byte.
The IDE reports no linter errors. `compileall` and `git diff --check` exit 0.

## 6. Known limits

- `generate` builds only concrete sentences about `Nat`; variables and quantifiers are in the stage 2-8 modules
- no Mathlib; stage 1 uses the Lean prelude
- the LCG uses modulo in `randint`, so the distribution can be slightly skewed, but it is deterministic
- on Darwin/Python 3.9 setting `RLIMIT_AS` does not work; the timeout and `RLIMIT_CPU` do. The CPU limit is a Unix mechanism.
- `verify_source` is meant for trusted code from the stage 1 exporter. The gate rejects executable constructions and unfinished proofs, but it is not a full sandbox for arbitrary Lean.
- the warning `declaration uses sorry` is rejected despite exit code 0. Other Lean results are judged first by the process exit code.
- `max_value` bounds the values of both sides, not the AST size or the difficulty; full complexity control belongs to stage 5.

## 7. Criteria

Every stage 1 criterion in [stages.md](stages.md) is met: determinism, result count, optional uniqueness, a correct export, real Lean verification, explicit errors, tests, and this report.

An independent audit found no critical or high defects. During the final verification the relative-path regression was fixed and the whole suite was run again.

## 8. Next step

When stage 1 closed, the next step was stage 2. It was built later. The current state of stages 2-8 is in `docs/stage-2.md` … `docs/stage-8.md`.
