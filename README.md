# Theorem Gen

Theorem Gen is a local experiment about formal sentences in Lean 4. It keeps two approaches apart. A deterministic generator writes a Lean file from a seed. A separate learning loop trains only on sentences Lean has already accepted, asks the model to write, and sends that writing back to Lean.

Lean is the only judge in the loop. What Lean accepts can be taught back. What it rejects never enters the weights.

A long browser deck of the stages and the four runs is [docs/runs-story.html](docs/runs-story.html).

The Python package is `theorem_gen`. Commands run from the repository root with Python 3.9 or newer. Lean 4.34.1 and Lake 5.0.0 come through elan. The repository pins that toolchain in `lean/lean-toolchain`. The loop database and the weight files live under `var/`, which is not part of the git tree. A stranger can read the generator without ever starting a run.

## Two approaches

### Deterministic generator

Stages 0-8 are implemented. The generator builds a theorem as a tree, exports Lean syntax, and can ask Lean to check the finished file. The same seed produces the same sentences. That file is not the model's corpus, and this road has no loop database.

The default CLI builds concrete theorems about `Nat`. A second generator, `theorem_gen.richgen`, prints equalities with variables. The same package also has general sentences (`generate_general`), the `double` definition, hypothesis assessment (`assess_hypothesis`), and exploration of four templates (`explore`). Commands, the three meanings of the word `proved`, and the expected Lean ending are in [Generator](#generator) below. Module boundaries are in [docs/architecture.md](docs/architecture.md). Stage reports are [docs/stage-0.md](docs/stage-0.md) through [docs/stage-8.md](docs/stage-8.md). Completion criteria are [docs/stages.md](docs/stages.md).

### Lean as the judge

The learning loop is a different process. It reads proved sentences from the generator, takes a training step, and samples text from the weights. A text with no equation does not go to Lean. A new equation is checked as a theorem closed by `rfl`. An accepted new formula can receive a training step. A rejection is stored and is not taught.

No other model is called. The network is a transformer trained from scratch, about 50 million parameters, context 512 tokens. The rhythm, statuses, gates, queue, and model slot are [docs/continuous-ai-architecture.md](docs/continuous-ai-architecture.md). The schema is [docs/continuous-ai-schema.sql](docs/continuous-ai-schema.sql). What any run of this loop can and cannot show is [docs/what-the-run-can-show.md](docs/what-the-run-can-show.md). Commands actually run for the first delivery of the loop are [docs/continuous-ai-report.md](docs/continuous-ai-report.md).

## Which runs matter

Four run ids share `var/learn.sqlite`. Weights for each run stay in `var/lm/<run-id>/`. Do not resume a closed run, and do not resume a paused run in order to continue an old decoder.

### run-1, greedy, closed

`run-1` is closed. The sampler takes the character with the largest logit, so the same prompt and the same weights always continue with the same character. Argmax wrote 125 names and no equation. The result note records 18,032 finished tries and 125 distinct strings. None contains `=` or `:=`. Lean accepted 0. The numbers are [docs/run-1-greedy-result.md](docs/run-1-greedy-result.md). Its weights stay in `var/lm/run-1/`. Do not resume it.

### Later runs

`run-2` is paused. It drew a hundred texts per step from `<|propose|>` and did not repair them. Its weights stay in `var/lm/run-2/`. Do not resume it. `docs/` has no separate result note for `run-2`.

`run-3` is closed. It was a new run and a new set of weights. Two hundred cycles of twenty formulas and up to two rounds of four endings produced no text Lean accepted. Endings moved the column. The numbers are [docs/run-3-repair-result.md](docs/run-3-repair-result.md). What that repair run can and cannot show is [docs/run-3-repair-can-show.md](docs/run-3-repair-can-show.md). Its weights stay in `var/lm/run-3/`. Do not resume it.

[The measurement](#the-measurement) below is the record of how `run-3` was started and what one cycle did.

### run-4, the current hole

`run-4` breaks one character of a generator sentence proved by `rfl`. The model may replace only that character. Twenty guesses and one argmax are checked as `theorem model_eq : {body} := rfl`. Only a character Lean accepts is taught. Weights go to `var/lm/run-4/`.

The hole part is finished: 200 cycles, 185 sample accepts, every one the original `(`, none a different character. The user stopped the run on 2026-10-15 14:01. Status in `runs` is `paused`. Do not resume `run-4`. The checks and the verdict are [docs/run-4-observations.md](docs/run-4-observations.md).

The command that started that hole run:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m theorem_gen.learn start --run-id run-4 --until-pause --lm --hole --lean-workers 4
```

Do not resume `run-1`, `run-2`, or `run-3`.

## The measurement

`run-3` was a new run and a new set of weights. The generator still wrote proofs, and Lean still accepted or rejected them. While more than 128 proved sentences sat ahead of the first read, the generator opened no new batch. The model did not write until it had taken one training step on sentences Lean had already accepted. No other model was called. Do not start this run again. The command below is the record of how it was started.

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

A separate road, with no loop database. Stages 0-8 are implemented. The default CLI builds concrete theorems about `Nat` and can ask Lean to check the file. That file is not the model's corpus.

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

- [docs/run-1-greedy-result.md](docs/run-1-greedy-result.md): the closed argmax run
- [docs/run-3-repair-can-show.md](docs/run-3-repair-can-show.md): what the repair run can and cannot show
- [docs/run-3-repair-result.md](docs/run-3-repair-result.md): the closed repair run: endings moved the column, Lean accepted nothing
- [docs/run-4-observations.md](docs/run-4-observations.md): hole-run checks after the 200 cycles, and the stop
- [docs/what-the-run-can-show.md](docs/what-the-run-can-show.md): what a run of this loop can and cannot show
- [docs/continuous-ai-architecture.md](docs/continuous-ai-architecture.md): the loop, statuses, gates, queue, model
- [docs/continuous-ai-memory.md](docs/continuous-ai-memory.md): memory and resident-copy notes
- [docs/continuous-ai-audit.md](docs/continuous-ai-audit.md): audit notes for the loop
- [docs/continuous-ai-schema.sql](docs/continuous-ai-schema.sql): the SQLite schema
- [docs/continuous-ai-report.md](docs/continuous-ai-report.md): commands actually run for that delivery
- [docs/prompts/build-continuous-lean-ai.md](docs/prompts/build-continuous-lean-ai.md): prompt for the continuous loop
- [docs/stage-0.md](docs/stage-0.md): environment and technical decisions for the generator
- [docs/architecture.md](docs/architecture.md): modules and the verification contract
- [docs/stage-1.md](docs/stage-1.md) through [docs/stage-8.md](docs/stage-8.md): generator stage reports
- [docs/stages.md](docs/stages.md): completion criteria for stages 0-8
- [docs/prompts/audit-lean-generator.md](docs/prompts/audit-lean-generator.md): prompt for an independent audit of stages 0-8
