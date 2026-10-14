# Formula repair: twenty openings, then four endings

> Last updated: 2026-10-14
> Branch: `main` (uncommitted)
> Status: done
> Writer: stopped 2026-10-14 with SIGTERM. `run-3` is `paused` at step 18404, phase `done`, cycles 200. Result: `docs/run-3-repair-result.md`. Do not resume.

## Problem & goal

Lean rejects a whole file when one character is wrong, so a long formula never becomes a lesson. This run keeps the generator queue and the same small model. The model still writes formulas from `<|propose|>`. After Lean names a column inside that formula, the same model continues from the prefix Lean managed to read. Done means `run-3` is writing under that rhythm and a later read can say whether any ending got further, and whether any formula was accepted.

## Scope

- **In scope:** `run-3`, fresh weights, 20 formula draws, one argmax stored apart, up to two rounds of 4 endings, dashboard labels, README.
- **Out of scope:** an external model, switching the prompt to `<|prove|>`, resuming `run-1` or `run-2`, deleting `var/learn.sqlite` or `var/lm/run-1/` or `var/lm/run-2/`, setting `learning`, changing `default_lean_workers()`.

## Key files & context

| Area | Path | Role |
|------|------|------|
| Rules | `theorem_gen/learn/probe.py` | 20 draws, 4 endings, second round only if the prefix grew |
| Loop | `theorem_gen/learn/minilm.py` | Repair phase continues `<|propose|>` plus the kept letters |
| Schema | `theorem_gen/learn/migrations/015_repair.sql` | `error_at`, `repair_ply`, repair phase |
| Page | `theorem_gen/learn/dashboard.py` | Twenty, endings, furthest characters read |
| Tests | `tests/test_learn_probe.py` | Progress, rhythm, continuation still wrapped as a formula |
| Reading | `docs/run-3-repair-can-show.md` | What a success can mean, and what it cannot |
| Paused | `var/lm/run-2/` | Hundred-draw pilot, do not resume |

## Decisions

- 2026-10-13: The generator queue still produces proofs. The model, between training steps, still proposes formulas. Repair does not call another model.
- 2026-10-13: Twenty openings, then four endings from the furthest `error_at` inside the formula. A second four opens only when a child `error_at` is strictly larger. No third round. An accepted formula skips the endings.
- 2026-10-13: An error in `theorem model_eq :` or in the stapled `:= rfl` is not progress inside the formula, so it does not open an ending.
- 2026-10-13: `run-3` has new weights. `run-2` stays paused at step 49.
- 2026-10-13: The dashboard heading is the run with status `running`. A `--run-id` is used only when every run is paused.
- 2026-10-14: After cycle 200 the model stops writing formulas. The first read continues, one page per tick, so new material can fall to 128. The generator stays closed above that cap.

## Progress

- [x] Migration 015, repair tick, `--repair`
- [x] Dashboard copy for the twenty and the endings
- [x] `run-2` paused with SIGTERM
- [x] Tests for the rule and the rhythm
- [x] `run-3` running (`--repair`, dashboard on port 8765)
- [x] Dashboard lists formulas the model wrote that Lean accepted, newest first, apart from latest tries
- [x] Generator waits while new material is above 128. Dashboard says so on the New material card.

## Next steps

1. Leave the writer as the only SQLite writer. The generator stays idle while new material is above 128.
2. Read the result against `docs/run-3-repair-can-show.md`. The model reached cycle 200 and stopped writing. The first read stopped with it, so the pile does not shrink on its own.
3. Do not set `learning`. Do not resume `run-1` or `run-2`.

## Blockers / open questions

- Early formulas are still byte soup. Endings open only when Lean's error sits inside the formula text. Until that happens, a cycle is twenty draws and no repair.

## Verification

```sh
python3 -m unittest tests.test_learn_probe tests.test_learn_minilm tests.test_learn_dashboard tests.test_learn_store
```

2026-10-13: 64 tests passed.
