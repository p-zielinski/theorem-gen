# run-3, formula repair: result

> Paused: 2026-10-14, SIGTERM. Status in `runs` is `paused`.
> Weights: `var/lm/run-3/model.safetensors`. Adam moments stay beside that file.
> Database: `var/learn.sqlite`, run id `run-3`. Not reset.
> Champion: `champion-generator-v0`. `learning` was not set.
> Do not resume `run-3`. Do not resume `run-1` or `run-2`.

This note is the measurement. What the rhythm was able to show at all is `docs/run-3-repair-can-show.md`.

## What was running

A transformer of about 50 million parameters, context 512, trained from scratch on sentences Lean had accepted. No pretrained weights. No second model. The prompt was `<|propose|>`. Temperature was 1 and the nucleus was 0.9. One argmax line was stored apart from the twenty and is not in the verdict table.

One cycle, 200 of them. A training step on up to four proved generator sentences, then twenty formula draws from those weights. If none was accepted, four endings continued from the formula Lean had read furthest into. A second four opened only when one of those got strictly further. There was no third round. The `rfl` on the file was stapled by the loop. An accepted formula would have been taught. None was.

After cycle 200 the model stopped writing. The process was later resumed and kept reading the generator pile, one page per step, until this pause. That later reading is not a formula result. It is why the step counter is far past 200.

At the pause: step 18,404, epoch 1, cursor 188,274, replay id 172,020, last loss 0.661, phase `done`, cycles 200.

While the model was still writing, loss at step 200 was about 1.09. The fall from there to about 0.66 is the first read, and then the replay, of generator sentences. It is not evidence that the formulas improved. The formula rows stop at step 200.

## What the model wrote

5,496 finished sample tries, across 200 cycles (cycles 0 through 199). 5,318 distinct strings in the whole attempt table, samples and argmax together. The draw searched. It did not repeat one name the way `run-1` did.

The verdict table excludes the 200 argmax lines.

| Verdict | Count |
|---------|------:|
| Repeated something already in the run | 139 |
| Not a valid formula | 4,868 |
| Lean could not prove it | 489 |
| Lean accepted it | 0 |
| Lean refuted it | 0 |
| Waiting for Lean | 0 |

"Lean could not prove it" is the wrong label for almost all of those 489. The stored failure class is `other` on 481 of them: Lean rejected the file as syntax, and the classifier does not name that phrase, so the dashboard says the proof failed. The failure class is `proof` on 8 rows. Those eight are the only texts Lean elaborated far enough to complain about the mathematics:

| Step | Ply | Text | Lean |
|-----:|----:|------|------|
| 7 | 0 | `cmt52b2=b` | not a definitional equality |
| 62 | 1 | `ht=_0me0024go02020t` | not a definitional equality |
| 62 | 2 | `ht=_0me0024g00o` | not a definitional equality |
| 69 | 0 | `8=_n` | not a definitional equality |
| 70 | 1 | `h0=oe *5001 * 3` | not a definitional equality |
| 148 | 1 | `theoreorem gen_s1101…` | function expected |
| 156 | 0 | `theoreorem gen_s10010014014 = by` | function expected |
| 196 | 1 | `(1) <= (5)` | `rfl` closes an equality, and this is `<=` |

`(1) <= (5)` is the only line that is a real comparison. The stapled `rfl` cannot close it. It was not accepted.

The 200 argmax lines: 121 repeats, 69 not a formula, 10 unresolved, 0 accepted.

## Did an ending get further

`error_at` is how many characters of the formula Lean read before the error. It is not a distance to a true equation.

| | Cycles |
|--|------:|
| Opening cycles | 200 |
| Lean's error sat inside an opening | 196 |
| An ending was drawn | 196 |
| First ending read further than that opening | 178 |
| Second ending read further than the first | 152 |

Furthest character counts on sample rows: opening 58 among unresolved rows and 94 among rows that are not formulas; first ending 123; second ending 154. The long ones are runs of the same letter, such as `eeee…`, which Lean treats as one token and then rejects. A larger `error_at` happened. It did not become an acceptance.

Openings were 4,000 sample rows (20 times 200). First endings were 784. Second endings were 712.

## What this shows

The draw was diverse: thousands of distinct strings, not one looped name.

Lean's cursor did enter the formula, in 196 of 200 cycles. The repair branch was not idle.

Keeping the letters and redrawing the tail moved that cursor further, inside one cycle, with the weights held still. That happened in 178 cycles at the first ending and in 152 at the second.

No ending was accepted. No opening was accepted. The kept prefix plus a new tail never produced a file Lean accepted.

## What this does not show

It does not show that a longer prefix is closer to a true formula. The longer prefix is usually a longer run of junk.

It does not show that the model can prove. The proof on these files would have been the stapled `rfl`. The model did not write it.

It does not show that the network keeps developing as a formula writer. After cycle 200 it only reads generator sentences. Loss near 0.66 is that reading.

It does not show `learning: yes`. The champion is still the generator.

## After the 200 cycles

On 2026-10-14 the paused process was resumed because a resume printed nothing: phase `done` returns without a line, and the generator was held because 9,319 proved sentences sat ahead of the cursor. The resume was changed so that, after writing stops, the first read continues, one page per step, and prints `lm study`. The generator opens no batch while that unread count is above 128. By the pause the first read had caught up (epoch 1) and the study was a replay. Those steps did not add formula rows.
