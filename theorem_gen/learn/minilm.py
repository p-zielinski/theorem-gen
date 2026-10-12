"""50M transformer trained from scratch on proved Lean lines.

Two role tags, each one special token:

- `<|propose|>` continues as the theorem statement
- `<|prove|>` continues as the statement plus its proof

The model does not speak until one of those tags is given. Sampled equations
are kept only when their body is not already in the run. Lean still decides
`proved`. A weak or repeated window stops sampling and rehearses.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from theorem_gen.learn.errors import Backpressure
from theorem_gen.learn.prefix import is_in_flight, unread_in_prefix
from theorem_gen.learn.balance import (
    after_sample,
    after_train,
    choose_action,
    loss_is_ready,
    observe,
    open_burst,
    remember_loss,
)
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
    """One writer-side trainer. A low-loss burst writes ten equations, then study resumes."""

    def __init__(self, directory: Path, config=None) -> None:
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
        self._aligned = False

    def tick(self, engine) -> None:
        self._load_state(engine.store, engine.run_id)
        self._rewind_to_weights()
        ready = loss_is_ready(self.recent_losses)
        self.burst_left, self.study_left = open_burst(
            self.burst_left, self.study_left, ready and not self.hold
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
        elif action == "rehearse":
            self._rehearse(engine)
        elif action == "sample":
            try:
                disposition = self._sample(engine)
            except Backpressure:
                return
            self.burst_left, self.study_left = after_sample(
                self.burst_left, self.study_left, disposition
            )
            self._save_state(engine.store, engine.run_id)

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
        self._apply_observation(store, candidate["run_id"], status)

    def stop(self) -> None:
        self._write_weights(moments=True)

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

    def _sample(self, engine) -> str:
        self._ensure_seen(engine.store, engine.run_id)
        self._ensure_trainer()
        token_ids = self.trainer.complete([PROPOSE])
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
        return self._enqueue(engine, body, digest, full)

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
        engine.queue.enqueue(
            engine.run_id,
            "lean_validate",
            payload={
                "candidate_id": candidate["id"],
                "source": full + "\n",
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
        engine.store.conn.execute(
            """
            INSERT INTO model_attempts (
              run_id, equation, equation_hash, origin, disposition, candidate_id, created_at
            ) VALUES (?, ?, ?, 'model', ?, ?, ?)
            """,
            (engine.run_id, body, digest, disposition, candidate_id, now),
        )
        if disposition != "queued":
            self._apply_observation(engine.store, engine.run_id, disposition)

    def _apply_observation(self, store, run_id: str, disposition: str) -> None:
        streak, should_hold = observe(disposition, self.weak_streak)
        self.weak_streak = streak
        if disposition == "proved":
            self.hold = False
        elif should_hold:
            self.hold = True
            self.pass_cursor = 0
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
                  burst_left, study_left, recent_losses
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            return
        store.conn.execute(
            """
            UPDATE lm_state
            SET step=?, epoch=?, cursor_id=?, pass_cursor=?, sequences=?,
                last_loss=?, hold=?, weak_streak=?, last_error=?, weights_path=?, updated_at=?,
                burst_left=?, study_left=?, recent_losses=?
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
                run_id,
            ),
        )
