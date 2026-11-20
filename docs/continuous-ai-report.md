# Loop delivery report

> Date: 2026-10-12. Directory: repository root. Branch: `main`.
> The numbers below come from that day's audit, after migration 004, the syntax-classification fix, and closing a batch cut by the budget.

Lean environment:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
lake --version
lean --version
```

```
Lake version 5.0.0-src+5045d00 (Lean version 4.34.1)
Lean (version 4.34.1, arm64-apple-darwin24.6.0, commit 5045d0056413266e57c625dcd7c365b10e377c52, Release)
```

`lake --dir lean build` ended with `Build completed successfully (4 jobs).` Exit code 0.

## Tests

```sh
python3 -m unittest discover -s tests
```

```
Ran 192 tests in 14.546s
OK
```

Exit code 0. The suite includes real Lean 4.34.1: a proof of `0 = 0`, a certificate `Not (1 = 0)`, rejection of `Not (0 = 0)`, a typing error `theorem bad : Nat := rfl` (`ill_formed`), syntax `theorem bad : (0 = 0) :=` and `this is not lean` (`ill_formed`), an accepted `double` definition as `check` with `accepted=0`, and a 2 s timeout on `repeat (first | done | skip)` (`timeout`, `accepted` false).

```sh
python3 -m compileall -q theorem_gen tests
git diff --check
```

Both commands exited 0.

`python3 -m theorem_gen generate --seed 1 --count 1 --out "$TMP/Generated.lean"` exited 0 (`generated 1 theorems`). The golden `lean/TheoremGen/Generated.lean` was not the write target and does not appear in `git status`.

## Memory

```sh
python3 -m theorem_gen.learn memory
```

Exit code 0. `peak_rss_bytes: 16646144`, `within_budget: yes`, `weights_loaded: no`, `resident_copies: 0`. Full printout: `docs/continuous-ai-memory.md`.

## A short Lean run

```sh
python3 -m theorem_gen.learn start --run-id smoke --curriculum 1 \
  --db "$DB" --seed 1 --count 1 --max-steps 2
```

Exit code 0. Two candidates, both `proved`. `learning: no`. `checkpoint_seq: 2`. `event_cursor: 9`.

```sh
python3 -m theorem_gen.learn replay --run-id smoke --db "$DB" --from-checkpoint 1
```

```
replay_match: yes
```

Exit code 0. `resume --max-steps 0` and `pause` also exit 0.

| Command | Code | Message |
|---------|------|---------|
| `start --curriculum 4` | 1 | `a new run starts at curriculum level 1` |
| `replay --from-checkpoint 99` | 1 | `checkpoint not found` |
| a second `replay --from-checkpoint 1` | 1 | `replay database already exists: …/learn-replay.sqlite` |
| `status --run-id missing` | 1 | `unknown run missing` |
| `start --checkpoint-interval 10` | 1 | `checkpoint interval must be between 300 and 600 seconds` |
| a second `start` of the same run | 1 | `run already exists; use resume` |
| `status` on a file that is not a SQLite database | 1 | `file is not a database` |
| `theorem_gen.learn nosuch` | 2 | argparse: `invalid choice: 'nosuch'` |

Real Lean in this run, through `validate_source`: `0 = 0` → `proved`; `1 = 0 := rfl` → `unresolved`; `Not (1 = 0)` → `refuted`; `Not (0 = 0)` → `unresolved`; `theorem bad : Nat` → `ill_formed` / `typing`; `theorem bad : (0 = 0) :=` and `this is not lean` → `ill_formed` / `syntax`; `def double` → `check`, `accepted=0`, `unresolved`; a 2 s timeout → `timeout`, `unresolved`. `sorry`, `axiom`, `opaque`, `unsafe`, `#eval`, `run_io`, `run_cmd`, and `import` are rejected before the process (`failure_class=rejected`). `admit` exits 0 with a sorry warning and is not `proved`. Lean rejects `sorryAx` as typing.

The default budget, the same shape as `start` without `--max-steps` (`seed=1`, `count=4`, `max_steps=50`, `refill_when_idle`), on Lean 4.34.1: 52 candidates, all `proved`, zero jobs in the queue, zero `failed` jobs, `learning: no`, level 1, `advancement_frozen` off, checkpoint 2, `event_cursor` 120. The budget falls in the middle of the thirteenth batch; the loop finishes those four validations and does not open the fourteenth. A separate run `--max-steps 2 --count 4` produced 4 `proved` and an empty queue. `--max-steps 0` still does not call Lean.

## What this run does not show

No 7B-8B model was loaded. RSS of inference together with Lean workers under a weight load was not measured. Occupancy ≥ 80% in the test is a scheduler step counter when the queue has work, not a system CPU percentage. The gate of 1000 candidates is checked on a cohort whose validation has the shape of an accepted proof, and on a separate timeout cohort that does not promote. A thousand separate `lake` calls per level were not run. The CLI `--max-steps 2 --count 1` is two `proved`. The default 50 steps at `count=4` is 52 `proved`. `learning: no` matches the definition: in this process the champion did not beat the baseline on a measurement other than the generator's constants.
