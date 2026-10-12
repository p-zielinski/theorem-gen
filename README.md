# Theorem Gen

An experiment: can a language model keep going without a fixed corpus, reading only the sentences Lean 4 has accepted, and from some point adding its own? Lean stays the only judge. What Lean accepts goes back into training. What it rejects never enters the weights.

The generator is the road those first sentences come from. Python builds a typed tree, Lean checks the proof, and the transformer reads only what became `proved`. From then on the subject of a run is the model.

The hypothesis is easy to fail. Loss can stall. The model can repeat the generator, or write equations Lean will not accept. A falling loss is not development by itself. `learning: yes` appears only when a saved champion beats a fixed held-out set on a metric other than a placeholder. The loop is built so that result, or its absence, can be read without guessing what the speed of the machine changed.

## The loop

`python3 -m theorem_gen.learn` stores candidates in SQLite and asks Lean 4.34.1 for a verdict. `proved` and `refuted` come only from a Lean validation. The generator keeps adding batches, including one equality with variables (`generator: richgen`: rearranging sums and products, distributivity, a proof of a few `rw` steps and `ac_rfl`). From level 2 every batch also adds a review of an earlier level. Lean checks that review and it stays in the corpus, but it does not count toward the promotion gate.

The process is linear, the same process you would get with no queue. A batch, Lean's verdict, training on the accepted sentences, and a possible turn of the model follow the row numbers in the database. The queue only lets several Lean checks run ahead of the cursor. A faster machine waits less. It does not skip a sentence that still has no verdict, and it does not cut a training step out of whatever happened to return first.

The cursor stands on the first sentence without a verdict. A rejected sentence, a badly formed one, or one that is too long for the window is already decided, so the cursor passes it. A `proved` sentence outside the held-out set enters training. A training step is four such sentences in a row. If an open check stands before those four are closed, the shorter piece waits with it and is not its own step. A shorter step happens only when no sentence is left ahead. When that read has nothing new to take, a replay walks the proved sentences already behind the cursor, generator and model together, by id. `lm_state.replay_id` is the last id included, so a resume continues there. The next pass starts at 0 once the walk meets the cursor. A replay step does not count toward the ten low losses that let the model write.

The limit of 128 is the depth of that lookahead, separately for each side. The generator may have 128 unfinished Lean checks, and the model may have 128 of its own. A full generator lane does not close the model's room, and a full model lane does not close the generator's. Other kinds of work (a new batch, roles, a counterexample) each have their own 128. Inside one list, higher priority goes first.

The model writes an equation of its own when 10 training steps in a row have loss under 0.45. The baseline turn then puts 10 equations into its Lean lane and returns to study for 200 steps. That budget is the latest block of 20 judged equations, not a high-water mark. A lower Wilson bound above one half widens the next turn to 20 equations and 100 study steps. Above three quarters the turn is 40 equations and 50 study steps. At or below one half, including an average block, the next turn goes back to 10 and 200. Clearly deep accepted equations can add one step on the wider turn. They do not keep a turn the share has given back. Until a block of 20 exists, the turn stays at the baseline.

A repeat of text already in the database does not spend a place in the turn. Weak tries in a row (a repeat, a badly formed sentence, no proof, a refutation) stop the writing and send the model through the corpus again. That stop is 8 at the baseline, 12 on the wider turn, and 16 on the widest. A full 128 in the model's lane also holds the writing, without spending the turn. The generator keeps going: it is still the source of sentences the model can study.

The transformer has about 50 million parameters and a window of 512 tokens, counting the `<|propose|>` or `<|prove|>` mark and `<|end|>`. It trains from scratch on the closed prefix of `proved` sentences. Beside the weights, the run stores Adam's two moment buffers, so a later resume keeps the same step size. The weights are written every 20 training steps. The moment buffers, about 400 MB, are written every 500 steps and when the process stops. A checkpoint written before that file existed still starts Adam fresh once. A sentence that does not fit gets the database status `blocked by context limit` and waits until the window can hold it. It does not enter the weights as a cut-off piece. The mechanics are in `docs/continuous-ai-architecture.md`.

From the repository root:

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"

