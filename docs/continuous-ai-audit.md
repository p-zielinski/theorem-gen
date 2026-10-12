# Audit of the continuous Lean AI loop

> Date: 2026-10-12. Branch: `main`.
> Verdict: `met_with_limitations`

The audit followed the code and the commands run in this pass. The previous report was not a verdict. Reading the status path found two gaps: a candidate's identity could be rewritten under a status already computed, and real Lean 4.34.1 syntax messages left the candidate `unresolved`. Both are fixed and covered by tests.

## Answers

The engine will not store a false `proved` or `refuted`. Role text, a Python witness without a matching claim, a timeout, a forbidden construction, a file whose hash differs from `bound_source`, an inconsistent `accepted` / `result` pair, an accepted `check`, and a claim swapped after insert do not set those statuses. `current_status` can be set only to a value derived from `validations`. `accepted=1` requires `result='accepted'` and type `proof` or `counterexample`.

A separate path remains: a process with access to the SQLite file can insert a consistent `validations` row (`accepted=1`, `result='accepted'`, type `proof` or `counterexample`) without running Lean. The status will follow that row. That is how the 1000 cohort fixture works. The CLI does not use this path.

Pause, resume, and replay survive the three required crash points and a fourth, after `os.replace` and before the `known_good` row. Resume neither loses nor duplicates `attempts`. An orphan checkpoint file does not become `known_good`. A scheduler committed together with a proposal is advanced by the `scheduler_committed` event. Level 7 replay calls the recorded `raw_response`. Level 1 has zero model calls, because the proposal is from the generator. A substituted `rng_state` in the checkpoint row is rejected when the snapshot file has a different seed. The suite that exercises these points ended `OK`.

Do not write that the system is learning. No weights were loaded in this pass. `learning_claimed` stays false while the champion and the baseline both have the constants `diversity=1` and `resource=1`, or while the active version is `champion-generator-v0`. The CLI printed `learning: no`.

## Findings

### medium — the claim could be swapped under status `proved`

The trigger `candidates_status_matches_validations` in `theorem_gen/learn/migrations/002_integrity.sql` watches only `current_status`. An `UPDATE` of `canonical_ast_json`, `structural_hash`, `proof_method`, or `ast_size` went through. After a real proof a different claim could be written, or `ast_size` raised, and the status stayed.

Reproduction: after `upsert_candidate`, run `UPDATE candidates SET canonical_ast_json='{"rewritten":true}'`. Before migration 004 SQLite accepted that write.

Tests did not see it. They checked inserting `proved` with no validation and an `UPDATE` of the status alone. They did not try to rewrite the claim.

Fix: `theorem_gen/learn/migrations/004_identity.sql`. On `UPDATE`, `current_status` and `updated_at` may change. The rest of the identity and the gate metrics are frozen. `docs/continuous-ai-schema.sql` is the concatenation of migrations 001–004.

### medium — Lean 4.34.1 syntax stayed `unresolved`

`classify_lean_failure` in `theorem_gen/verify.py` looked for `unexpected token`, `expected term`, and `expected token`, and it did that after the proof bucket (`unsolved goals`). The real file `theorem bad : (0 = 0) :=` yields `unexpected end of input` and class `other`. The file `this is not lean` yields `unexpected identifier; expected command`. A file with `???` in a tactic yields both `unsolved goals` and `unexpected token`, so the proof bucket won. `derive_outcome` for class `other` or `proof` leaves `unresolved`, not `ill_formed`.

Reproduction: `validate_source` of those three sources on Lean 4.34.1, before the phrase order changed.

Tests did not see it. The syntax stub supplied exactly `unexpected token` / `expected term`. It did not emit the message this Lean emits.

Fix: the phrases `unexpected end of input`, `unexpected identifier`, and `expected command` are syntax, and syntax is checked before `unsolved goals`. `Unknown identifier` stays class `other` — that split is in `test_syntax_and_typing_are_separate_from_proof` and was not moved. Real Lean in `test_real_lean_accepts_a_proof_and_a_negation_certificate` checks a cut-off proof and a file that is not Lean.

## What was checked and holds

