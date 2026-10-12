# Continuous Lean + SQLite loop

> Last updated: 2026-10-12
> Branch: `main` (`2c88b10`, pushed)
> Status: in progress
> Audit: `met_with_limitations` (`docs/continuous-ai-audit.md`), pass of 2026-10-12

## Problem & goal

The loop must be stoppable and resumable: proposal → Lean 4 → status → SQLite. "Done" for that delivery: the schema, the queue, the checkpoint, the Lean adapter, a curriculum from the existing `generate()`, and three roles only after the level 6 gate. We do not claim the model already solves hypotheses. `learning` is true only when a saved champion beats the baseline on held-out.

## Scope

- **In scope:** `theorem_gen/learn/`, tests, `docs/continuous-ai-*.md`, pointers in the README and `docs/architecture.md`.
- **Out of scope:** Mathlib, three copies of a model in RAM, online fine-tune, a quiet change to the stage 0–8 generator and the golden `lean/TheoremGen/Generated.lean`.

## Key files & context

| Area | Path | Role |
|------|------|------|
| Architecture | `docs/continuous-ai-architecture.md` | Loop, statuses, gates, RAM |
| Schema | `docs/continuous-ai-schema.sql` | Concatenated migrations 001–013 |
| Audit | `docs/continuous-ai-audit.md` | Verdict and the acceptance matrix |
| Report | `docs/continuous-ai-report.md` | Commands from that pass |
| Memory | `docs/continuous-ai-memory.md` | Control-plane RSS |
| Package | `theorem_gen/learn/` | Store, queue, engine, CLI |
| Tests | `tests/test_learn_*.py`, `tests/learn_support.py` | unittest, no new dependency |
| Stages 0–8 base | `.cursor/work/lean-theorem-generator.md` | Closed; this loop does not rewrite it |

## Decisions

