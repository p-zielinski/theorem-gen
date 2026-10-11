"""Atomic checkpoint publish. A crash before replace keeps the previous known-good."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from theorem_gen.learn.errors import LearnError

CHECKPOINT_MIN_S = 300
CHECKPOINT_MAX_S = 600
CHECKPOINT_DEFAULT_S = 300


def normalize_interval(seconds: int) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise LearnError("checkpoint interval must be an int")
    if seconds < CHECKPOINT_MIN_S or seconds > CHECKPOINT_MAX_S:
        raise LearnError("checkpoint interval must be between 300 and 600 seconds")
    return seconds


class Checkpoints:
    def __init__(self, store, directory: Path, hooks) -> None:
        self.store = store
        self.directory = Path(directory)
        self.hooks = hooks

    def path_for(self, run_id: str, seq: int) -> Path:
        return self.directory / run_id / f"{seq}.json"

    def publish(self, run_id: str, *, reason: str, scheduler: dict, rng_state: int, level: int, frozen: int) -> dict:
        seq = self.store.next_checkpoint_seq(run_id)
        attempt_cursor = self.store.attempt_cursor(run_id)
        payload = {
            "run_id": run_id,
            "seq": seq,
            "event_cursor": self.store.event_cursor(run_id),
            "scheduler": scheduler,
            "rng_state": rng_state,
            "curriculum_level": level,
            "advancement_frozen": frozen,
            "attempt_cursor": attempt_cursor,
            "reason": reason,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        final = self.path_for(run_id, seq)
        final.parent.mkdir(parents=True, exist_ok=True)
        temporary = final.parent / (final.name + ".tmp")
        temporary.write_text(body, encoding="utf-8")
        self.hooks.hit("during_checkpoint_write")
        os.replace(temporary, final)
        self.hooks.hit("after_replace_before_checkpoint_row")
        run = self.store.get_run(run_id)
        window = int(run["checkpoint_window"]) + 1
        with self.store.transaction():
            row = self.store.insert_checkpoint(
                run_id=run_id,
                seq=seq,
                event_cursor=payload["event_cursor"],
                scheduler_state_json=json.dumps(scheduler, sort_keys=True),
                rng_state=str(rng_state),
                curriculum_state_json=json.dumps(
                    {"level": level, "frozen": frozen},
                    sort_keys=True,
                ),
                artifact_hashes_json=json.dumps(
                    {"attempt_cursor": attempt_cursor, "snapshot": digest},
                    sort_keys=True,
                ),
                reason=reason,
            )
            status = "paused" if reason == "pause" else "running"
            self.store.update_run(
                run_id,
                status=status,
                checkpoint_window=window,
                promoted_in_window=0,
            )
            self.store.append_event(run_id, "checkpoint", {"seq": seq, "reason": reason})
        return row

    def verify(self, row: dict) -> None:
        if not row or not row["known_good"]:
            raise LearnError("checkpoint is not known-good")
        path = self.path_for(row["run_id"], row["seq"])
        if not path.is_file():
            raise LearnError("known-good checkpoint file is missing")
        body = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        stored = json.loads(row["artifact_hashes_json"])
        if digest != stored["snapshot"]:
            raise LearnError("checkpoint file does not match the stored hash")
        parsed = json.loads(body)
        if int(parsed["attempt_cursor"]) != int(stored["attempt_cursor"]):
            raise LearnError("checkpoint attempt cursor was modified")
        if parsed.get("run_id") != row["run_id"] or int(parsed["seq"]) != int(row["seq"]):
            raise LearnError("checkpoint identity does not match the snapshot")
        if int(parsed["rng_state"]) != int(row["rng_state"]):
            raise LearnError("checkpoint rng does not match the snapshot")
        if int(parsed["event_cursor"]) != int(row["event_cursor"]):
            raise LearnError("checkpoint event cursor does not match the snapshot")
        if parsed["scheduler"] != json.loads(row["scheduler_state_json"]):
            raise LearnError("checkpoint scheduler does not match the snapshot")
        curriculum = json.loads(row["curriculum_state_json"])
        if int(parsed["curriculum_level"]) != int(curriculum["level"]):
            raise LearnError("checkpoint curriculum does not match the snapshot")
        if int(parsed["advancement_frozen"]) != int(curriculum["frozen"]):
            raise LearnError("checkpoint frozen flag does not match the snapshot")
