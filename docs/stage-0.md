# Stage 0 — analysis and technical plan

> Date: 2026-10-11
> Status: done

## Environment

Checked in the repository directory on an `arm64` machine, Darwin 25.5.0:

| Tool | Result |
|------|--------|
| Python | 3.9.6, `/usr/bin/python3` |
| git, curl, brew | available |
| `lean`, `lake`, `elan` on `PATH` | absent |
| `~/.elan` | absent |

Lean was not installed globally. So the shell configuration would stay unchanged, elan was installed locally in the project:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
  | sh -s -- -y --default-toolchain leanprover/lean4:v4.34.1 --no-modify-path
```

After installation:

- Lean 4.34.1 (`arm64-apple-darwin24.6.0`, commit `5045d0056413`)
- Lake 5.0.0-src+5045d00

The `.toolchains/` directory is in `.gitignore`. `lean/lean-toolchain` pins the same version, so `lake` can fetch it with a global elan as well.

## Lean 4.34 dialect probe

The real compiler was run on short files.

- `((2 + 3) = 5) := rfl`, `(((2 + 3) * 4) = 20) := rfl`, and `((2 + 4) = (4 + 2)) := rfl` pass.
- `(2 <= 5)` and `(2 < 5)` pass as `:= by decide`.
- `(1 = 0) := rfl` exits 1. The message contains `Not a definitional equality`, then a separate line `Type mismatch` for the term `rfl`. Classification must recognize a proof error first, or it will describe it as a type error.
- `True + 1` exits 1 with `failed to synthesize` / `synthInstanceFailed`.
- A cut-off `(1 = := rfl` exits 1 with `unexpected token`.
- `:= sorry` exits 0 with the warning `declaration uses sorry`. The exit code alone is not enough to accept a proof.

On this macOS, `resource.setrlimit(RLIMIT_AS, ...)` in Python 3.9 raises `ValueError` (`RLIMIT_AS` and `RLIMIT_RSS` share a number). A virtual-memory limit is not used. What remains is a wall-clock limit and `RLIMIT_CPU` in the child process.

## Python / Lean split

Python holds the generator, the typed tree, the seed, export of a bounded subset, and launching the process. Tests of that part do not need the compiler.

Lean 4 is the only judge of a proof. There is no Lean parser of our own, and no heuristic that reads an error message and concludes the theorem is true. The message text is used only to describe an error and to reject `sorry`, which the compiler accepts with exit code 0.

Mathlib is not part of stage 1. Concrete theorems about `Nat` with `+`, `*`, and comparisons fit in the prelude.

## Minimum scope of stage 1

In the code:

- `Nat` literals, addition, multiplication, `=`, `<=`, `<`
- a concrete theorem: a `Prop` expression plus a proof method `rfl` or `decide`
- a generator driven by a seed and a configuration
- export of a Lean module
- verification by a `lake env lean` process with a time limit

Outside stage 0, added later in stages 2–8:

- variables, quantifiers, implications
- a wider AST
- a dependency registry and cycles
- complexity control
- definitions
- hypotheses
- open exploration

In stage 1 itself the exporter accepted the kind `concrete`. Later kinds have their own export paths and are not quietly translated into a concrete proof.

## Directory layout

```
theorem_gen/          the generator in Python
tests/                unittest
lean/                 Lake project (verification)
docs/                 architecture, stages, reports
.toolchains/elan/     local Lean, outside git
```

## Interface

`GeneratorConfig`: `seed`, `count`, `max_literal`, `max_depth`, `max_value`, `unique`, `rules`, `max_attempts`.

`generate(config)` returns a list of theorems. The same config gives the same result. With one rule the generator does not spend a draw on choosing it. The number generator is a 32-bit LCG (multiplier `1664525`, increment `1013904223`), independent of Python's `random`.

Export: `export_module(theorems, config)` — a file with a configuration comment and the theorems.

Verification: `verify_source` / `verify_theorems`. Statuses: `proved`, `failed`, `timeout`, `unavailable`. Failure class when the status is `failed`: `syntax`, `typing`, `proof`, `rejected`, `other`.

Running tests from the repository root:

```sh
python3 -m unittest discover -s tests -v
```

Example:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m theorem_gen generate --seed 1 --count 8 --out lean/TheoremGen/Generated.lean --verify
```

## Completion criteria

Recorded in [stages.md](stages.md). Stage 0 is closed by this note and
[architecture.md](architecture.md). Stage 1 was then built and
described in [stage-1.md](stage-1.md).