- 2026-10-11: Status is computed by `derive_outcome` from `validations` only. Role text is not an input.
- 2026-10-11: `quarantined` is a defect (a proof and a certificate at once), not a fifth synonym of a mathematical result.
- 2026-10-11: One process, one `ModelSlot`. The default backend loads no weights.
- 2026-10-11: Checkpoint 300–600 s, default 300. Write through `os.replace`, the `known_good` row after the file is replaced.
- 2026-10-11: A new run starts only at level 1. Promotion requires 1000 Lean evaluations, three windows, and no held-out regression. `training_loss` is ignored. The number 1000 does not grow with the level. Level 2 counts only `generate_general`, level 3 one `wide_ast`, level 6 the `double` definition and theorem. Levels 4 and 5 do not raise the threshold.
- 2026-10-11: Roles from level 7. The alternate in the prove phase does not get the primary proof.
- 2026-10-11: `diversity` / `resource` in the baseline score are the generator's constants 1.0, not a measurement of the network.
- 2026-10-11: The loop adapter rejects import. Stage 0–8 `verify.py` did not gain an `import` ban.
- 2026-10-11: `Engine.promote_model` checkpoints only a promotion. A challenger rollback does not write a snapshot.
- 2026-10-11: The LCG got `get_state` / `set_state` for the checkpoint. The draw sequence without that call does not change.
- 2026-10-11: The audit added migration 002. Status starts as `unresolved` and must match the validations. A proof source is bound by a hash. Level 7 replay takes `raw_response`. The constants `diversity=1` and `resource=1` do not turn `learning` on.
- 2026-10-11: Missing `lake` (`unavailable`) does not close a validation. The job returns to the queue, the run stops, the CLI returns an error. A later `resume` can finish the same candidates. An `unavailable` step counts as idle.
- 2026-10-11: Second audit. An accepted `check` has `accepted=0` and leaves `unresolved`. A timeout does not enter the threshold of 1000. A certificate INSERT must point at the same candidate. Resume compares the LCG and the scheduler with the snapshot file. A proposal has three tries, then the next index. A run with no first checkpoint can be resumed if there are no jobs or candidates yet. "is not a proposition" is a typing error.
- 2026-10-12: The `start` and `resume` CLI add the next batch when the queue is empty and the step budget is still running. Crash tests stay at one queue drain. Replay of a finished budget repeats that budget from the start checkpoint. Migration 001 can be repeated when the script ran without a version row.
- 2026-10-12: A candidate's identity is immutable after insert. Status and `updated_at` may be rewritten. Lean 4.34.1 syntax phrases (`unexpected end of input`, `unexpected identifier`, `expected command`) are `syntax` and win over `unsolved goals`.
- 2026-10-12: A step budget that falls in the middle of a batch finishes `lean_validate` jobs already queued and does not open the next batch. `--max-steps 0` does not call Lean. A failed proposal stays in the queue.
- 2026-10-12: From level 2 a batch adds a review of an earlier level (`review`, rotation by `batch_index`). The review is validated and enters the training corpus, and not the threshold of 1000 or the promotion windows.
- 2026-10-12: A loop batch skips hashes already stored in the run. After numerals 0..9 are exhausted it raises the cap by 10, without changing the default `generate` and without resetting the database.
- 2026-10-12: Concurrency stays at one SQLite writer. `lean_validate` runs in a pool of `lean` processes. Default 2, so there is spare room for QLoRA. `train_items` and `online_weights` (migration 005) are a small linear vector, not 7B weights.
- 2026-10-12: 7B QLoRA progress is one `qlora_state` row (migration 006): `step`, `cursor_id`, `last_loss`. Lean text is not copied. `learning` stays `no`.
- 2026-10-12: Qwen QLoRA was dropped. In its place a transformer from scratch, about 50M (`--lm`). Migration 007 drops `qlora_state` and adds `lm_state` and `model_attempts`. Order: new `proved` past the cursor, then a `<|propose|>` sample. A duplicate equation does not go to Lean. Eight weak samples set `hold` and return to a corpus pass. `learning` stays `no`. Origin: `provenance.origin` = `generator` or `model`.
- 2026-10-12: Effort 1–4 comes from the proof method plus `ast_size` and `depth`, not from the size of a number. `model` with no AST gets no level. Migration 008 adds `validations.lean_ms` on new checks. The page: `dashboard`, read-only, port 8765.
- 2026-10-12: On the page, columns 1–4 name the proof shape (`decide`, `rfl`, `lemma`, `rewrite`). The header says "Curriculum lesson N of 7", so they are not confused with the generator's lessons.
- 2026-10-12: Model attempts on the page have 10-minute windows and a better/weaker/same sentence. The time is `created_at` of the stored equation. `queued` does not enter the share.
- 2026-10-12: "Still to read" was `proved`, `held_out=0`, and `id` greater than `lm_state.cursor_id`. That was the same number as `_untrained`. An own equation waited until it hit 0. One weight refresh read 4 such sentences. Later the same day the cursor was changed to stop at the first open check, and writing no longer waits for an empty pile.
- 2026-10-12: The clock "Time until it may write" was `unread / the rate unread shrank` over the last minute in the browser. New `proved` rows were already in that rate. The first 20 seconds showed Measuring. The card was later retitled "Time to finish this read" and is no longer the writing condition. The same day the clock was removed. The remaining count is "New material": proved sentences the first read has not reached. Replay is not in that number.
- 2026-10-12: `run-1` resumes with `--lean-workers 4` (it was 2). The Lean queue is often empty anyway, because the generator at depth 2 yields about one new sentence per batch. The four workers are for later model samples. The default function stays 2. Do not widen the generator during the first read.
- 2026-10-12: the model starts writing when 10 losses in a row are < 0.45. One turn is 10 equations in the Lean queue, then 200 study steps. Migration 010.
- 2026-10-12: the cursor stands on the first sentence without a verdict. 128 unfinished Lean checks are separate for the generator and for the model.
- 2026-10-12: the "Model may write" card shows the stage: `n/10`, Yes, Studying, Waiting, or No.
- 2026-10-12: a training step is four `proved` sentences. A shorter piece in front of an open check waits and is not its own step.
- 2026-10-12: the README leads with the hypothesis of a model that reads only sentences Lean has accepted. The generator is the source of the first sentences. The repository text is in English.
- 2026-10-12: When the forward read has nothing new, a replay walks proved rows already behind the cursor, generator and model together, by id. `lm_state.replay_id` (migration 011) is the last id included. A resume continues after it. The walk returns to 0 at the cursor. Replay does not enter the loss streak.
- 2026-10-12: The headline on the page is own equations Lean accepted. Migration 012 stores `lm_step` and `loss` on `model_attempts` at the moment of writing. A repeat is not an acceptance. There is no difficulty grade, because a model sentence has no syntax tree.

## Progress

