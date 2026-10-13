# What run-3 can show

> Written 2026-10-13, while `run-3` is in progress.
> Weights: `var/lm/run-3/`. Database: `var/learn.sqlite`, run id `run-3`.
> `run-1` and `run-2` stay paused. Do not resume them. Do not set `learning`.

This note is the reading of the repair rhythm before the numbers exist. A later result note should cite it and then say which of the readings below actually occurred.

## What is running

A transformer of about 50 million parameters, context 512, trained from scratch. No pretrained weights. No second model.

The generator queue is unchanged. It still writes proofs, Lean still accepts or rejects them, and one training step still reads up to four proved sentences. The model writes only in the gap after that step. The prompt is `<|propose|>`. The text is a formula. If the text has no equation, it is marked "not a formula" and does not go to Lean. If it is new, Lean receives `theorem model_eq : … := rfl`. The `rfl` is stapled by the loop. The model did not write the proof.

One cycle, at most 200 of them:

1. One training step on generator sentences Lean has already accepted.
2. Twenty formulas from those weights (temperature 1, nucleus 0.9), then one argmax line stored apart. The twenty share one set of weights.
3. Lean judges the twenty. The argmax line is judged too and is not part of the twenty.
4. If any of them was accepted, the endings are skipped.
5. Otherwise the same model may write four endings. The prefix is the opening Lean read furthest into, counted in characters of the formula. An error in `theorem model_eq :` or in the stapled `:= rfl` is not inside the formula, so it does not open an ending. A prefix of length 0 does not open one either.
6. If one of those four gets strictly further, four more endings start from that new prefix. There is no third round.
7. Each accepted formula from the cycle gets one immediate training step. A rejection, a repeat, and a longer-but-still-wrong ending do not.

`error_at` on a row is that character count. `repair_ply` 0 is an opening. 1 is the first four endings. 2 is the second four. The argmax row is not a prefix and is not repaired.

The weights do not move between the twenty and the endings. A longer prefix is only a longer prompt. The gradient sees an ending only later, and only if Lean accepted the whole file.

## What a success can mean

Read these in order. A later one is not available until the earlier one has happened.

**The twenty are not one string.** Distinct, out of 20, is greater than 1 on later cycles, and the argmax line is not that whole set. The draw searched. This is the failure mode of `run-1`, where argmax collapsed onto a handful of names. It is not yet a result about repair.

**Lean's error sits inside a formula.** Some opening has `error_at` greater than 0. The file got past the wrapper and died on a character of the formula. Until this happens, the ending rounds never open, and the run has not tested repair. It has tested whether this network puts Lean's cursor inside its own text.

**An ending gets further than the opening it continued.** In that cycle the best `error_at` on ply 1 is greater than the ply-0 prefix it started from, or ply 2 is greater than ply 1. Keeping the letters Lean had already read, and redrawing only the tail, moved the error to the right. That is a result about search inside one cycle. The weights are the same weights. The run has not shown that the network learned the correction.

**An ending is accepted in a cycle whose twenty were not.** `repair_ply` is 1 or 2 and `disposition` is `proved`, and no ply-0 row in that cycle is `proved`. The kept prefix plus a new tail produced a file Lean accepted, and the twenty fresh draws did not. Check that the accepted text still begins with that prefix. If it does, the kept letters were part of the file that passed. The run still has no matched control that spends the same eight Lean calls on eight fresh formulas. "The ending passed" is not yet "repair beats eight more draws."

**Accepted formulas come back in later cycles.** After at least one accept, a later cycle's twenty contain text in the same shape, or the argmax line does. The weights have now seen that file, and they have also seen another page of generator text, so the generator step is mixed in. A single accept followed by more of the same shape is the strongest reading this run can support. It is still "the model emits definitional equalities Lean closes with `rfl`."

Depth, operator count, and node count on the accepted rows say whether those equalities are bare or nested. A long numeral is not depth.

## What it will not show, even if all of the above happens

**That a near miss became a lesson.** A longer `error_at` is not training data. The failed opening and the failed ending stay out of the weights. The only model text that is taught is a file Lean accepted. The correction the user can see on the page is a second draw from a longer prompt, not a gradient step on the mistake.

**That the right letter was supplied.** Nothing in the loop writes the character Lean wanted. The model samples a new tail. If the tail is still wrong, the cycle ends after the second four. There is no teacher token and no external model.

**That the model can prove.** The proof on these files is the stapled `rfl`, except when the model itself wrote `:=` and a proof. An accept means Lean's definitional equality closed the formula. It does not mean a `rewrite`, a lemma, or a proof the model composed. Early accepts, if they come, will be short true equations.

**That a longer prefix is closer to truth.** Lean can read further into a string that is still not a true equation: a longer name, a numeral, a fragment that parses and then breaks. `error_at` measures how many formula characters were consumed before the first error. It does not measure mathematical distance. Ply 2 can be "further" and still be garbage.

**That repair is why an accept happened.** This run does not also draw four and then four fresh formulas from an empty prefix. Extra Lean calls alone can hit. `run-2` is not a control: it was paused at step 49, it drew a hundred texts, and it did not repair. A comparison of accept counts between `run-2` and `run-3` does not isolate the endings.

**That the network keeps developing.** The model stops writing after 200 cycles. Generator training can continue in the same process, but the formula loop has a fixed end. `learning` stays off. The champion stays `champion-generator-v0`. The held-out pair is unchanged. An accepted formula does not flip that flag.

**Mathematics outside this fragment.** The corpus is the generator's `Nat` sentences. An accepted model formula is one more sentence in that fragment, wrapped as `theorem model_eq`. It is not a result about Lean in general, about proof search, or about a model that invents theorems the generator could not state.

## How to read a miss

**No `error_at` above 0.** Repair never started. The formulas never put Lean's error inside the body. Same family of result as the early text of `run-2`: the draw may be diverse, and it is not yet a formula Lean can partially read.

**`error_at` above 0, and ply 1 never exceeds it.** The prefix was real, and redrawing the tail did not move the error. On this network, keeping the letters did not help the search.

**Ply 1 or 2 goes further, and nothing is accepted.** The endings parse a longer prefix and still do not produce a file `rfl` can close. The column moved. The judge did not accept a theorem.

**Accepts are only short true equations, and the argmax line stays away from them.** The search-and-repair path can hit a trivial equality while the model's own most likely continuation is still something else. The weights have not put a formula on the mode. The accept is a sample, not the policy.

## What to count when the run stops

Openings are `repair_ply = 0` and `decoder = 'sample'`. Endings are `repair_ply` 1 and 2. The argmax row is `decoder = 'argmax'`.

```sql
SELECT repair_ply,
       COUNT(*) AS n,
       SUM(disposition = 'proved') AS accepted,
       MAX(error_at) AS furthest
FROM model_attempts
WHERE run_id = 'run-3' AND decoder = 'sample'
GROUP BY repair_ply;

SELECT cycle, repair_ply, error_at, disposition, equation
FROM model_attempts
WHERE run_id = 'run-3' AND repair_ply > 0
ORDER BY cycle, id;
```

A cycle repaired something only if a ply-0 row in that cycle has `error_at > 0` and a ply-1 row exists. The second round happened only if a ply-2 row exists. An ending that used the kept letters still starts with the parent prefix. That comparison is the one to write down next to the counts.
