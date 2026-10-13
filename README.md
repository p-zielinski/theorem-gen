# Theorem Gen

An experiment: can a language model, trained only on sentences Lean has accepted, start to write new ones of its own? Lean is the only judge. What Lean accepts can be taught back. What it rejects never enters the weights.

The greedy run `run-1` is closed. Argmax wrote 125 names and no equation. The numbers are `docs/run-1-greedy-result.md`. Its weights stay in `var/lm/run-1/`. Its rows stay in `var/learn.sqlite`. Do not resume it.

`run-2` is paused. It drew a hundred texts per step from `<|propose|>` and did not repair them. Its weights stay in `var/lm/run-2/`. Do not resume it.

## The measurement

`run-3` is a new run and a new set of weights. The generator queue is unchanged: it still writes proofs, and Lean still accepts or rejects them. The model does not write until it has taken one training step on sentences Lean has already accepted. No other model is called.

Then the rhythm is fixed. The accepted share is a reading, not a throttle.

1. One training step on four proved sentences from the generator. If the first read has caught up, that step is one page of replay.
2. Twenty formulas drawn from those weights (temperature 1, nucleus 0.9), then one argmax text stored apart. The prompt is `<|propose|>`. The model is filling a formula, not a proof.
3. A text with no equation is "not a formula" and does not go to Lean. A text already in the run is a repeat. A new equation goes to Lean as `theorem model_eq : … := rfl`.
4. After those twenty are judged, if none was accepted, the same model writes four endings. The prefix is the formula Lean read furthest into before the error. The error in the wrapper or in the stapled `rfl` does not count. A second four opens only when one of those endings gets strictly further. Then the branch stops.
5. Each accepted new formula gets one immediate training step. Back to step 1.

The twenty share one set of weights. Distinct, out of 20, says whether the draw searched. The argmax line is not part of that twenty. Endings are the same model continuing the kept letters. The run stops the model after 200 cycles. `learning` stays off unless a saved champion other than the generator beats the held-out set. This network does not enter that gate.

From the repository root:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"

python3 -m theorem_gen.learn start \
  --run-id run-3 \
  --until-pause \
  --lm \
  --repair \
  --lean-workers 4
```

The database is still `var/learn.sqlite`. `start` adds `run-3` beside the paused runs. Weights go to `var/lm/run-3/`. `--until-pause` runs until SIGINT or SIGTERM. Lean checks use four processes. One process stays the only SQLite writer.

Continue it the same way. The repair flag is stored on the run, so a later resume keeps the rhythm:

```sh
python3 -m theorem_gen.learn resume --run-id run-3 --until-pause --lm --lean-workers 4
```

Stop with Ctrl-C or `kill -TERM` on the writer. The signal finishes the Lean calls already started, writes the pause checkpoint, and exits 0. Do not start a second `start` or `resume` on this database while one is alive.

A read-only page, not a second writer:

```sh
python3 -m theorem_gen.learn dashboard
```

The heading is the run whose status is `running`. A `--run-id` on this command is used only when every run is paused. The page is in English at `http://127.0.0.1:8765/`. The top is the current cycle: which of the 200 it is, how many of the twenty differ, how many Lean accepted, how far into a formula Lean read, and what the argmax text was. The verdict table under that counts the sampled texts. The argmax line is not in that table.

```sql
SELECT cycle, repair_ply, error_at, decoder, disposition, equation
FROM model_attempts WHERE run_id='run-3' ORDER BY id;
```

## Generator

A separate road, with no loop database. Stages 0–8 are implemented. The default CLI builds concrete theorems about `Nat` and can ask Lean to check the file. That file is not the model's corpus.

Python 3.9+. Lean 4.34.1 and Lake 5.0.0 through elan. The repository pins the version in `lean/lean-toolchain`. If `elan` is not installed, a local toolchain can be created without changing the user's `PATH`:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
mkdir -p "$ELAN_HOME"
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
  | sh -s -- -y \
      --default-toolchain leanprover/lean4:v4.34.1 \
      --no-modify-path
export PATH="$ELAN_HOME/bin:$PATH"
```

From the repository root:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"

python3 -m theorem_gen generate \
  --seed 1 \
  --count 8 \
  --out lean/TheoremGen/Generated.lean \
  --verify \
  --timeout 120
```

Expected ending:

```text
verification: proved
Lean accepted the file with exit code 0.
```

The result is in `lean/TheoremGen/Generated.lean`.

The second generator, the same one the loop uses, prints equalities with variables:

```sh
python3 -m theorem_gen.richgen --seed 1 --count 4 --out /tmp/rich.lean
```

Besides the CLI there are general sentences (`generate_general`), the `double` definition, hypothesis assessment (`assess_hypothesis`), and exploration of four templates (`explore`). No proof, a counterexample, and no rule in the fragment are separate results.

The word `proved` has three meanings. Keep them apart:

| Where | Meaning |
|-------|---------|
| `VerificationReport.status` | Lean accepted the file |
| `HypothesisAssessment.status` | a hypothesis after Lean or a counterexample |
| `ExplorationResult.status` | a citation of a registered lemma |

`ExplorationResult.status == "proved"` is not `claimed_true`. Export from `theorem_from_proved` stays `unverified` until Lean checks the file. `claimed_true(theorem)` requires `verification == "proved"` and a non-empty proof.

## Tests

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m unittest discover -s tests -v
```

The suite has unit tests and real Lean calls. If Lean is unavailable, the integration class is skipped.

A full Lean project build:

```sh
cd lean
export ELAN_HOME="$PWD/../.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
lake clean
lake build
```

## Documentation

- `docs/run-1-greedy-result.md` — the closed argmax run
- `docs/run-3-repair-can-show.md` — what the repair run can and cannot show
- `docs/what-the-run-can-show.md` — what a run of this loop can and cannot show
- `docs/continuous-ai-architecture.md` — the loop, statuses, gates, queue, model
- `docs/continuous-ai-schema.sql` — the SQLite schema
- `docs/continuous-ai-report.md` — commands actually run for that delivery
- `docs/prompts/build-continuous-lean-ai.md` — prompt for the continuous loop
- `docs/stage-0.md` — environment and technical decisions for the generator
- `docs/architecture.md` — modules and the verification contract
- `docs/stage-1.md` … `docs/stage-8.md` — generator stage reports
- `docs/stages.md` — completion criteria for stages 0–8
- `docs/prompts/audit-lean-generator.md` — prompt for an independent audit of stages 0–8