- [x] Architecture, schema, handoff
- [x] SQLite, migrations, idempotency, triggers
- [x] Queue, pause, resume, three crash points, replay
- [x] Lean adapter and classification
- [x] Curriculum 1 on `generate()`, gates through the stage 6 capabilities
- [x] Three roles as a stage 7 helper, after the gate
- [x] Retrieval, corpus selection, challenger adjudication (no weight training)
- [x] Documents with measured commands
- [x] Parallel Lean checks and a weight-step queue (migration 005), without resetting `run-1`
- [x] 2026-10-12: every proposal adds one `richgen` sentence beside the old batch (`--lean-workers 4` unchanged)
- [x] 2026-10-12: network context 512. `run-1` weights stay, because the window is not a parameter dimension and the cursor had not yet reached `richgen`
- [x] 2026-10-12: a sentence longer than the window, marks included, gets `context_blocks.status = blocked by context limit` and waits. Epoch 0 does not end while such a row is waiting
- [x] 2026-10-12: model writing starts when 10 losses in a row are < 0.45. One turn is 10 equations in the Lean queue, then 200 study steps. Migration 010.
- [x] 2026-10-12: the cursor stands on the first sentence without a verdict. 128 unfinished Lean checks are separate for the generator and for the model.
- [x] 2026-10-12: the "Model may write" card shows the stage: `n/10`, Yes, Studying, Waiting, or No.
- [x] 2026-10-12: a training step is four `proved` sentences. A shorter piece in front of an open check waits and is not its own step.
- [x] 2026-10-12: README leads with the model hypothesis. The generator is the source of the first sentences. Docs are in English.
- [x] 2026-10-12: Adam moments are saved in `var/lm/<run>/adam.safetensors` next to the weights. A checkpoint without that file still starts Adam fresh.
- [x] 2026-10-12: Adam is written every 500 training steps and on stop. Weights stay on the 20-step cadence.
- [x] 2026-10-12: Replay walks already-read proved rows by id when the forward read is idle. `replay_id` resumes that walk.
- [x] 2026-10-12: The finish-this-read clock is gone. "New material" counts proved sentences the first read has not reached. Replay is not in that number.
- [x] 2026-10-12: The page leads with own equations Lean accepted. Each attempt stores the step and loss from the moment it was written.
- [x] 2026-10-12: Accepted share is a line over the whole history, last 10 judged and from the start. A later fall stays visible.
- [x] 2026-10-12: A block of 20 widens the next turn only when its Wilson interval sits wholly above the previous block. A wholly lower block narrows the turn by one step. Steps: 10/200/8, 20/100/12, 40/50/16.
- [x] 2026-10-12: The same block also moves one step when the nesting depth of the accepted equations clears the margin and the accepted share does not move the other way. Depth 1, 2, and 3+ are the bands. A numeral's size and Lean's elapsed time are not inputs.
- [x] 2026-10-12: Freedom is the latest block of 20, not a ratchet. Lower Wilson bound above 1/2 is the wider turn, above 3/4 the widest. At or below 1/2, including an average block, the turn returns to 10 equations and 200 study steps at once. Deep accepted equations add one step only while the share is already above 1/2.
- [x] 2026-10-12: Migration 013 stores `expr_depth`, `expr_operators`, and `expr_size` on `model_attempts` at the moment of writing. NULL is unparsed text, not depth 0. The page charts mean depth and mean operator count of accepted equations, with a 95% interval on each block of 20.

## Next steps

1. `run-1` resumes with `--lm` and `--lean-workers 4` on the live process. Do not start a second writer. Qwen stays outside the loop.
2. The `train_items` queue updates a small vector. 7B LoRA stays offline, on `select_training_rows`, and only if the challenger's held-out beats the champion.
3. Do not set `learning: yes` by hand. It has to come from `learning_claimed`.

## Blockers / open questions

- No local 7B weight. The RSS measurement does not cover a process with a 7B model.
- A full 1000 real Lean calls per level was not run as a production run. The accepted-proof gate is checked on a cohort. The live run `run-1` (`var/learn.sqlite`, `--until-pause`) ran on Lean 4.34.1: SIGTERM wrote a pause checkpoint, `resume` finished three pending validations and went further. `learning` stays `no`.
- A consistent `validations` row inserted by SQL, bypassing the adapter, still sets a status. The engine does not write that way.
- Replay onto a fresh database does not copy the queue it finds. Continuing a live database is `resume`.

## Verification

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m unittest discover -s tests
python3 -m compileall -q theorem_gen tests
git diff --check
python3 -m theorem_gen.learn memory
```

Result on 2026-10-12 after the Lean pool and the weight queue: `Ran 202 tests in 9.619s` / `OK`. Earlier that day: `Ran 192 tests in 14.546s` / `OK`. Earlier that day compileall, `git diff --check`, and `lake --dir lean build` exited 0. Memory: `peak_rss_bytes: 16646144`, `weights_loaded: no`, exit 0. CLI `--max-steps 2 --count 1`: two `proved`, `learning: no`, replay from checkpoint 1 `replay_match: yes`. Default budget `seed=1`, `count=4`, `max_steps=50`: 52 `proved`, an empty queue, zero `failed`, `learning: no`.

Live run 2026-10-12, `var/learn.sqlite`, `run-1`, `--until-pause`: after start, 52 candidates (48 `proved`, 4 still without a validation). `SIGTERM` ended the process with exit 0. Database: `integrity_check=ok`, no duplicate `stable_id`, 49 `proved`, 3 `lean_validate` in the queue, checkpoint 2 with reason `pause`, `learning: no`. `resume` marked those three `proved` and reached 60 candidates (59 `proved`, 1 in an open batch), zero `failed` jobs, status `running`. `status` during the run returns exit 0. Log: `var/learn-run-1.log`. Audit details: `docs/continuous-ai-audit.md`.
