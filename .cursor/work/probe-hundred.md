# Probe: one step, then a hundred draws

> Last updated: 2026-10-13
> Branch: `main` (uncommitted)
> Status: paused
> Result of the closed run: `docs/run-1-greedy-result.md`
> Live experiment: `.cursor/work/formula-repair.md` (`run-3`)

## Problem & goal

`run-1` showed that argmax on these weights writes one of 125 names and no equation. `run-2` drew a hundred texts per step and was paused on 2026-10-13. Do not resume it. The live measurement is `run-3`.

## Scope

- **In scope:** a new run id, new weights, fixed rhythm, nucleus sampling, one argmax line stored apart, dashboard cycle cards, README.
- **Out of scope:** resuming `run-1`, deleting `var/learn.sqlite` or `var/lm/run-1/`, setting `learning`, a repetition penalty, a depth reward, starting the process.

## Key files & context

| Area | Path | Role |
|------|------|------|
| Rhythm | `theorem_gen/learn/probe.py` | Hundred, then one argmax. Temperature 0 is argmax |
| Loop | `theorem_gen/learn/minilm.py` | Probe tick: train, draw, wait, teach |
| Decoder | `theorem_gen/learn/minilm_model.py` | `complete` takes temperature and top-p |
| Schema | `theorem_gen/learn/migrations/014_probe.sql` | `decoder`, `cycle`, probe phase |
| Page | `theorem_gen/learn/dashboard.py` | Cycle, distinct, accepted, argmax |
| Tests | `tests/test_learn_probe.py` | Pick, rhythm, page counts |
| Closed run | `docs/run-1-greedy-result.md` | Why argmax stopped |

## Decisions

- 2026-10-13: `run-2` is a new run in the same database. Weights are `var/lm/run-2/`. `run-1` stays paused.
- 2026-10-13: The rhythm is one real training step, then 100 samples at temperature 1 and nucleus 0.9, then one argmax. An empty corpus does not draw. Non-equations do not go to Lean. Accepted new equations are taught one at a time after the hundred is judged, then the next generator step opens the next hundred.
- 2026-10-13: Distinct-per-100 is the sign that the draw searched. The argmax line is excluded from that hundred and from the verdict table.
- 2026-10-13: The model stops after 200 cycles. No logit penalty and no depth reward in this run.

## Progress

- [x] Migration 014, sampler, probe tick, CLI `--probe`
- [x] Dashboard cycle cards
- [x] README and the closed-run note
- [x] Tests for the pick, the rhythm, and the page split
- [x] `run-2` started by the user and paused on 2026-10-13 (step 49, phase draw)

## Next steps

1. Do not resume `run-1` or `run-2`. The live run is `run-3` in `.cursor/work/formula-repair.md`.

## Blockers / open questions

- None in the code. The run itself has not started, so there is no loss curve yet.

## Verification

```sh
python3 -m unittest tests.test_learn_probe tests.test_learn_minilm tests.test_learn_dashboard tests.test_learn_store tests.test_learn_replay
```

2026-10-13: those 60 tests passed. A wider `test_learn*.py` run still has 7 failures in `test_learn_outcome` and `test_learn_runtime` that count one extra generator sentence (`richgen`) per batch. That count is on `main` and was not changed here.
