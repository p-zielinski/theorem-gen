# run-4 observations

> Started: 2026-10-14
> Run: `run-4` (one-character hole, then study)
> Status: stopped by the user on 2026-10-15 14:01. Do not resume.

The hole part is finished: 200 cycles, 185 sample accepts, every one the original `(`, none a different character. This file watches what happens after that. A check every 90 minutes asks two questions: is the model still learning, and are the sentences getting harder. The verdict is written here when both have reached their maximum, or when learning freezes.

## What counts

- **Training up:** `lm_state.step` increased and `last_loss` is lower than the previous check.
- **Difficulty up:** curriculum level rose, or the latest proved `generate` rows have a higher mean depth or size than the previous check. The hard caps already seen are depth 3 and size 9 for `generate`, depth 6 for `richgen`.
- **Maximum:** curriculum level 7 with its gate passed, or the generators are on those caps and the general surface cannot grow. Level 2 asks for 1000 evaluated `generate_general` rows. That generator has 9 fixed statements, so level 7 is not reachable without a new generator. Do not lower the 1000 gate.
- **Stopped:** 2026-10-15 14:01 the user asked to turn the run off. Writer, dashboard, and the 90-minute loop are down. `runs.status` is `paused`. Do not resume `run-4`. Do not resume `run-1`, `run-2`, or `run-3`.
- **The approach works** only if, at that maximum, the model has a Lean-accepted sentence that is not the original character put back and not a copy of a generator line. Restoring `(` is not that sentence.

## Checks

| When | Step | Loss | Epoch | Level | Late depth | General rows | Reading |
|------|------|------|-------|-------|------------|--------------|---------|
| 2026-10-14 23:01 | 10768 | 0.467 | 1 | 2 | 2.77 (max 3) | 9 | Training up. Difficulty of new `generate` rows is higher than the first 200 (mean depth 1.8) and is already on the cap of 3. General statements are the 9 schemas. Not stuck. Verdict waits until loss also stops falling. |
| 2026-10-14 23:06 | 11000 | 0.528 | 1 | 2 | n/a | n/a | Replay turned off. A caught-up cursor waits for a new proved sentence. A flat step while the process is alive and the log has no traceback is that wait, not a stuck run. |
| 2026-10-15 00:22 | 0 | n/a | 0 | 2 | n/a | 9 | Model reset. Weights in `var/lm/run-4/` removed. Cursor and replay set to 0. 17991 proved sentences kept. Phase stays done, so it reads that pile once and does not guess again. Other runs' weights were not touched. |
| 2026-10-15 00:37 | 1092 | 0.832 | 0 | 2 | 2.87 (max 3) | 9 | Training up from the fresh start (first loss was 5.6). Replay position still 0. Cursor 193653, about 13600 proved sentences still ahead. Generator is waiting because that pile is above 128. Difficulty stays on the cap. Not stuck. |
| 2026-10-15 02:07 | 5657 | 0.743 | 1 | 2 | 2.90 (max 3) | 9 | Training up. First read finished: unread 0, replay position 0, cursor 209463. Generator is opening batches again and the model reads them as they are proved. Difficulty stays on the cap. Not stuck. |
| 2026-10-15 03:37 | 7720 | 0.613 | 1 | 2 | 2.96 (max 3, size 8.1) | 9 | Training up. Cursor 213230, unread 0, replay 0. About 391 new sentences in the last 10 minutes, read as they arrive. No accepted character other than the original. Difficulty still on the cap. Not stuck. |
| 2026-10-15 05:07 | 9624 | 0.645 | 1 | 2 | 2.96 (max 3, size 8.1) | 9 | Step moved, loss did not fall. Cursor 216607, unread 0, replay 0, about 367 new sentences in 10 minutes. Difficulty unchanged on the cap. See the verdict. |
| 2026-10-15 06:37 | 11399 | 0.583 | 1 | 2 | 2.95 (max 3, size 8.1) | 9 | Step moved and loss eased from 0.645. Cursor 219743, unread 0, replay 0, about 359 new sentences in 10 minutes. Difficulty unchanged. No new accepted character. The verdict stands. |
| 2026-10-15 08:07 | 13036 | 0.604 | 1 | 2 | 3.0 (max 3, size 8.2) | 9 | Step moved, loss did not fall. Cursor 222556, unread 0, replay 0, about 287 new sentences in 10 minutes. Mean depth is now on the cap of 3. No new accepted character. The verdict stands. |
| 2026-10-15 08:25 | n/a | n/a | 1 | 2 | n/a | 9 | Level 2 was stuck: `generate_general` had 9 fixed statements and the gate wants 1000. Later copies of the lemma rules now add a numeral and stay provable. The 1000 gate is unchanged. The writer was resumed so new batches use that generator. |
| 2026-10-15 09:37 | 16451 | 0.457 | 1 | 7 | 3.0 (max 3, size 8.2) | 9296 | Curriculum reached level 7. General sentences proved: 9296. Loss fell from 0.604. Cursor 232976, unread 3, replay 0. Concrete `generate` depth is still capped at 3. No new accepted model character. |
| 2026-10-15 11:07 | 19958 | 0.345 | 1 | 7 | 3.0 (max 3, size 8.4) | 20196 | Training up: loss fell from 0.457. Level stays 7. Cursor 244359, unread 2, replay 0. Concrete depth still capped at 3. No new accepted model character. The verdict stands. |
| 2026-10-15 12:37 | 23766 | 0.437 | 1 | 7 | 2.99 (max 3, size 8.3) | 32165 | Step moved, loss did not fall (0.345 to 0.437). Level stays 7. Cursor 256834, unread 0, replay 0, about 1549 new sentences in 10 minutes. Concrete depth still capped at 3. No new accepted model character. The verdict stands. |
| 2026-10-15 14:01 | 27288 | 0.284 | 1 | 7 | n/a | n/a | Stopped at the user's request. Phase `done`, cursor 268380. No writer, no dashboard on port 8765, no 90-minute loop. Do not resume. |

## Verdict

Curriculum level 7, the top of this program, was reached at 09:37 after the general sentences started to vary. 9296 of them are proved. The 1000 gate was not lowered. Concrete `generate` rows are still depth 3 and size at most 9. Loss on the fresh read is about 0.46. The model is not rereading.

That does not make the writing approach work. The only Lean-accepted sentences the model wrote are the 185 hole guesses that put `(` back. None replaced it with a different character. Since the fresh start the model only reads, so the new general sentences train it. They do not add a sentence Lean accepts that the generator did not already write.