- `proved` and `refuted` come out of `derive_outcome` only with `accepted` and `result='accepted'` and type `proof` or `counterexample`. The trigger on a status UPDATE counts the same way.
- A candidate starts as `unresolved`. An accepted `check` has `accepted=0` and stays `unresolved`. A timeout and `unavailable` do not enter the threshold of 1000.
- A `proof` or `check` source must have its hash in an immutable `bound_source` event. A counterexample is recomputed from that candidate's assignment and claim. A certificate on INSERT and UPDATE must point at an accepted `counterexample` validation of the same candidate.
- `sorry`, `axiom`, `opaque`, `unsafe`, `#eval`, `run_io`, `run_cmd`, and `import` at the start of a line are rejected before the process starts. `admit` is not on the word list. Lean 4.34.1 finishes it with exit code 0 and an incomplete-proof warning, and the adapter does not set `proved`. `sorryAx` does not pass the word filter for `sorry`, but Lean rejects it as typing, so there is no `proved`.
- `quarantined` arises only when an accepted proof and an accepted certificate exist together. `mathematical_outcome` returns `None`.
- WAL, `foreign_keys`, and `busy_timeout` are set on connect. Migrations 1–4 are skipped when the version is in `schema_migrations`. A script that ran without a version row can be finished (`IF NOT EXISTS` in 001, a repeat of 002–004). Two connections on the same idempotency key return one row.
- Queue: validation priority over a proposal, high-water, lease, heartbeat, reclaim after expiry, backpressure rewinds the whole scheduler including `last_mix` and does not stop Lean jobs. A proposal error has three tries, then the next index. `unavailable` returns to the queue and is an idle step.
- Checkpoint: interval 300–600 s, `os.replace`, then the `known_good` row. Verification compares the file hash and the LCG, scheduler, cursor, level, and freeze flag. A crash after `os.replace` leaves the previous `known_good`.
- Curriculum: a new run from level 1, no skips, threshold 1000, three full windows, `training_loss` is not an input, one promotion per window, a failed gate does not delete validations, roles from level 7. A numeral is not a measure of difficulty. A timeout cohort does not promote.
- Roles: the proposer does not store a verdict, the prover receives only the AST, the alternate in the `prove` phase gets `primary=None`, critique sees both artifacts, retrieval returns `stable_id`, status, and family. One `ModelSlot` does not hold a second resident copy. The text `{"verdict":"proved"}` does not change the status.
- Held-out does not enter `select_training_rows`. The descendant cap is 8. Balance goes by family, outcome, and `ast_size` band. A weaker challenger is `rolled_back` and does not write a promotion checkpoint.
- The `start` and `resume` CLI add the next batch when the queue is empty and the step budget is still running. A proposal key that is not `queued` is not inserted a second time. Replay of a finished budget from the start checkpoint repeats that budget. A `--until-pause` run does not enter an endless loop on replay.
- `python3 -m theorem_gen generate` to a temporary file exits 0. The golden `lean/TheoremGen/Generated.lean` is not in `git status`. The difference in `theorem_gen/verify.py` against `HEAD` is the earlier priority of the phrase "is not a proposition" and, in this audit, the syntax phrases. The stage 0–8 generator did not get a different verdict on an accepted proof.

## Acceptance matrix

| # | Test | Result |
|---|------|--------|
| 1 | The existing unittest stays green | pass — `Ran 192 tests in 14.546s`, `OK` |
| 2 | Migrations, FK, transactions, idempotency | pass |
| 3 | Role agreement does not mark a rejected file `proved` | pass |
| 4 | A Python witness with no certificate → `unresolved` | pass |
| 5 | A Lean certificate → `refuted` | pass — real `Not (1 = 0)` |
| 6 | Syntax / typing → `ill_formed`; timeout → `unresolved` | pass — after the phrase fix; `Unknown identifier` stays `unresolved` |
| 7 | Three crash points, zero duplicates | pass — the suite runs the dequeue, commit, and checkpoint-write hooks |
| 8 | Pause and resume restore the scheduler and the LCG | pass |
| 9 | An expired lease and backpressure | pass |
| 10 | Occupancy ≥ 80% when there is work | pass as a step counter, not CPU |
| 11 | Curriculum does not advance early or from `training_loss` | pass on a cohort, not on a thousand `lake` calls |
| 12 | A weaker challenger is rolled back | pass |
| 13 | Replay with no live model reproduces results | pass from the start checkpoint; level 7 takes `raw_response` |
| 14 | Peak RSS of inference, workers, and Lean inside an 18 GB budget | not_measured for a process with weights; control plane: `16646144` bytes, `within_budget: yes` |
| 15 | Forbidden constructions rejected despite role agreement | pass — the runner does not start; real Lean confirmed the refusal and `admit` |
| 16 | A report of commands actually run | pass — `docs/continuous-ai-report.md` |

