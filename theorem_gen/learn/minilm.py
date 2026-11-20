"""50M transformer trained from scratch on proved Lean lines.

Two role tags, each one special token:

- `<|propose|>` continues as the theorem statement
- `<|prove|>` continues as the statement plus its proof

The model does not speak until one of those tags is given. Sampled equations
are kept only when their body is not already in the run. Lean still decides
`proved`. Every try spends one place in the turn, then study resumes. The
share of accepted equations is the coefficient for the next turn.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from theorem_gen.learn.probe import (
    CYCLE_LIMIT,
    DRAW_COUNT,
    FORMULA_DRAW,
    HOLE_DRAW,
    TEMPERATURE,
    TOP_P,
    first_break,
    formula_progress,
    lean_error_at,
    next_draw,
    open_repairs,
    splice_char,
)
from theorem_gen.learn.prefix import is_in_flight, unread_in_prefix
from theorem_gen.learn.replay import next_replay
from theorem_gen.learn.balance import (
    after_sample,
    after_train,
    choose_action,
    fit_study,
    freedom_plan,
    loss_is_ready,
    observe,
    open_burst,
    remember_loss,
)
from theorem_gen.learn.effort import remember_shapes, statement_depth, statement_measures
from theorem_gen.learn.heldout import HELD_OUT_HASHES

ADAM_EVERY = 500

PAD = 0
PROPOSE = 1
PROVE = 2
END = 3
BYTE = 4
VOCAB = 260

PROPOSE_TAG = "<|propose|>"
PROVE_TAG = "<|prove|>"
END_TAG = "<|end|>"
_SPECIALS = ((PROPOSE_TAG, PROPOSE), (PROVE_TAG, PROVE), (END_TAG, END))
_NAMES = {PROPOSE: PROPOSE_TAG, PROVE: PROVE_TAG, END: END_TAG, PAD: ""}
BATCH_CANDIDATES = 4


def hole_lesson(broken: str, index: int, char: str) -> str:
    """One accepted replacement. The known original is not a lesson by itself."""
    return f"{PROPOSE_TAG}\n{broken}\n{index}\n{char}\n{END_TAG}"


def theorem_line(source: str) -> str:
    block = theorem_block(source)
    if not block:
        return ""
    return block.splitlines()[0]


def theorem_block(source: str) -> str:
    """Theorem line plus the proof lines under it. A blank line ends the block."""
    lines = source.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().startswith("theorem ")), None)
    if start is None:
        return ""
    block = []
    for line in lines[start:]:
        if block and not line.strip():
            break
        block.append(line.strip())
    return "\n".join(block)


def equation_body(line: str) -> str:
    text = " ".join(line.split())
    if text.startswith("theorem "):
        text = text[len("theorem ") :]
        if ":" in text:
            text = text.split(":", 1)[1]
    if ":=" in text:
        text = text.split(":=", 1)[0]
    return " ".join(text.split())


def equation_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def statement_line(line: str) -> str:
    if ":=" not in line:
        return line.strip()
    return line.split(":=", 1)[0].rstrip()


def role_documents(source: str) -> list:
    block = theorem_block(source)
    if not block or ":=" not in block:
        return []
    first = block.splitlines()[0]
    return [
        f"{PROPOSE_TAG}\n{statement_line(first)}\n{END_TAG}",
        f"{PROVE_TAG}\n{block}\n{END_TAG}",
    ]


BLOCKED_BY_CONTEXT = "blocked by context limit"


def token_length(text: str) -> int:
    """Tokens in `text`. A role mark and `<|end|>` are one token each."""
    count = 0
    index = 0
    while index < len(text):
        matched = False
        for literal, _token in _SPECIALS:
            if text.startswith(literal, index):
                count += 1
                index += len(literal)
                matched = True
                break
        if matched:
            continue
        count += 1
        index += 1
    return count


def overflowing_length(documents, context: int) -> int:
    """Longest document when it does not fit. Zero when every document fits."""
    longest = 0
    for text in documents:
        longest = max(longest, token_length(text))
    if longest > context:
        return longest
    return 0


def encode(text: str, context: int) -> tuple:
    ids = []
    index = 0
    while index < len(text) and len(ids) < context:
        matched = False
        for literal, token in _SPECIALS:
            if text.startswith(literal, index):
                ids.append(token)
                index += len(literal)
                matched = True
                break
        if matched:
            continue
        code = ord(text[index])
        ids.append(BYTE + code if code < 256 else BYTE + 63)
        index += 1
    length = len(ids)
    if len(ids) < context:
        ids.extend([PAD] * (context - len(ids)))
    return ids, length


def decode(ids: list) -> str:
    chars = []
    for token in ids:
        if token in _NAMES:
            chars.append(_NAMES[token])
        elif token >= BYTE:
            chars.append(chr(token - BYTE))
    return "".join(chars)


def counts(store, run_id: str) -> dict:
    row = store._one(
        """
        SELECT step, epoch, last_loss, hold, weak_streak
        FROM lm_state WHERE run_id=?
        """,
        (run_id,),
    )
    if row is None:
        return {
            "lm_step": 0,
            "lm_epoch": 0,
            "lm_loss": None,
            "lm_hold": False,
            "lm_weak": 0,
        }
    return {
        "lm_step": int(row["step"]),
        "lm_epoch": int(row["epoch"]),
        "lm_loss": row["last_loss"],
        "lm_hold": bool(row["hold"]),
        "lm_weak": int(row["weak_streak"]),
    }


def _source_for(store, run_id: str, candidate) -> str:
    keys = (
        f"{run_id}:lean_validate:{candidate['stable_id']}:proof",
        f"{run_id}:lean_validate:{candidate['stable_id']}:check",
        f"{run_id}:cert:{candidate['stable_id']}",
    )
    for key in keys:
        row = store._one(
            "SELECT payload_json FROM queue_jobs WHERE idempotency_key=?",
            (key,),
        )
        if row is None:
            continue
        source = json.loads(row["payload_json"]).get("source")
        if source:
            return str(source)
    return ""


class MiniLMService:
    """One writer-side trainer. A turn writes its own equations, then study resumes."""

    def __init__(self, directory: Path, config=None, probe: bool = False, repair: bool = False, hole: bool = False) -> None:
        self.directory = Path(directory)
        if config is None:
            from theorem_gen.learn.minilm_model import PRODUCTION

            config = PRODUCTION
        self.config = config
        self.trainer = None
        self.seen = set()
        self.seen_ready = False
        self.step = 0
        self.epoch = 0
        self.cursor_id = 0
        self.pass_cursor = 0
        self.sequences = 0
        self.hold = False
        self.weak_streak = 0
        self.last_loss = None
        self.last_error = None
        self.burst_left = 0
        self.study_left = 0
        self.recent_losses = []
        self.replay_id = 0
        self._aligned = False
        self._shapes_ready = False
        self._unbound_checked = False
        self.hole = bool(hole)
        self.repair = bool(repair) and not self.hole
        self.probe = bool(probe) or self.repair or self.hole
        self.phase = "train"
        self.cycle = 0
        self.cycles = 0
        self.draw_left = 0
        self.greedy_left = 0
        self.repair_ply = 0
        self.repair_left = 0
        self.repair_at = 0
        self.repair_prefix = ""
        self.hole_broken = ""
        self.hole_index = 0
        self.hole_from = ""
        self._pending_char = ""
        self.sample_seed = 1
        self._decoder = "argmax"

    def tick(self, engine) -> None:
        self._load_state(engine.store, engine.run_id)
        if not self._shapes_ready:
            remember_shapes(engine.store.conn)
            self._shapes_ready = True
        self._requeue_unbound(engine)
        self._rewind_to_weights()
        if self.hold and not self.probe:
            self.hold = False
            self.pass_cursor = 0
            self._save_state(engine.store, engine.run_id)
        if self.probe or self.repair or self.hole:
            self.probe = True
            self.sample_seed = int(getattr(engine, "seed", 1)) + int(self.step)
            self._probe_tick(engine)
            return
        ready = loss_is_ready(self.recent_losses)
        plan = freedom_plan(self._judged_dispositions(engine.store, engine.run_id))
        fitted = fit_study(self.study_left, plan["study"])
        if fitted != self.study_left:
            self.study_left = fitted
            self._save_state(engine.store, engine.run_id)
        self.burst_left, self.study_left = open_burst(
            self.burst_left, self.study_left, ready, plan["burst"]
        )
        action = choose_action(
            untrained=self._untrained(engine.store, engine.run_id),
            epoch=self.epoch,
            hold=self.hold,
            lean_backlog=engine.queue.occupancy(
                engine.run_id, "lean_validate", origin="model"
            ),
            high_water=engine.queue.high_water,
            loss_ready=ready,
            burst_left=self.burst_left,
        )
        if action == "train":
            outcome = self._train_page(engine, after=self.cursor_id, advance_cursor=True)
            updated = after_train(
                self.study_left,
                outcome == "trained",
                waiting=outcome == "waiting",
            )
            if updated != self.study_left:
                self.study_left = updated
                self._save_state(engine.store, engine.run_id)
            if outcome == "idle":
                self._replay(engine)
        elif action == "rehearse":
            self._rehearse(engine)
        elif action == "sample":
            try:
                disposition = self._sample(engine)
            except Backpressure:
                return
            self.burst_left, self.study_left = after_sample(
                self.burst_left, self.study_left, disposition, plan["study"]
            )
            self._save_state(engine.store, engine.run_id)

    def note_failure(self, store, job) -> None:
        """A Lean job that died without a verdict is not still waiting."""
        try:
            payload = json.loads(job["payload_json"])
        except (TypeError, json.JSONDecodeError):
            return
        candidate_id = payload.get("candidate_id")
        if not candidate_id:
            return
        row = store._one(
            """
            SELECT id FROM model_attempts
            WHERE run_id=? AND candidate_id=? AND disposition='queued'
            """,
            (job["run_id"], candidate_id),
        )
        if row is None:
            return
        store.conn.execute(
            """
            UPDATE model_attempts SET disposition='ill_formed'
            WHERE id=? AND disposition='queued'
            """,
            (row["id"],),
        )
        self._apply_observation(store, job["run_id"], "ill_formed")

    def _bind_source(self, engine, candidate_id: int, validation_type: str, source: str) -> None:
        engine.store.append_event(
            engine.run_id,
            "bound_source",
            {
                "candidate_id": candidate_id,
                "validation_type": validation_type,
                "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            },
        )

    def _requeue_unbound(self, engine) -> None:
        """Send a model check back to Lean when it failed before a verdict.

        The first model sentence was queued without a bound source, so Lean
        refused it and the attempt stayed 'queued'. One pass binds that source
        and puts the job back. Later sentences are bound when they are written.
        """
        if self._unbound_checked:
            return
        rows = engine.store._all(
            """
            SELECT candidate_id FROM model_attempts
            WHERE run_id=? AND disposition='queued' AND candidate_id IS NOT NULL
            """,
            (engine.run_id,),
        )
        for row in rows:
            candidate = engine.store.get_candidate(row["candidate_id"])
            if candidate is None:
                continue
            key = f"{engine.run_id}:lean_validate:{candidate['stable_id']}:proof"
            job = engine.store._one(
                "SELECT id, state, payload_json FROM queue_jobs WHERE idempotency_key=?",
                (key,),
            )
            if job is None or job["state"] != "failed":
                continue
            try:
                payload = json.loads(job["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            source = payload.get("source") or ""
            if not source:
                continue
            self._bind_source(
                engine,
                candidate["id"],
                payload.get("validation_type") or "proof",
                source,
            )
            engine.store.conn.execute(
                """
                UPDATE queue_jobs
                SET state='queued', lease_owner=NULL, lease_expiry=NULL, updated_at=?
                WHERE id=? AND state='failed'
                """,
                (engine.store.now(), job["id"]),
            )
        self._unbound_checked = True

    def note_verdict(self, store, candidate) -> None:
        try:
            provenance = json.loads(candidate["provenance"])
        except (TypeError, json.JSONDecodeError):
            return
        if provenance.get("origin") != "model":
            return
        status = candidate["current_status"]
        if status not in {"proved", "refuted", "unresolved", "ill_formed"}:
            status = "unresolved"
        store.conn.execute(
            """
            UPDATE model_attempts
            SET disposition=?
            WHERE run_id=? AND candidate_id=? AND disposition='queued'
            """,
            (status, candidate["run_id"], candidate["id"]),
        )
        self._mark_progress(store, candidate)
        self._apply_observation(store, candidate["run_id"], status)

    def stop(self) -> None:
        self._write_weights(moments=True)

    def _probe_tick(self, engine) -> None:
        """One action of the fixed rhythm. The hundred shares one set of weights."""
        if self.phase == "done" or self.cycles >= CYCLE_LIMIT:
            if self.phase != "done":
                self.phase = "done"
                self._save_state(engine.store, engine.run_id)
                print(f"lm probe done cycles={self.cycles} step={self.step}", flush=True)
            self._study_finished(engine)
            return
        if self.phase == "train":
            outcome = self._train_page(engine, after=self.cursor_id, advance_cursor=True)
            if outcome != "trained":
                return
            if self.hole:
                opened = self._open_hole(engine)
                if opened is None:
                    self.phase = "train"
                    self._save_state(engine.store, engine.run_id)
                    return
                if not opened:
                    self._advance_without_guess(engine)
                    return
                self.phase = "draw"
                self.draw_left = HOLE_DRAW
                self.greedy_left = 1
                self._save_state(engine.store, engine.run_id)
                loss = "—" if self.last_loss is None else f"{self.last_loss:.3f}"
                print(
                    f"lm hole cycle={self.cycle + 1} step={self.step} loss={loss} index={self.hole_index}",
                    flush=True,
                )
                return
            self.phase = "draw"
            self.draw_left = FORMULA_DRAW if self.repair else DRAW_COUNT
            self.greedy_left = 1
            self.repair_ply = 0
            self.repair_left = 0
            self.repair_at = 0
            self.repair_prefix = ""
            self._save_state(engine.store, engine.run_id)
            loss = "—" if self.last_loss is None else f"{self.last_loss:.3f}"
            label = "repair" if self.repair else "probe"
            print(
                f"lm {label} cycle={self.cycle + 1} step={self.step} loss={loss}",
                flush=True,
            )
            return
        if self.phase == "draw":
            decoder, self.draw_left, self.greedy_left = next_draw(self.draw_left, self.greedy_left)
            if not decoder:
                self.phase = "wait"
                self._save_state(engine.store, engine.run_id)
                return
            if self.hole:
                self._guess_hole(engine, decoder)
            else:
                self._sample(engine, decoder=decoder)
            if self.draw_left == 0 and self.greedy_left == 0:
                self.phase = "wait"
            self._save_state(engine.store, engine.run_id)
            return
        if self.phase == "wait":
            if self._cycle_waiting(engine):
                return
            if self.repair and self._open_repair(engine):
                self.phase = "repair"
                self._save_state(engine.store, engine.run_id)
                return
            self.phase = "teach"
            self._save_state(engine.store, engine.run_id)
            return
        if self.phase == "repair":
            if self.repair_left <= 0:
                self.phase = "wait"
                self._save_state(engine.store, engine.run_id)
                return
            prompt = f"{PROPOSE_TAG}\n{self.repair_prefix}"
            encoded, length = encode(prompt, self.config.context)
            self._sample(
                engine,
                decoder="sample",
                prompt_ids=encoded[:length],
                prefix=self.repair_prefix,
            )
            self.repair_left -= 1
            if self.repair_left == 0:
                self.phase = "wait"
            self._save_state(engine.store, engine.run_id)
            return
        if self.phase == "teach":
            if self._teach_one(engine):
                return
            self.cycles += 1
            self.cycle += 1
            if self.cycles >= CYCLE_LIMIT:
                self.phase = "done"
                print(f"lm probe done cycles={self.cycles} step={self.step}", flush=True)
            else:
                self.phase = "train"
            self._save_state(engine.store, engine.run_id)

    def _study_finished(self, engine) -> None:
        """Writing has stopped. Read a new proved sentence, or wait for one."""
        outcome = self._train_page(engine, after=self.cursor_id, advance_cursor=True)
        if outcome != "trained":
            return
        loss = "—" if self.last_loss is None else f"{self.last_loss:.3f}"
        print(
            f"lm study step={self.step} loss={loss} cursor={self.cursor_id}",
            flush=True,
        )

    def _cycle_waiting(self, engine) -> bool:
        row = engine.store._one(
            """
            SELECT id FROM model_attempts
            WHERE run_id=? AND cycle=? AND disposition='queued'
            LIMIT 1
            """,
            (engine.run_id, self.cycle),
        )
        return row is not None

    def _cycle_proved(self, engine) -> bool:
        row = engine.store._one(
            """
            SELECT id FROM model_attempts
            WHERE run_id=? AND cycle=? AND disposition='proved'
            LIMIT 1
            """,
            (engine.run_id, self.cycle),
        )
        return row is not None

    def _best_progress(self, engine, ply: int):
        return engine.store._one(
            """
            SELECT equation, error_at FROM model_attempts
            WHERE run_id=? AND cycle=? AND repair_ply=? AND decoder='sample'
              AND error_at IS NOT NULL AND error_at > 0
            ORDER BY error_at DESC, id DESC
            LIMIT 1
            """,
            (engine.run_id, self.cycle, ply),
        )

    def _progress_values(self, engine, ply: int) -> list:
        rows = engine.store._all(
            """
            SELECT error_at FROM model_attempts
            WHERE run_id=? AND cycle=? AND repair_ply=? AND decoder='sample'
              AND error_at IS NOT NULL
            """,
            (engine.run_id, self.cycle, ply),
        )
        return [int(row["error_at"]) for row in rows]

    def _open_repair(self, engine) -> bool:
        """Arm four endings from the furthest formula. False when nothing is closer."""
        if self._cycle_proved(engine):
            return False
        if self.repair_ply == 0:
            best = self._best_progress(engine, 0)
            if best is None or open_repairs(0, int(best["error_at"]), []) == 0:
                return False
            at = int(best["error_at"])
            self.repair_prefix = (best["equation"] or "")[:at]
            self.repair_at = at
            self.repair_ply = 1
            self.repair_left = open_repairs(0, at, [])
            return True
        children = self._progress_values(engine, self.repair_ply)
        width = open_repairs(self.repair_ply, self.repair_at, children)
        if width == 0:
            return False
        best = self._best_progress(engine, self.repair_ply)
        if best is None:
            return False
        at = int(best["error_at"])
        self.repair_prefix = (best["equation"] or "")[:at]
        self.repair_at = at
        self.repair_ply += 1
        self.repair_left = width
        return True

    def _mark_progress(self, store, candidate) -> None:
        names = {row["name"] for row in store.conn.execute("PRAGMA table_info(model_attempts)")}
        if "error_at" not in names:
            return
        attempt = store._one(
            """
            SELECT id, equation FROM model_attempts
            WHERE run_id=? AND candidate_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (candidate["run_id"], candidate["id"]),
        )
        if attempt is None:
            return
        validation = store._one(
            """
            SELECT message FROM validations
            WHERE candidate_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (candidate["id"],),
        )
        progress = None
        if validation is not None:
            source = _source_for(store, candidate["run_id"], candidate)
            progress = formula_progress(
                source,
                attempt["equation"] or "",
                lean_error_at(validation["message"], source),
            )
        store.conn.execute(
            "UPDATE model_attempts SET error_at=? WHERE id=?",
            (progress, attempt["id"]),
        )

    def _teach_one(self, engine) -> bool:
        """One extra step on an accepted equation from this cycle. True if one was taken."""
        row = engine.store._one(
            """
            SELECT id, candidate_id FROM model_attempts
            WHERE run_id=? AND cycle=? AND disposition='proved' AND taught=0
            ORDER BY id
            LIMIT 1
            """,
            (engine.run_id, self.cycle),
        )
        if row is None:
            return False
        if self.hole:
            detail = engine.store._one(
                """
                SELECT hole_broken, hole_index, hole_char FROM model_attempts
                WHERE id=?
                """,
                (row["id"],),
            )
            char = "" if detail is None else (detail["hole_char"] or "")
            if char:
                doc = hole_lesson(detail["hole_broken"] or "", int(detail["hole_index"] or 0), char)
                if not overflowing_length([doc], self.config.context):
                    loss = self._fit([doc])
                    self.last_loss = loss
                    self.recent_losses = remember_loss(self.recent_losses, loss)
                    self.sequences += 1
                    self.step += 1
            engine.store.conn.execute(
                "UPDATE model_attempts SET taught=1 WHERE id=?",
                (row["id"],),
            )
            self._save_state(engine.store, engine.run_id)
            return True
        candidate = None
        if row["candidate_id"] is not None:
            candidate = engine.store.get_candidate(row["candidate_id"])
        docs = role_documents(_source_for(engine.store, engine.run_id, candidate)) if candidate else []
        if docs and not overflowing_length(docs, self.config.context):
            loss = self._fit(docs)
            self.last_loss = loss
            self.recent_losses = remember_loss(self.recent_losses, loss)
            self.sequences += len(docs)
            self.step += 1
        engine.store.conn.execute(
            "UPDATE model_attempts SET taught=1 WHERE id=?",
            (row["id"],),
        )
        self._save_state(engine.store, engine.run_id)
        return True

    def _train_page(self, engine, *, after: int, advance_cursor: bool) -> str:
        """Return trained, waiting, advanced, or idle.

        `waiting` means the next sentence has no Lean verdict yet. The cursor stays.
        """
        released_docs, released_ids = self._ready_blocked(engine)
        rows, new_cursor, waiting = self._closed_page(engine.store, engine.run_id, after)
        if not rows and not released_docs:
            if waiting:
                return "waiting"
            if new_cursor == after:
                if self.epoch < 1 and self._blocked_count(engine.store, engine.run_id) == 0:
                    self.epoch = 1
                    self._save_state(engine.store, engine.run_id)
                return "idle"
        docs = []
        for candidate in rows:
            if candidate["structural_hash"] in HELD_OUT_HASHES:
                continue
            role_docs = role_documents(_source_for(engine.store, engine.run_id, candidate))
            overflow = overflowing_length(role_docs, self.config.context)
            if overflow:
                self._block(engine.store, engine.run_id, int(candidate["id"]), overflow)
                continue
            docs.extend(role_docs)
        docs.extend(released_docs)
        if docs:
            loss = self._fit(docs)
            self.last_loss = loss
            self.recent_losses = remember_loss(self.recent_losses, loss)
            self.sequences += len(docs)
            self.step += 1
            if self.hold and advance_cursor:
                self.hold = False
                self.weak_streak = 0
            self._clear_blocks(engine.store, engine.run_id, released_ids)
        if new_cursor != after:
            if advance_cursor:
                self.cursor_id = new_cursor
            else:
                self.pass_cursor = new_cursor
        self._save_state(engine.store, engine.run_id)
        if self.step % 20 == 0 and docs:
            self._write_weights(moments=self.step % ADAM_EVERY == 0)
            print(
                f"lm step={self.step} epoch={self.epoch} loss={self.last_loss} cursor={self.cursor_id}",
                flush=True,
            )
        if docs:
            return "trained"
        if waiting:
            return "waiting"
        if new_cursor != after:
            return "advanced"
        return "idle"

    def _rehearse(self, engine) -> None:
        outcome = self._train_page(engine, after=self.pass_cursor, advance_cursor=False)
        if outcome != "idle":
            return
        self.hold = False
        self.weak_streak = 0
        self.pass_cursor = 0
        self.epoch += 1
        self._save_state(engine.store, engine.run_id)

    def _replay(self, engine) -> str:
        """One page of sentences already read. New work stays in front of this."""
        rows, nxt = next_replay(
            engine.store.conn,
            engine.run_id,
            self.replay_id,
            self.cursor_id,
            BATCH_CANDIDATES,
        )
        docs = []
        for candidate in rows:
            role_docs = role_documents(_source_for(engine.store, engine.run_id, candidate))
            if not role_docs or overflowing_length(role_docs, self.config.context):
                continue
            docs.extend(role_docs)
        if docs:
            self._fit(docs)
            self.step += 1
            self.sequences += len(docs)
        if nxt == self.replay_id and not docs:
            return "idle"
        self.replay_id = nxt
        self._save_state(engine.store, engine.run_id)
        if docs and self.step % 20 == 0:
            self._write_weights(moments=self.step % ADAM_EVERY == 0)
            print(
                f"lm replay step={self.step} replay_id={self.replay_id} cursor={self.cursor_id}",
                flush=True,
            )
        return "trained" if docs else "idle"

    def _advance_without_guess(self, engine) -> None:
        """A proved line was found and every tried swap still passed. The cycle is spent."""
        self.cycles += 1
        self.cycle += 1
        if self.cycles >= CYCLE_LIMIT:
            self.phase = "done"
            print(f"lm probe done cycles={self.cycles} step={self.step}", flush=True)
        else:
            self.phase = "train"
            print(f"lm hole skip cycle={self.cycle} step={self.step}", flush=True)
        self._save_state(engine.store, engine.run_id)

    def _open_hole(self, engine):
        """Arm one broken character. None when no rfl line exists. False when none of the swaps fail."""
        body = self._next_rfl_body(engine)
        if not body:
            return None
        found = first_break(body, lambda text: self._body_closed(engine, text))
        if not found:
            return False
        index, broken, original = found
        self.hole_index = index
        self.hole_broken = broken
        self.hole_from = original
        self.repair_at = index
        self.repair_prefix = broken
        return True

    def _next_rfl_body(self, engine) -> str:
        rows = engine.store._all(
            """
            SELECT id, stable_id FROM candidates
            WHERE run_id=? AND current_status='proved' AND held_out=0 AND proof_method='rfl'
              AND instr(COALESCE(provenance, ''), '"origin": "model"') = 0
            ORDER BY id
            """,
            (engine.run_id,),
        )
        if not rows:
            return ""
        start = self.cycle % len(rows)
        ordered = rows[start:] + rows[:start]
        for row in ordered:
            candidate = engine.store.get_candidate(int(row["id"]))
            if candidate is None:
                continue
            body = equation_body(theorem_line(_source_for(engine.store, engine.run_id, candidate)))
            if body and "\n" not in body:
                return body
        return ""

    def _body_closed(self, engine, body: str) -> bool:
        from theorem_gen.learn.validate import validate_source

        source = f"theorem model_eq : {body} := rfl\n"
        report = validate_source(
            source,
            validation_type="proof",
            project_dir=engine.project_dir,
            timeout_s=engine.lean_timeout_s,
            runner=getattr(engine, "runner", None),
        )
        return bool(report.get("accepted"))

    def _model_body_known(self, store, run_id: str, digest: str) -> bool:
        row = store._one(
            """
            SELECT id FROM model_attempts
            WHERE run_id=? AND equation_hash=? AND disposition!='duplicate'
            LIMIT 1
            """,
            (run_id, digest),
        )
        return row is not None

    def _one_character(self, token_ids: list, prompt_len: int) -> str:
        if len(token_ids) <= prompt_len:
            return ""
        token = int(token_ids[prompt_len])
        if token in {END, PAD, PROPOSE, PROVE}:
            return ""
        char = decode([token])
        if len(char) != 1 or char in "\n\r":
            return ""
        return char

    def _guess_hole(self, engine, decoder: str) -> str:
        """Draw one replacement for the planted character."""
        self._ensure_trainer()
        self._decoder = decoder
        self._pending_char = ""
        prompt = f"{PROPOSE_TAG}\n{self.hole_broken}\n{self.hole_index}\n"
        encoded, length = encode(prompt, self.config.context)
        prompt_ids = encoded[:length]
        temperature = TEMPERATURE if decoder == "sample" else 0.0
        top_p = TOP_P if decoder == "sample" else 1.0
        token_ids = self.trainer.complete(
            list(prompt_ids),
            max_new=1,
            temperature=temperature,
            top_p=top_p,
        )
        char = self._one_character(token_ids, len(prompt_ids))
        if not char:
            self._record(engine, "", equation_hash(""), "ill_formed", None)
            return "ill_formed"
        repaired = splice_char(self.hole_broken, self.hole_index, char)
        if not repaired:
            self._record(engine, "", equation_hash(""), "ill_formed", None)
            return "ill_formed"
        digest = equation_hash(repaired)
        self._pending_char = char
        if self._model_body_known(engine.store, engine.run_id, digest):
            self._record(engine, repaired, digest, "duplicate", None)
            self._pending_char = ""
            return "duplicate"
        source = f"theorem model_eq : {repaired} := rfl\n"
        outcome = self._enqueue(engine, repaired, digest, source)
        self._pending_char = ""
        return outcome

    def _sample(self, engine, decoder: str = "argmax", prompt_ids=None, prefix: str = "") -> str:
        self._ensure_seen(engine.store, engine.run_id)
        self._ensure_trainer()
        self._decoder = decoder
        temperature = TEMPERATURE if decoder == "sample" else 0.0
        top_p = TOP_P if decoder == "sample" else 1.0
        if prompt_ids is None:
            prompt_ids = [PROPOSE]
        token_ids = self.trainer.complete(list(prompt_ids), temperature=temperature, top_p=top_p)
        if prefix:
            extra = decode(token_ids[len(prompt_ids) :])
            for tag in (END_TAG, PROPOSE_TAG, PROVE_TAG):
                extra = extra.replace(tag, "")
            line = prefix + extra.split("\n", 1)[0]
        else:
            text = decode(token_ids)
            line = theorem_line(text)
            if not line:
                line = text.replace(PROPOSE_TAG, "").replace(END_TAG, "").strip()
        body = equation_body(line)
        if not body:
            self._record(engine, "", equation_hash(""), "ill_formed", None)
            return "ill_formed"
        digest = equation_hash(body)
        if digest in self.seen or self._hash_known(engine.store, engine.run_id, digest):
            self._record(engine, body, digest, "duplicate", None)
            return "duplicate"
        full = line if ":=" in line else f"{statement_line(line)} := rfl"
        if not full.startswith("theorem "):
            full = f"theorem model_eq : {body} := rfl"
        source = full if full.endswith("\n") else full + "\n"
        return self._enqueue(engine, body, digest, source)

    def _enqueue(self, engine, body: str, digest: str, full: str) -> None:
        stable_id = f"{engine.run_id}:model:{digest[:16]}"
        provenance = json.dumps(
            {"origin": "model", "generator": "minilm"},
            sort_keys=True,
        )
        candidate = engine.store.upsert_candidate(
            stable_id=stable_id,
            run_id=engine.run_id,
            canonical_ast_json=json.dumps({"equation": body}, sort_keys=True),
            structural_hash=digest,
            kind="theorem",
            provenance=provenance,
            current_status="unresolved",
            curriculum_level=engine.level,
            family="model",
            ast_size=len(body),
            depth=1,
            proof_method="model",
            dependency_depth=0,
            held_out=False,
        )
        source = full if full.endswith("\n") else full + "\n"
        self._bind_source(engine, candidate["id"], "proof", source)
        engine.queue.enqueue(
            engine.run_id,
            "lean_validate",
            payload={
                "candidate_id": candidate["id"],
                "source": source,
                "validation_type": "proof",
                "counterexample_id": None,
            },
            idempotency_key=f"{engine.run_id}:lean_validate:{stable_id}:proof",
            origin="model",
        )
        self.seen.add(digest)
        self._record(engine, body, digest, "queued", candidate["id"])
        return "queued"

    def _record(self, engine, body: str, digest: str, disposition: str, candidate_id) -> None:
        now = engine.store.now()
        shape = statement_measures(body)
        engine.store.conn.execute(
            """
            INSERT INTO model_attempts (
              run_id, equation, equation_hash, origin, disposition, candidate_id, created_at,
              lm_step, loss, expr_depth, expr_operators, expr_size, decoder, cycle, repair_ply,
              hole_index, hole_char, hole_from, hole_broken
            ) VALUES (?, ?, ?, 'model', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                engine.run_id,
                body,
                digest,
                disposition,
                candidate_id,
                now,
                self.step,
                self.last_loss,
                None if shape is None else shape["depth"],
                None if shape is None else shape["operators"],
                None if shape is None else shape["size"],
                self._decoder if self.probe else None,
                self.cycle if self.probe else None,
                self.repair_ply if self.repair else 0,
                self.hole_index if self.hole else None,
                self._pending_char if self.hole else "",
                self.hole_from if self.hole else "",
                self.hole_broken if self.hole else "",
            ),
        )
        if disposition != "queued":
            self._apply_observation(engine.store, engine.run_id, disposition)

    def _apply_observation(self, store, run_id: str, disposition: str) -> None:
        plan = freedom_plan(self._judged_dispositions(store, run_id))
        streak, _stopped = observe(disposition, self.weak_streak, plan["weak"])
        self.weak_streak = streak
        if disposition == "proved":
            self.hold = False
        self._save_state(store, run_id)

    def _fit(self, docs: list) -> float:
        self._ensure_trainer()
        rows = []
        lengths = []
        for text in docs:
            encoded, length = encode(text, self.config.context)
            rows.append(encoded)
            lengths.append(length)
        return self.trainer.step(rows, lengths)

    def _ensure_trainer(self) -> None:
        if self.trainer is not None:
            return
        from theorem_gen.learn.minilm_model import Trainer

        self.trainer = Trainer(self.config)
        weights = self.directory / "model.safetensors"
        if weights.is_file() and self.step > 0:
            self.trainer.load(weights)
        import mlx.core as mx

        mx.random.seed(int(self.sample_seed) & 0xFFFFFFFF)

    def _write_weights(self, moments: bool = False) -> None:
        if self.trainer is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self.trainer.save(self.directory / "model.safetensors", moments=moments)
        (self.directory / "checkpoint.json").write_text(
            json.dumps(
                {
                    "step": self.step,
                    "epoch": self.epoch,
                    "cursor_id": self.cursor_id,
                    "pass_cursor": self.pass_cursor,
                    "sequences": self.sequences,
                    "hold": self.hold,
                    "weak_streak": self.weak_streak,
                    "burst_left": self.burst_left,
                    "study_left": self.study_left,
                    "recent_losses": self.recent_losses,
                    "replay_id": self.replay_id,
                }
            ),
            encoding="utf-8",
        )

    def _rewind_to_weights(self) -> None:
        if self._aligned:
            return
        self._aligned = True
        path = self.directory / "checkpoint.json"
        if not path.is_file():
            return
        meta = json.loads(path.read_text(encoding="utf-8"))
        if int(meta["cursor_id"]) < self.cursor_id:
            self.cursor_id = int(meta["cursor_id"])
            self.pass_cursor = int(meta["pass_cursor"])
            self.step = int(meta["step"])
            self.epoch = int(meta["epoch"])
            self.sequences = int(meta["sequences"])
            self.hold = bool(meta["hold"])
            self.weak_streak = int(meta["weak_streak"])
            if "burst_left" in meta:
                self.burst_left = int(meta["burst_left"])
                self.study_left = int(meta["study_left"])
                self.recent_losses = [float(item) for item in meta.get("recent_losses") or []]
            if "replay_id" in meta:
                self.replay_id = int(meta["replay_id"])
        self._keep_replay_behind_the_cursor()

    def _ready_blocked(self, engine) -> tuple:
        rows = engine.store._all(
            """
            SELECT candidate_id FROM context_blocks
            WHERE run_id=? AND token_length<=?
            ORDER BY candidate_id
            LIMIT ?
            """,
            (engine.run_id, self.config.context, BATCH_CANDIDATES),
        )
        docs = []
        ids = []
        for row in rows:
            candidate = engine.store.get_candidate(int(row["candidate_id"]))
            if candidate is None or candidate["current_status"] != "proved":
                continue
            if candidate["structural_hash"] in HELD_OUT_HASHES:
                continue
            role_docs = role_documents(_source_for(engine.store, engine.run_id, candidate))
            overflow = overflowing_length(role_docs, self.config.context)
            if overflow:
                self._block(engine.store, engine.run_id, int(candidate["id"]), overflow)
                continue
            if not role_docs:
                self._clear_blocks(engine.store, engine.run_id, [int(candidate["id"])])
                continue
            docs.extend(role_docs)
            ids.append(int(candidate["id"]))
        return docs, ids

    def _block(self, store, run_id: str, candidate_id: int, token_length: int) -> None:
        now = store.now()
        store.conn.execute(
            """
            INSERT INTO context_blocks (
              run_id, candidate_id, token_length, context_limit, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, candidate_id) DO UPDATE SET
              token_length=excluded.token_length,
              context_limit=excluded.context_limit,
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                run_id,
                candidate_id,
                token_length,
                self.config.context,
                BLOCKED_BY_CONTEXT,
                now,
                now,
            ),
        )

    def _clear_blocks(self, store, run_id: str, candidate_ids: list) -> None:
        if not candidate_ids:
            return
        marks = ",".join("?" for _ in candidate_ids)
        store.conn.execute(
            f"DELETE FROM context_blocks WHERE run_id=? AND candidate_id IN ({marks})",
            (run_id, *candidate_ids),
        )

    def _blocked_count(self, store, run_id: str) -> int:
        return store.count_where(
            "SELECT COUNT(*) FROM context_blocks WHERE run_id=?",
            (run_id,),
        )

    def _closed_page(self, store, run_id: str, after: int) -> tuple:
        """The next 4 proved rows, or a short tail when nothing is left ahead.

        An in-flight sentence is a stop. Sentences already proved before it wait
        until four of them are closed, so a slow check does not cut a smaller step.
        """
        chosen = []
        cursor = after
        while len(chosen) < BATCH_CANDIDATES:
            row = store._one(
                """
                SELECT * FROM candidates
                WHERE run_id=? AND id>?
                ORDER BY id
                LIMIT 1
                """,
                (run_id, cursor),
            )
            if row is None:
                return chosen, cursor, False
            if is_in_flight(store.conn, run_id, row):
                return [], after, True
            cursor = int(row["id"])
            if int(row["held_out"]) or row["structural_hash"] in HELD_OUT_HASHES:
                continue
            if row["current_status"] != "proved":
                continue
            chosen.append(row)
        return chosen, cursor, False

    def _untrained(self, store, run_id: str) -> int:
        return unread_in_prefix(store.conn, run_id, self.cursor_id)

    def _judged_dispositions(self, store, run_id: str) -> list:
        if store._one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='model_attempts'"
        ) is None:
            return []
        rows = store._all(
            """
            SELECT disposition, equation FROM model_attempts
            WHERE run_id=? AND disposition != 'queued'
            ORDER BY CAST(created_at AS REAL), id
            """,
            (run_id,),
        )
        return [
            (row["disposition"], statement_depth(row["equation"] or ""))
            for row in rows
        ]

    def _hash_known(self, store, run_id: str, digest: str) -> bool:
        row = store._one(
            """
            SELECT id FROM candidates
            WHERE run_id=? AND structural_hash=?
            LIMIT 1
            """,
            (run_id, digest),
        )
        return row is not None

    def _ensure_seen(self, store, run_id: str) -> None:
        if self.seen_ready:
            return
        rows = store._all(
            """
            SELECT equation_hash FROM model_attempts
            WHERE run_id=? AND disposition!='duplicate'
            """,
            (run_id,),
        )
        self.seen.update(row["equation_hash"] for row in rows)
        proofs = store._all(
            """
            SELECT payload_json FROM queue_jobs
            WHERE run_id=? AND job_type='lean_validate' AND state='done'
            """,
            (run_id,),
        )
        for row in proofs:
            source = json.loads(row["payload_json"]).get("source") or ""
            body = equation_body(theorem_line(source))
            if body:
                self.seen.add(equation_hash(body))
        self.seen_ready = True

    def _load_state(self, store, run_id: str) -> None:
        row = store._one("SELECT * FROM lm_state WHERE run_id=?", (run_id,))
        if row is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._save_state(store, run_id)
            return
        self.step = int(row["step"])
        self.epoch = int(row["epoch"])
        self.cursor_id = int(row["cursor_id"])
        self.pass_cursor = int(row["pass_cursor"])
        self.sequences = int(row["sequences"])
        self.hold = bool(row["hold"])
        self.weak_streak = int(row["weak_streak"])
        self.last_loss = row["last_loss"]
        self.last_error = row["last_error"]
        self.burst_left = int(row["burst_left"])
        self.study_left = int(row["study_left"])
        self.recent_losses = [float(item) for item in json.loads(row["recent_losses"] or "[]")]
        names = set(row.keys())
        self.replay_id = int(row["replay_id"]) if "replay_id" in names else 0
        if "probe" in names:
            self.probe = bool(row["probe"]) or self.probe
            self.phase = row["probe_phase"] or "train"
            self.cycle = int(row["probe_cycle"])
            self.cycles = int(row["probe_cycles"])
            self.draw_left = int(row["probe_draw_left"])
            self.greedy_left = int(row["probe_greedy_left"])
        if "probe_task" in names and (row["probe_task"] == "hole" or self.hole):
            self.hole = True
            self.repair = False
            self.probe = True
            self.hole_from = row["hole_from"] if "hole_from" in names else ""
            self.hole_broken = row["repair_prefix"] or ""
            self.hole_index = int(row["repair_at"] or 0)
        elif "probe_task" in names and (row["probe_task"] == "repair" or self.repair):
            self.repair = True
            self.probe = True
            self.repair_ply = int(row["repair_ply"])
            self.repair_left = int(row["repair_left"])
            self.repair_at = int(row["repair_at"])
            self.repair_prefix = row["repair_prefix"] or ""
        self._keep_replay_behind_the_cursor()

    def _keep_replay_behind_the_cursor(self) -> None:
        if self.replay_id > self.cursor_id:
            self.replay_id = self.cursor_id

    def _task_name(self) -> str:
        if self.hole:
            return "hole"
        if self.repair:
            return "repair"
        return ""

    def _save_state(self, store, run_id: str) -> None:
        now = store.now()
        path = str(self.directory / "model.safetensors")
        existing = store._one("SELECT run_id FROM lm_state WHERE run_id=?", (run_id,))
        if existing is None:
            store.conn.execute(
                """
                INSERT INTO lm_state (
                  run_id, step, epoch, cursor_id, pass_cursor, sequences,
                  last_loss, hold, weak_streak, last_error, weights_path, updated_at,
                  burst_left, study_left, recent_losses, replay_id,
                  probe, probe_phase, probe_cycle, probe_cycles, probe_draw_left, probe_greedy_left,
                  probe_task, repair_ply, repair_left, repair_at, repair_prefix, hole_from
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    self.step,
                    self.epoch,
                    self.cursor_id,
                    self.pass_cursor,
                    self.sequences,
                    self.last_loss,
                    1 if self.hold else 0,
                    self.weak_streak,
                    self.last_error,
                    path,
                    now,
                    self.burst_left,
                    self.study_left,
                    json.dumps(self.recent_losses),
                    self.replay_id,
                    1 if self.probe else 0,
                    self.phase,
                    self.cycle,
                    self.cycles,
                    self.draw_left,
                    self.greedy_left,
                    self._task_name(),
                    self.repair_ply,
                    self.repair_left,
                    self.hole_index if self.hole else self.repair_at,
                    self.hole_broken if self.hole else self.repair_prefix,
                    self.hole_from,
                ),
            )
            return
        store.conn.execute(
            """
            UPDATE lm_state
            SET step=?, epoch=?, cursor_id=?, pass_cursor=?, sequences=?,
                last_loss=?, hold=?, weak_streak=?, last_error=?, weights_path=?, updated_at=?,
                burst_left=?, study_left=?, recent_losses=?, replay_id=?,
                probe=?, probe_phase=?, probe_cycle=?, probe_cycles=?,
                probe_draw_left=?, probe_greedy_left=?,
                probe_task=?, repair_ply=?, repair_left=?, repair_at=?, repair_prefix=?, hole_from=?
            WHERE run_id=?
            """,
            (
                self.step,
                self.epoch,
                self.cursor_id,
                self.pass_cursor,
                self.sequences,
                self.last_loss,
                1 if self.hold else 0,
                self.weak_streak,
                self.last_error,
                path,
                now,
                self.burst_left,
                self.study_left,
                json.dumps(self.recent_losses),
                self.replay_id,
                1 if self.probe else 0,
                self.phase,
                self.cycle,
                self.cycles,
                self.draw_left,
                self.greedy_left,
                self._task_name(),
                self.repair_ply,
                self.repair_left,
                self.hole_index if self.hole else self.repair_at,
                self.hole_broken if self.hole else self.repair_prefix,
                self.hole_from,
                run_id,
            ),
        )