python3 -m theorem_gen.learn start --run-id run-1 --until-pause --lm
```

Defaults: database `var/learn.sqlite` (the `var/` directory is in `.gitignore`), curriculum 1, seed 1, four theorems per batch, Lean timeout 60 s, checkpoint every 300 s. `--until-pause` removes the limit of 50 steps. The process runs until SIGINT or SIGTERM. Lean checks run in two processes (`--lean-workers`, default 2). One process stays the only SQLite writer. `--lm` turns the transformer on. Provenance shows whether a sentence was written by `generator` or `model`. Model progress:

```sql
SELECT step, epoch, cursor_id, replay_id, last_loss, hold, weak_streak
FROM lm_state WHERE run_id='run-1';
```

`hold = 1` means the model has stopped writing for a while and is reading the corpus again. A rising `step` does not set `learning: yes`.

Effort in this fragment is a level from 1 to 4: proof method together with `ast_size` and `depth`. The size of a numeral in the formula is not difficulty. `decide` on a small tree is 1, ordinary `rfl` is 2, a larger tree or `lemma` is 3, `rewrite` or a tree from `ast_size` 12 is 4. Model rows without an AST get no level from 1 to 4. The equation text still stores depth, operator count, and node count, and the dashboard charts those. From migration 008, new Lean checks store `lean_ms`: under 0.1 s, 0.1–0.5 s, 0.5–2 s, above 2 s. Older validations have no time.

A read-only view of the run, not a second writer:

```sh
python3 -m theorem_gen.learn dashboard --run-id run-1
```

The page is in English at `http://127.0.0.1:8765/`. The numbers stay in fixed places and refresh every 5 seconds. The first cards are the model's own equations: how many Lean accepted, and that count over the ones Lean has already judged. The latest sentences are listed with the training step, the loss, and the shape of the text from the moment they were written. Freedom shows Baseline until a block of 20 judged equations exists, then the budget that block earned.

One chart is the accepted share across the whole history: the last 10 judged equations, the share from the first, and a margin bar for each block of 20. Two more charts measure the accepted equations, separate from that budget. One is mean syntactic depth, the last 10 and the mean from the first, with a 95% interval on every 20. The other counts operators the same way. Depth, operator count, and node count are the same three counts as the generator's syntax tree. A numeral of any size is one leaf. Text that is not a statement of this fragment is left out, not stored as zero. The three numbers are written on `model_attempts` when the equation is written.

"New material" counts `proved` sentences the first read has not reached. Replay is not in that number. "Model may write" shows how many recent steps in a row have loss under 0.45.

```sql
SELECT equation, disposition, lm_step, loss, expr_depth, expr_operators, expr_size
FROM model_attempts WHERE run_id='run-1' ORDER BY id;
```

Database state, including while the loop is running:

```sh
python3 -m theorem_gen.learn status --run-id run-1
```

Stop a live process with Ctrl-C or `kill -TERM` on its PID. The signal does not cut Lean calls that have already started: the loop finishes the current group (each one at most `--timeout`), applies pending weight steps, releases leases, writes the pause checkpoint, and exits 0. Do not start a second `start` or `resume` on the same database while the first process is alive.

Continue the same run:

```sh
python3 -m theorem_gen.learn resume --run-id run-1 --lm
```

A run started with `--until-pause` resumes until the next signal. An explicit `--max-steps` on `resume` limits only that resume. Jobs left in the queue are finished; new batches arrive when there is room. `SIGKILL` does not write a pause checkpoint. `resume` then returns to the last known checkpoint (start, or the 300 s interval) and takes over orphaned leases.

Replay from the start checkpoint, on a separate database `var/learn-replay.sqlite`:

```sh
python3 -m theorem_gen.learn replay --run-id run-1 --from-checkpoint 1
```

That repeats a recorded run. It does not continue one. Continuing the live database is `resume`.

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

- `docs/continuous-ai-architecture.md` — the loop, statuses, gates, queue, model
- `docs/continuous-ai-schema.sql` — the SQLite schema
- `docs/continuous-ai-report.md` — commands actually run for that delivery
- `docs/prompts/build-continuous-lean-ai.md` — prompt for the continuous loop
- `docs/stage-0.md` — environment and technical decisions for the generator
- `docs/architecture.md` — modules and the verification contract
- `docs/stage-1.md` … `docs/stage-8.md` — generator stage reports
- `docs/stages.md` — completion criteria for stages 0–8
- `docs/prompts/audit-lean-generator.md` — prompt for an independent audit of stages 0–8