## Commands of this pass

```sh
export ELAN_HOME="$PWD/.toolchains/elan"
export PATH="$ELAN_HOME/bin:$PATH"
python3 -m unittest discover -s tests
python3 -m compileall -q theorem_gen tests
git diff --check
lake --dir lean build
lean --version
lake --version
python3 -m theorem_gen.learn memory
python3 -m theorem_gen generate --seed 1 --count 1 --out "$TMP/Generated.lean"
python3 -m theorem_gen.learn start|status|pause|resume|replay …
```

Results: unittest `192` / `14.546s` / `OK` after the batch was closed. Earlier that day compileall and `git diff --check`: exit 0. Lake: `Build completed successfully (4 jobs).` Lean `4.34.1`, Lake `5.0.0-src+5045d00`. Memory: exit 0, `peak_rss_bytes: 16646144`, `weights_loaded: no`. Generate: exit 0, written to a temporary file. CLI `start --max-steps 2 --count 1`: two `proved`, `learning: no`, exit 0. `replay --from-checkpoint 1`: `replay_match: yes`. Bad arguments: the table in `docs/continuous-ai-report.md`. The engine, the same shape as `start` without `--max-steps`: 52 `proved`, an empty queue, zero `failed`, `learning: no`.

`git status` separates layers. Tracked differences from before this loop are `theorem_gen/rng.py` and `tests/test_rng.py` (`get_state` / `set_state`), entries in `README.md` and `docs/architecture.md`, `var/` in `.gitignore`, and a next-steps digest in `.cursor/work/lean-theorem-generator.md`. Tracked `theorem_gen/verify.py` and `tests/test_verify.py` carry the "is not a proposition" classification and the syntax phrases from this audit. The package `theorem_gen/learn/`, the tests `tests/test_learn_*.py`, and the documents `docs/continuous-ai-*` are untracked. The golden `lean/TheoremGen/Generated.lean` is not in the diff.

## Fixes

- `theorem_gen/learn/migrations/004_identity.sql` and the concatenation in `docs/continuous-ai-schema.sql`
- `classify_lean_failure`: Lean 4.34.1 syntax before the `unsolved goals` bucket
- tests of candidate identity, syntax phrases, and real Lean on a cut-off file
- architecture, the report, memory, and this file describe this pass
- a step budget finishes `lean_validate` jobs already queued and does not open the next batch; `--max-steps 0` does not touch the queue

## Limits that remain

- The 1000 cohort is a fixture with the shape of an accepted validation. A separate timeout cohort checks that a timeout alone does not promote. Real Lean: single files, a short CLI (`--max-steps 2 --count 1`), and the default budget of 50 steps at `count=4` (52 `proved`, an empty queue, zero `failed` jobs). A thousand `lake` calls per level were not run.
- A consistent `validations` row inserted by SQL, bypassing the adapter, still carries a status. The engine does not write that way. The same process can append a `bound_source` event, so the trigger "a hash must exist" does not close this path.
- Replay onto a fresh database reproduces a run from the scheduler, the LCG, and `attempt_cursor`. It does not copy the queue it finds. Continuing a live database is `resume`. Replay from a pause checkpoint starts from the LCG saved after the finished batches and gets the next theorems. Reproducing a run starts from the start checkpoint.
- Occupancy is a fraction of steps. A step that returned, was unavailable, or failed counts as idle. The loop does not call `heartbeat` during a blocking Lean call. One process still ends the lease in `complete`, because the loop has no `reclaim_expired`. A second process on the same database is not supported.
- RSS `16646144` is this process with no 7B weights and no Lean load.
- Stage 0–8 `verify.py` still does not reject `import`. The loop adapter rejects it before it calls `verify_source`.
- `Unknown identifier` stays class `other` and status `unresolved`. That is not `proved`.
- `admit` is not on the word list. Lean reports it as an incomplete proof and the adapter does not set `proved`.
