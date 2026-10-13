# run-1, greedy decoder: result

> Paused: 2026-10-13, SIGTERM. Status in `runs` is `paused`.
> Weights: `var/lm/run-1/model.safetensors`. Adam moments stay beside that file.
> Database: `var/learn.sqlite`, run id `run-1`. Not reset.
> Champion: `champion-generator-v0`. `learning` was not set.

This note is the measurement. What the loop is able to show at all is `docs/what-the-run-can-show.md`.

## What was running

A transformer of about 50 million parameters, context 512, trained from scratch on sentences Lean had accepted. No pretrained weights. The sampler in `theorem_gen/learn/minilm_model.py` takes the character with the largest logit. The same prompt and the same weights therefore always continue with the same character.

A turn started when ten losses in a row were under 0.45, or when the last 80 forward losses sat level. The length of a turn followed the accepted share of the latest 20 finished tries. That share stayed at 0, so the turn stayed at the baseline: 40 tries, then 40 study steps. A repeat spends one of those tries and does not go to Lean.

## Loss

Logged forward steps in `var/learn-run-1.log` (`lm step=`, not replay):

| Step | Median loss in that band | Cursor around there |
|------|--------------------------|---------------------|
| 20 | 3.37 (the first logged step) | 80 |
| 4,000–14,000 | 0.32–0.37 | short generator sentences |
| ~18,000 | steps up to about 0.59 | ~77,000, longer equalities |
| 76,000–78,000 | 0.61–0.63 | past 150,000 |

At the pause: step 79,812, epoch 1, cursor 154,977, replay id 101,191, last loss 0.668.

The drop from 3.37 to about 0.32 is the model learning the short prefix. The step up to about 0.6 is the corpus changing to longer equalities and longer theorem names, whose fresh digits the model cannot predict. Ten losses in a row under 0.45 did not return after that step. Writing opened because the curve was level, not because loss had fallen through 0.45. Bands near 0.32 later in the log are short sentences being read again. They are not a second crossing of that door.

## What the model wrote

18,032 finished tries. 125 distinct strings. None contains `=` or `:=`.

| Verdict | Count |
|---------|------:|
| Repeated something already in the run | 17,907 |
| Not a valid formula | 125 |
| Lean accepted it | 0 |
| Lean could not prove it | 0 |
| Lean refuted it | 0 |
| Waiting for Lean | 0 |

The 125 strings are theorem names whose digits collapse. The most common, 9,200 times, is `gen_s6` followed by a run of the digit `1`. The others are the same shape with a different digit, or a short prefix and then a run of zeros. Each distinct string was sent to Lean once, rejected as not a formula, and every later copy was counted as a repeat. The last 10-minute windows on the dashboard matched each other: a few hundred repeats, one not-a-formula, zero accepted. The share was not drifting.

The generator pile at the pause: 151,301 candidates `proved`, 3,551 `unresolved`, 125 `ill_formed` (those are the model's names). Historical failed `propose` jobs: 8,637, unchanged through the writing phase. Curriculum level 7.

Accepted share is 0 / 18,032. There is no depth or operator mean, because nothing accepted had a shape to measure.

## Conclusions

1. This decoder on these weights does not write an equation. It writes one of 125 names and then repeats it. More turns of the same argmax do not change that. The stop in `docs/what-the-run-can-show.md` (the first blocks of judged tries are repeats and rejections) was passed many times over.
2. A longer turn and a level-curve door only bought more copies of those names. The policy worked. The text did not.
3. Loss near 0.6 is the cost of unpredictable digits in names and numerals. It is not evidence that a new theorem was about to appear.
4. The run does not say whether some other character, with smaller logit, would have started an equation. Argmax never asks. That is the unread measurement.
5. `learning` stays off. The champion stays the generator. This network was not a challenger, and a pile of repeated names is not a reason to flip the flag by hand.

Resuming `python3 -m theorem_gen.learn resume --run-id run-1 --lean-workers 4 --lm` continues this same decoder. Do that only to reproduce the table above.

## Next measurement

Ready, not running. Start it with `python3 -m theorem_gen.learn start --run-id run-2 --until-pause --lm --probe --lean-workers 4`. That creates new weights in `var/lm/run-2/` and a new run in the same database. `run-1` stays paused.

The rhythm is fixed, so the accepted share is a reading and not a throttle:

1. One training step on four sentences the generator has already proved. An empty corpus does not draw.
2. One hundred texts drawn from those weights, then one extra text with argmax, stored apart so it is not one of the hundred.
3. A text with no equation is "not a formula" and does not go to Lean. A text already in the run is a repeat. A new equation goes to Lean. After that hundred is judged, each accepted new equation is one immediate training step. Then the rhythm returns to step 1.

Decoder for the hundred: temperature 1, nucleus top-p 0.9. Tests keep argmax unless they opt in. Each probe attempt records which decoder wrote it.

The number that says the hundred was a search is how many of the hundred differ. If that stays near 1, the distribution is still a single mode.

The model stops after 200 cycles. If the distinct strings are still names without `=`, the following change is the propose-role target, not a wider network and not a penalty on the logit. Do not reset `var/learn.sqlite`. Do not delete `var/lm/run-1/`. Do not set `learning`.
