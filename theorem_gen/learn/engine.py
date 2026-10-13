"""Scheduler for one run. Roles share one model slot and never write an outcome."""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from theorem_gen.export_lean import export_prop
from theorem_gen.learn.batches import has_capability, novel_batch, review_items, rich_items, source_for
from theorem_gen.learn.checkpoint import CHECKPOINT_DEFAULT_S, Checkpoints, normalize_interval
from theorem_gen.learn.curriculum import assess_gate, level_is_justified
from theorem_gen.learn.errors import Backpressure, CapabilityError, Crash, LearnError
from theorem_gen.learn.heldout import HELD_OUT_HASHES, evaluate_held_out, scores_from_held_out
from theorem_gen.learn.policy import CHAMPION_ID, adjudicate, admit_descendant, ensure_baseline, learning_claimed
from theorem_gen.learn.queue import INFERENCE_JOBS, LEAN_JOBS, JobQueue
from theorem_gen.learn import minilm
from theorem_gen.learn.train import enqueue as enqueue_train
from theorem_gen.learn.train import progress as train_progress
from theorem_gen.learn.train import remember_workers, snapshot as train_snapshot
from theorem_gen.learn.roles import alternate_prompt, proposer_prompt, prover_prompt, retrieve
from theorem_gen.learn.validate import (
    false_proposition,
    load_candidate_prop,
    negation_source,
    python_witness,
    validate_source,
)
from theorem_gen.rng import LCG

# A proposal is tried this many times, then the batch index advances.
PROPOSE_ATTEMPTS = 3


def default_project_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "lean"


class Hooks:
    def __init__(self, crash_at: str = None) -> None:
        self.crash_at = crash_at

    def hit(self, point: str) -> None:
        if self.crash_at == point:
            raise Crash(point)


class Meter:
    def __init__(self) -> None:
        self.inference_busy = 0
        self.inference_idle = 0
        self.lean_busy = 0
        self.lean_idle = 0

    def ratio(self, kind: str) -> float:
        busy = getattr(self, f"{kind}_busy")
        idle = getattr(self, f"{kind}_idle")
        total = busy + idle
        if total == 0:
            return 0.0
        return busy / total


class ModelSlot:
    """One resident backend. Roles are requests, not extra copies of the weights."""

    def __init__(self, backend) -> None:
        self.backend = backend
        self.resident_copies = 0
        self.loaded = False
        self.model_version = "none"
        self._busy = False

    def complete(self, role: str, prompt: str) -> str:
        if self._busy:
            raise LearnError("the single model slot is already serving a request")
        if not self.loaded:
            self.loaded = True
            self.resident_copies = 1
        if self.resident_copies != 1:
            raise LearnError("refusing to keep more than one resident model")
        self._busy = True
        try:
            return self.backend.complete(role, prompt)
        finally:
            self._busy = False


class RaiseBackend:
    invoked_model = False

    def complete(self, role: str, prompt: str) -> str:
        raise LearnError("live inference is not available")


class ReplayBackend:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.invoked_model = False
        self.calls = 0

    def complete(self, role: str, prompt: str) -> str:
        self.calls += 1
        if not self.responses:
            raise LearnError("replay exhausted recorded responses")
        return self.responses.pop(0)


class Engine:
    def __init__(
        self,
        store,
        *,
        run_id: str,
        seed: int = 1,
        batch_count: int = 4,
        curriculum: int = 1,
        max_steps=50,
        checkpoint_interval_s: int = CHECKPOINT_DEFAULT_S,
        high_water: int = 128,
        lease_ttl_s: float = 30.0,
        lean_timeout_s: float = 60.0,
        project_dir: Path = None,
        backend=None,
        runner=None,
        hooks=None,
        until_pause: bool = False,
        refill_when_idle: bool = False,
        lean_workers: int = 1,
        lm: bool = False,
        probe: bool = False,
        repair: bool = False,
        language=None,
    ) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise LearnError("seed must be an int")
        if isinstance(batch_count, bool) or not isinstance(batch_count, int) or batch_count < 0:
            raise LearnError("batch_count must be >= 0")
        if isinstance(lean_workers, bool) or not isinstance(lean_workers, int) or not 1 <= lean_workers <= 32:
            raise LearnError("lean_workers must be an int from 1 to 32")
        self.store = store
        self.lean_workers = lean_workers
        self.lm_enabled = bool(lm or language is not None)
        self.repair = bool(repair)
        self.probe = bool(probe) or self.repair
        self._language = language
        self.run_id = run_id
        self.seed = seed
        self.batch_count = batch_count
        self.curriculum = curriculum
        self.max_steps = max_steps
        self.checkpoint_interval_s = normalize_interval(checkpoint_interval_s)
        self.lean_timeout_s = lean_timeout_s
        self.project_dir = Path(project_dir) if project_dir is not None else default_project_dir()
        self.runner = runner
        self.hooks = Hooks() if hooks is None else hooks
        self.until_pause = until_pause
        self.refill_when_idle = refill_when_idle
        self.pause_requested = False
        self.lean_block = None
        self.queue = JobQueue(store, high_water=high_water, lease_ttl_s=lease_ttl_s)
        self.checkpoints = Checkpoints(
            store,
            store.path.parent / "checkpoints",
            self.hooks,
        )
        self.slot = ModelSlot(RaiseBackend() if backend is None else backend)
        self.meter = Meter()
        self.rng = LCG(seed)
        self.scheduler = {
            "batch_index": 0,
            "last_mix": None,
            "hold_propose": False,
            "last_checkpoint_at": None,
        }

    def close(self) -> None:
        self.store.close()

    def request_pause(self) -> None:
        self.pause_requested = True

    @property
    def level(self) -> int:
        return int(self.store.get_run(self.run_id)["curriculum_level"])

    def start(self) -> None:
        self.store.migrate()
        self.bootstrap()
        try:
            self.run_steps(self.max_steps)
        except Crash:
            self.close()
            raise
        self.finish()

    def finish(self) -> None:
        """Pause if the loop is still running. A missing toolchain stays queued."""
        self.pause()
        if self.lean_block:
            raise LearnError(self.lean_block)

    def bootstrap(self) -> None:
        if self.store.get_run(self.run_id) is not None:
            raise LearnError("run already exists; use resume")
        if self.curriculum != 1:
            raise LearnError("a new run starts at curriculum level 1")
        self.store.create_run(
            self.run_id,
            seed=self.seed,
            curriculum_level=1,
            config=self._config(),
        )
        self.rng = LCG(self.seed)
        self.scheduler = {
            "batch_index": 0,
            "last_mix": None,
            "hold_propose": False,
            "last_checkpoint_at": None,
        }
        self.publish("start")
        self._enqueue_propose()
        remember_workers(self.store, self.run_id, self.lean_workers)

    def run_steps(self, n) -> None:
        if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 0):
            raise LearnError("max_steps must be >= 0 or None")
        steps = 0
        ran = False
        while n is None or steps < n:
            if self.pause_requested:
                self.pause()
                return
            self._maybe_time_checkpoint()
            did = self.cooperative_step()
            self._train_slice()
            self._lm_slice()
            if not did:
                if self.scheduler.get("hold_propose"):
                    return
                if ran:
                    self.promote_if_ready()
                    ran = False
                if self._continue_after_idle(n, steps) and self._schedule_next_batch():
                    continue
                return
            ran = True
            steps += 1
        if n is not None and n > 0 and not self.pause_requested:
            self._finish_open_batch()
            self._train_slice()
            self._lm_slice()
        if ran:
            self.promote_if_ready()

    def _finish_open_batch(self) -> None:
        """Validate Lean jobs already queued when the step cap lands mid-batch.

        Proposals stay queued: a failed propose is resumed later, and a new
        batch is not opened here. Two Lean steps that do not shrink the
        queue stop the drain, so a released job cannot spin.
        """
        kinds = ("lean_validate",)
        stalled = 0
        while not self.pause_requested:
            self._maybe_time_checkpoint()
            depth = self.queue.depth(self.run_id, kinds)
            if depth <= 0:
                return
            if not self._serve(kinds, "lean"):
                return
            if self.queue.depth(self.run_id, kinds) >= depth:
                stalled += 1
                if stalled >= 2:
                    return
            else:
                stalled = 0

    def cooperative_step(self) -> bool:
        did = False
        inference = INFERENCE_JOBS
        if self.scheduler.get("hold_propose"):
            inference = tuple(kind for kind in INFERENCE_JOBS if kind != "propose")
        if inference and self._serve(inference, "inference"):
            did = True
        if self._serve(LEAN_JOBS, "lean"):
            did = True
        return did

    def _serve(self, kinds, meter_kind: str) -> bool:
        if (
            meter_kind == "lean"
            and self.lean_workers > 1
            and self.queue.depth(self.run_id, ("lean_validate",)) > 0
        ):
            return self._serve_lean_parallel()
        if self.queue.depth(self.run_id, kinds) <= 0:
            return False
        job = self.queue.dequeue(self.run_id, meter_kind, kinds, self.hooks)
        if job is None or not self.queue.heartbeat(job["id"], job["lease_owner"]):
            setattr(self.meter, f"{meter_kind}_idle", getattr(self.meter, f"{meter_kind}_idle") + 1)
            return False
        outcome = self._dispatch(job)
        if outcome == "done":
            setattr(self.meter, f"{meter_kind}_busy", getattr(self.meter, f"{meter_kind}_busy") + 1)
        else:
            setattr(self.meter, f"{meter_kind}_idle", getattr(self.meter, f"{meter_kind}_idle") + 1)
        return True

    def _serve_lean_parallel(self) -> bool:
        """Run several Lean checks at once. SQLite writes stay on this thread."""
        batch = []
        while len(batch) < self.lean_workers:
            if self.queue.depth(self.run_id, ("lean_validate",)) <= 0:
                break
            job = self.queue.dequeue(self.run_id, "lean", ("lean_validate",), self.hooks)
            if job is None or not self.queue.heartbeat(job["id"], job["lease_owner"]):
                setattr(self.meter, "lean_idle", self.meter.lean_idle + 1)
                break
            try:
                batch.append((job, self._lean_request(job)))
            except Crash:
                raise
            except Exception as exc:
                self._fail_job(job, exc)
        if not batch:
            return False
        futures = {}
        with ThreadPoolExecutor(max_workers=len(batch), thread_name_prefix="lean") as pool:
            for job, request in batch:
                futures[pool.submit(self._execute_lean, request)] = (job, request)
            waiting = set(futures)
            while waiting:
                done, waiting = wait(waiting, timeout=0.05, return_when=FIRST_COMPLETED)
                if not done:
                    self._train_slice()
                    continue
                for future in done:
                    job, request = futures[future]
                    try:
                        recorded = future.result()
                    except Exception as exc:
                        self._fail_job(job, exc)
                        self.meter.lean_idle += 1
                        continue
                    outcome = self._finish_lean(job, request, recorded)
                    if outcome == "done":
                        self.meter.lean_busy += 1
                    else:
                        self.meter.lean_idle += 1
        return True

    def _train_slice(self) -> None:
        train_progress(self.store, self.run_id, lean_workers=self.lean_workers)

    def _ensure_lm(self) -> None:
        if self._language is not None:
            return
        from theorem_gen.learn.minilm import MiniLMService

        self._language = MiniLMService(
            self.store.path.parent / "lm" / self.run_id,
            probe=self.probe,
            repair=self.repair,
        )

    def _lm_slice(self) -> None:
        if not self.lm_enabled:
            return
        try:
            self._ensure_lm()
            self._language.tick(self)
        except Exception as exc:
            self.lm_enabled = False
            print(f"lm error: {exc}", flush=True)

    def _stop_lm(self) -> None:
        if self._language is None:
            return
        self._language.stop()

    def _fail_job(self, job: dict, exc: BaseException) -> None:
        self.queue.fail(job)
        self.store.append_event(
            self.run_id,
            "job_failed",
            {"job_id": job["id"], "error": str(exc)},
        )
        if self._language is not None and job["job_type"] == "lean_validate":
            try:
                self._language.note_failure(self.store, job)
            except Exception as err:
                print(f"lm verdict error: {err}", flush=True)

    def pause(self) -> None:
        run = self.store.get_run(self.run_id)
        if run is None:
            raise LearnError("unknown run")
        if run["status"] == "paused":
            return
        self._stop_lm()
        self.queue.release_all(self.run_id)
        self.publish("pause")

    def resume(self) -> None:
        self.pause_requested = False
        self.lean_block = None
        self.store.migrate()
        if self.store.integrity() != "ok":
            raise LearnError(self.store.integrity())
        run = self.store.get_run(self.run_id)
        if run is None:
            raise LearnError("unknown run")
        row = self.store.latest_known_good(self.run_id)
        if row is None:
            if self._has_any_job() or self.store.list_candidates(self.run_id):
                raise LearnError("no known-good checkpoint")
            self.rng = LCG(int(run["seed"]))
            self.scheduler = {
                "batch_index": 0,
                "last_mix": None,
                "hold_propose": False,
                "last_checkpoint_at": None,
            }
            self.publish("start")
            self._ensure_initial_propose()
            remember_workers(self.store, self.run_id, self.lean_workers)
            return
        self.checkpoints.verify(row)
        curriculum = json.loads(row["curriculum_state_json"])
        level = int(curriculum["level"])
        if level != int(run["curriculum_level"]):
            raise LearnError("checkpoint level does not match the run")
        if not level_is_justified(self.store, self.run_id, level):
            raise LearnError("checkpoint level is not justified by curriculum gates")
        self.rng = LCG(0)
        self.rng.set_state(int(row["rng_state"]))
        self.scheduler = json.loads(row["scheduler_state_json"])
        self.scheduler["hold_propose"] = False
        self._fast_forward_scheduler(int(row["event_cursor"]))
        self.queue.reclaim_abandoned(self.run_id)
        self._ensure_initial_propose()
        if run["status"] != "running":
            self.store.update_run(self.run_id, status="running")
        remember_workers(self.store, self.run_id, self.lean_workers)

    def publish(self, reason: str) -> dict:
        run = self.store.get_run(self.run_id)
        self.scheduler["last_checkpoint_at"] = self.store.clock.time()
        return self.checkpoints.publish(
            self.run_id,
            reason=reason,
            scheduler=self.scheduler,
            rng_state=self.rng.get_state(),
            level=int(run["curriculum_level"]),
            frozen=int(run["advancement_frozen"]),
        )

    def status(self) -> dict:
        run = self.store.get_run(self.run_id)
        checkpoint = self.store.latest_known_good(self.run_id)
        return {
            "run_id": self.run_id,
            "status": run["status"],
            "curriculum_level": run["curriculum_level"],
            "event_cursor": self.store.event_cursor(self.run_id),
            "queue": self.queue.depths(self.run_id),
            "model_version": run["model_version"],
            "checkpoint_seq": None if checkpoint is None else checkpoint["seq"],
            "advancement_frozen": bool(run["advancement_frozen"]),
            "learning": learning_claimed(self.store),
            **train_snapshot(self.store, self.run_id),
            **minilm.counts(self.store, self.run_id),
        }

    def promote_if_ready(self) -> bool:
        if not self.maybe_promote():
            return False
        self.publish("promotion")
        return True

    def promote_model(self, challenger_id: str) -> str:
        """Offline challenger decision. A promotion checkpoints; a rollback does not."""
        outcome = adjudicate(self.store, challenger_id)
        if outcome == "promoted":
            self.store.update_run(self.run_id, model_version=challenger_id)
            self.publish("model_promotion")
        return outcome

    def maybe_promote(self) -> bool:
        run = self.store.get_run(self.run_id)
        if run["promoted_in_window"]:
            return False
        if int(run["curriculum_level"]) >= 7:
            return False
        result = self._held_out()
        self.store.update_run(self.run_id, held_out_latest=result["score"])
        baseline = self.store.get_run(self.run_id)["held_out_baseline"]
        if baseline is None:
            baseline = result["score"]
            self.store.update_run(self.run_id, held_out_baseline=baseline)
        ensure_baseline(self.store, scores_from_held_out(result))
        if not self.store.get_run(self.run_id)["model_version"]:
            self.store.update_run(self.run_id, model_version=CHAMPION_ID)
        decision = assess_gate(
            self.store,
            self.run_id,
            held_out_latest=float(result["score"]),
            held_out_baseline=float(baseline),
        )
        if not decision["promote"]:
            if decision["freeze"]:
                self.store.update_run(self.run_id, advancement_frozen=1)
                self.store.upsert_window(
                    run_id=self.run_id,
                    level=decision["level"],
                    window_index=-1,
                    metrics_json=json.dumps({"reason": decision["reason"]}, sort_keys=True),
                    gate_status="frozen",
                    evaluated_count=decision["evaluated"],
                )
                self.store.append_event(
                    self.run_id,
                    "gate_frozen",
                    {"reason": decision["reason"], "level": decision["level"]},
                )
            return False
        new_level = decision["level"] + 1
        self.store.upsert_window(
            run_id=self.run_id,
            level=decision["level"],
            window_index=-1,
            metrics_json=json.dumps(
                {"reason": "passed", "evaluated": decision["evaluated"]},
                sort_keys=True,
            ),
            gate_status="passed",
            evaluated_count=decision["evaluated"],
        )
        self.store.update_run(
            self.run_id,
            curriculum_level=new_level,
            promoted_in_window=1,
            advancement_frozen=0,
        )
        self.store.append_event(self.run_id, "promoted", {"to": new_level})
        return True

    def note_witness(self, candidate_id: int):
        candidate = self.store.get_candidate(candidate_id)
        statement = load_candidate_prop(candidate["canonical_ast_json"])
        found = python_witness(statement)
        if found is None:
            return None
        return self.store.insert_counterexample(
            candidate_id=candidate_id,
            assignment_json=json.dumps(found["assignment"], sort_keys=True),
            instantiated_prop=found["instantiated_prop"],
            proposed_by="python",
        )

    def certify_witness(self, candidate_id: int, counterexample_id: int) -> str:
        candidate = self.store.get_candidate(candidate_id)
        rows = self.store.list_counterexamples(candidate_id)
        row = next(item for item in rows if item["id"] == counterexample_id)
        source = negation_source(row["instantiated_prop"], candidate["stable_id"])
        self._commit_validation(
            candidate_id=candidate_id,
            source=source,
            validation_type="counterexample",
            idempotency_key=f"{self.run_id}:cert:{candidate['stable_id']}",
            counterexample_id=counterexample_id,
        )
        return self.store.get_candidate(candidate_id)["current_status"]

    def _commit_validation(
        self,
        *,
        candidate_id: int,
        source: str,
        validation_type: str,
        idempotency_key: str,
        counterexample_id=None,
        job=None,
    ) -> dict:
        request = self._bound_request(
            candidate_id=candidate_id,
            source=source,
            validation_type=validation_type,
            idempotency_key=idempotency_key,
            counterexample_id=counterexample_id,
        )
        recorded = self._execute_lean(request)
        self.hooks.hit("after_validate_before_commit")
        if recorded["result"] == "unavailable":
            if job is not None:
                self._release_unavailable(job, recorded)
            return recorded
        self._write_lean(request, recorded, job)
        return recorded

    def replay_into(self, dest_store, from_seq: int, backend_factory=ReplayBackend) -> bool:
        row = self.store.get_checkpoint(self.run_id, from_seq)
        if row is None:
            raise LearnError("checkpoint not found")
        self.checkpoints.verify(row)
        config = json.loads(self.store.get_run(self.run_id)["config_json"])
        responses = self._responses_after(row)
        curriculum = json.loads(row["curriculum_state_json"])
        backend = backend_factory(responses)
        self.last_replay_backend = backend
        engine = Engine(
            dest_store,
            run_id=self.run_id,
            seed=config["seed"],
            batch_count=config["batch_count"],
            curriculum=1,
            max_steps=None if config["max_steps"] < 0 else config["max_steps"],
            checkpoint_interval_s=config["checkpoint_interval_s"],
            high_water=config["high_water"],
            lease_ttl_s=config["lease_ttl_s"],
            lean_timeout_s=config["lean_timeout_s"],
            project_dir=self.project_dir,
            backend=backend,
            runner=self.runner,
            hooks=Hooks(),
            until_pause=False,
            refill_when_idle=self._replay_refill(config),
        )
        engine.store.migrate()
        engine.store.create_run(
            self.run_id,
            seed=config["seed"],
            curriculum_level=1,
            config=config,
        )
        engine.rng = LCG(0)
        engine.rng.set_state(int(row["rng_state"]))
        engine.scheduler = json.loads(row["scheduler_state_json"])
        self._copy_gates(engine, int(curriculum["level"]))
        if int(curriculum.get("frozen") or 0):
            engine.store.update_run(self.run_id, advancement_frozen=1)
        engine.publish("start")
        if engine.queue.depth(engine.run_id) == 0:
            engine._enqueue_propose()
        engine.run_steps(engine.max_steps)
        engine.pause()
        return _same_outcomes(self.store, dest_store, self.run_id)

    def _responses_after(self, checkpoint: dict) -> list:
        """Model replies recorded after this checkpoint, in attempt order.

        Generator proposals store the AST and are not model calls. Level 1
        therefore replays with an empty response list. Level 7 feeds each
        role completion from the stored raw_response.
        """
        stored = json.loads(checkpoint["artifact_hashes_json"])
        cursor = int(stored["attempt_cursor"])
        rows = self.store._all(
            """
            SELECT attempts.raw_response
            FROM attempts
            JOIN candidates ON candidates.id = attempts.candidate_id
            WHERE candidates.run_id=?
              AND attempts.id > ?
              AND attempts.model_version IS NOT NULL
              AND attempts.model_version != 'generator'
            ORDER BY attempts.id
            """,
            (self.run_id, cursor),
        )
        return [row["raw_response"] for row in rows]

    def _config(self) -> dict:
        max_steps = -1 if self.max_steps is None else self.max_steps
        return {
            "seed": self.seed,
            "batch_count": self.batch_count,
            "checkpoint_interval_s": self.checkpoint_interval_s,
            "max_steps": max_steps,
            "high_water": self.queue.high_water,
            "lease_ttl_s": self.queue.lease_ttl_s,
            "lean_timeout_s": self.lean_timeout_s,
            "until_pause": self.until_pause,
            "refill_when_idle": self.refill_when_idle,
            "probe": self.probe,
            "repair": self.repair,
        }

    def _replay_refill(self, config: dict) -> bool:
        """Replay a bounded run with the same batch schedule. Never loop forever."""
        if int(config["max_steps"]) < 0:
            return False
        return bool(config.get("refill_when_idle"))

    def _continue_after_idle(self, n, steps: int) -> bool:
        if self.pause_requested:
            return False
        if n is not None and steps >= n:
            return False
        return bool(self.until_pause or self.refill_when_idle)

    def _schedule_next_batch(self) -> bool:
        """Queue the scheduler's current proposal.

        A finished key for that index means the scheduler was not advanced.
        Returning false keeps the loop from enqueueing the same key forever.
        """
        index = int(self.scheduler["batch_index"])
        existing = self.store._one(
            "SELECT state FROM queue_jobs WHERE idempotency_key=?",
            (f"{self.run_id}:propose:{index}",),
        )
        if existing is not None and existing["state"] != "queued":
            return False
        try:
            self._enqueue_propose()
        except Backpressure:
            self.scheduler["hold_propose"] = True
            return False
        return True

    def _held_out(self) -> dict:
        def validate(source, validation_type):
            return validate_source(
                source,
                validation_type=validation_type,
                project_dir=self.project_dir,
                timeout_s=self.lean_timeout_s,
                runner=self.runner,
            )

        return evaluate_held_out(validate)

    def _maybe_time_checkpoint(self) -> None:
        last = self.scheduler.get("last_checkpoint_at")
        if last is None:
            return
        if self.store.clock.time() - float(last) >= self.checkpoint_interval_s:
            self.publish("interval")

    def _enqueue_propose(self) -> None:
        index = int(self.scheduler["batch_index"])
        self.queue.enqueue(
            self.run_id,
            "propose",
            payload={"batch_index": index},
            idempotency_key=f"{self.run_id}:propose:{index}",
        )

    def _dispatch(self, job: dict) -> str:
        try:
            kind = job["job_type"]
            if kind == "propose":
                return self._propose(job)
            if kind == "prove_primary":
                self._require("roles")
                return self._role(job, "prover", "primary")
            if kind == "prove_alternate_or_critique":
                self._require("roles")
                phase = json.loads(job["payload_json"]).get("phase", "prove")
                return self._role(job, "alternate_prover_critic", phase)
            if kind == "lean_validate":
                return self._lean(job)
            if kind == "counterexample_search":
                self._search(job)
            else:
                raise LearnError(f"unknown job {kind}")
            return "done"
        except Crash:
            raise
        except CapabilityError:
            self.queue.fail(job)
            return "failed"
        except Backpressure:
            self.scheduler["hold_propose"] = True
            self.queue.release_job(job)
            return "held"
        except Exception as exc:
            if job["job_type"] == "propose":
                return self._retry_propose(job, exc)
            self._fail_job(job, exc)
            return "failed"

    def _retry_propose(self, job: dict, exc: BaseException) -> str:
        """Keep the proposal queued. After three failures, skip that batch index."""
        self.store.append_event(
            self.run_id,
            "job_failed",
            {"job_id": job["id"], "error": str(exc), "retry": True},
        )
        if int(job["retry_count"]) + 1 >= PROPOSE_ATTEMPTS:
            self.queue.fail(job)
            self.scheduler["batch_index"] = int(self.scheduler["batch_index"]) + 1
            try:
                self._enqueue_propose()
            except Backpressure:
                self.scheduler["hold_propose"] = True
            return "failed"
        self.queue.release_for_retry(job)
        return "held"

    def _ensure_initial_propose(self) -> None:
        """Queue the first proposal when it never landed after the start checkpoint."""
        if self.store.list_candidates(self.run_id):
            return
        if self._has_any_job():
            return
        self._enqueue_propose()

    def _has_any_job(self) -> bool:
        return (
            self.store.count_where(
                "SELECT COUNT(*) FROM queue_jobs WHERE run_id=?",
                (self.run_id,),
            )
            > 0
        )

    def _require(self, name: str) -> None:
        if not has_capability(self.level, name):
            raise CapabilityError(f"{name} is not available at curriculum level {self.level}")

    def _propose(self, job: dict) -> str:
        self._require("concrete")
        state_before = self.rng.get_state()
        scheduler_before = dict(self.scheduler)
        index_before = int(self.scheduler["batch_index"])
        try:
            return self._propose_committed(job, state_before, scheduler_before, index_before)
        except Backpressure:
            self._rewind_propose(state_before, scheduler_before, job)
            return "held"
        except Exception:
            self._restore_scheduler(state_before, scheduler_before)
            raise

    def _restore_scheduler(self, state_before: int, scheduler_before: dict) -> None:
        self.rng.set_state(state_before)
        self.scheduler.clear()
        self.scheduler.update(scheduler_before)

    def _rewind_propose(self, state_before: int, scheduler_before: dict, job: dict) -> None:
        self._restore_scheduler(state_before, scheduler_before)
        self.scheduler["hold_propose"] = True
        self.queue.release_job(job)

    def _propose_committed(self, job: dict, state_before: int, scheduler_before: dict, index_before: int) -> str:
        self.scheduler["last_mix"] = self.rng.next_u32()
        self.scheduler["batch_index"] = index_before + 1
        seen = self.store.structural_hashes(self.run_id)
        forward = novel_batch(
            self.level,
            seed=self.seed,
            count=self.batch_count,
            batch_index=index_before,
            run_id=self.run_id,
            seen=seen,
        )
        reviewed = review_items(
            self.level,
            seed=self.seed,
            count=self.batch_count,
            batch_index=index_before,
            run_id=self.run_id,
            seen=set(seen) | {item.structural_hash for item in forward},
        )
        occupied = set(seen) | {item.structural_hash for item in forward + reviewed}
        items = forward + reviewed + rich_items(self.seed, index_before, self.run_id, occupied)
        counts = {}
        for item in items:
            counts["lean_validate"] = counts.get("lean_validate", 0) + 1
            if item.needs_roles:
                counts["prove_primary"] = counts.get("prove_primary", 0) + 1
                counts["prove_alternate_or_critique"] = counts.get("prove_alternate_or_critique", 0) + 1
        for job_type, count in counts.items():
            lane = "generator" if job_type == "lean_validate" else None
            if self.queue.occupancy(self.run_id, job_type, origin=lane) + count > self.queue.high_water:
                self._rewind_propose(state_before, scheduler_before, job)
                return "held"
        prepared = []
        for item in items:
            prepared.append((item, source_for(item), self._proposal_text(item)))
        with self.store.transaction():
            rows = []
            for item, source, proposal in prepared:
                if not admit_descendant(self.store, item.ancestor_stable_id):
                    continue
                candidate = self.store.upsert_candidate(
                    stable_id=item.stable_id,
                    run_id=self.run_id,
                    canonical_ast_json=item.canonical_ast_json,
                    structural_hash=item.structural_hash,
                    kind=item.candidate_kind,
                    provenance=json.dumps(item.provenance, sort_keys=True),
                    current_status="unresolved",
                    curriculum_level=self.level,
                    ancestor_stable_id=item.ancestor_stable_id,
                    family=item.family,
                    ast_size=item.ast_size,
                    depth=item.depth,
                    proof_method=item.proof_method,
                    dependency_depth=item.dependency_depth,
                    held_out=item.structural_hash in HELD_OUT_HASHES,
                )
                self._insert_attempt(
                    candidate,
                    role="theorem_proposer",
                    phase="propose",
                    prompt=proposal["prompt"],
                    raw=proposal["raw"],
                    proof_artifact=None,
                    critique_artifact=None,
                    model_version=proposal["model_version"],
                )
                self.store.append_event(
                    self.run_id,
                    "bound_source",
                    {
                        "candidate_id": candidate["id"],
                        "validation_type": item.validation_type,
                        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    },
                )
                rows.append((item, source, candidate))
            for item, _source, candidate in rows:
                for dep in item.depends_on:
                    target = self.store.get_by_stable(dep)
                    if target is not None:
                        self.store.insert_dependency(candidate["id"], target["id"], "uses_definition")
            if has_capability(self.level, "registry"):
                self.store.append_event(
                    self.run_id,
                    "registry_checked",
                    {"count": len(rows)},
                )
            self.queue.complete(job)
            for item, source, candidate in rows:
                self.queue.enqueue(
                    self.run_id,
                    "lean_validate",
                    payload={
                        "candidate_id": candidate["id"],
                        "source": source,
                        "validation_type": item.validation_type,
                        "counterexample_id": None,
                    },
                    idempotency_key=(
                        f"{self.run_id}:lean_validate:{item.stable_id}:{item.validation_type}"
                    ),
                    origin="generator",
                )
                if item.needs_roles:
                    self.queue.enqueue(
                        self.run_id,
                        "prove_primary",
                        payload={"candidate_id": candidate["id"]},
                        idempotency_key=f"{self.run_id}:prove_primary:{item.stable_id}",
                    )
                    self.queue.enqueue(
                        self.run_id,
                        "prove_alternate_or_critique",
                        payload={"candidate_id": candidate["id"], "phase": "prove"},
                        idempotency_key=f"{self.run_id}:prove_alternate:{item.stable_id}:prove",
                    )
            self.store.append_event(
                self.run_id,
                "scheduler_committed",
                {
                    "batch_index": int(self.scheduler["batch_index"]),
                    "last_mix": self.scheduler["last_mix"],
                    "rng_state": self.rng.get_state(),
                },
            )
        return "done"

    def _proposal_text(self, item) -> dict:
        candidate = {
            "stable_id": item.stable_id,
            "canonical_ast_json": item.canonical_ast_json,
            "structural_hash": item.structural_hash,
            "family": item.family,
        }
        if not item.needs_roles:
            return self._generator_proposal(item)
        found = retrieve(
            self.store,
            self.run_id,
            structural_hash=item.structural_hash,
            family=item.family,
        )
        prompt = proposer_prompt(candidate, found)
        try:
            raw = self.slot.complete("theorem_proposer", prompt)
        except LearnError as exc:
            if str(exc) != "live inference is not available":
                raise
            # No weights are loaded. Keep the generator statement and skip role jobs.
            item.needs_roles = False
            return self._generator_proposal(item)
        return {
            "prompt": prompt,
            "raw": raw,
            "model_version": self.slot.model_version,
        }

    def _generator_proposal(self, item) -> dict:
        return {
            "prompt": item.canonical_ast_json,
            "raw": item.canonical_ast_json,
            "model_version": "generator",
        }

    def _role(self, job: dict, role: str, phase: str) -> str:
        payload = json.loads(job["payload_json"])
        candidate = self.store.get_candidate(payload["candidate_id"])
        if phase == "critique":
            primary = self._artifact(candidate["id"], "prover")
            alternate = self._artifact(candidate["id"], "alternate_prover_critic")
            if primary is None or alternate is None:
                self.queue.release_job(job)
                return "held"
            prompt = alternate_prompt(candidate, "critique", primary=primary, alternate=alternate)
            field = "critique"
        elif role == "prover":
            prompt = prover_prompt(candidate)
            field = "proof"
        else:
            # Prove phase never loads the primary artifact, even if a row exists.
            prompt = alternate_prompt(candidate, "prove", primary=None)
            field = "proof"
        raw = self.slot.complete(role, prompt)
        with self.store.transaction():
            self._insert_attempt(
                candidate,
                role=role,
                phase=phase,
                prompt=prompt,
                raw=raw,
                proof_artifact=raw if field == "proof" else None,
                critique_artifact=raw if field == "critique" else None,
                model_version=self.slot.model_version,
            )
            self.queue.complete(job)
            self._maybe_enqueue_critique(candidate)
        return "done"

    def _maybe_enqueue_critique(self, candidate: dict) -> None:
        if self._artifact(candidate["id"], "prover") is None:
            return
        if self._artifact(candidate["id"], "alternate_prover_critic") is None:
            return
        self.queue.enqueue(
            self.run_id,
            "prove_alternate_or_critique",
            payload={"candidate_id": candidate["id"], "phase": "critique"},
            idempotency_key=f"{self.run_id}:prove_alternate:{candidate['stable_id']}:critique",
        )

    def _artifact(self, candidate_id: int, role: str):
        for attempt in self.store.list_attempts(candidate_id):
            if attempt["role"] != role:
                continue
            if attempt["proof_artifact"]:
                return attempt["proof_artifact"]
        return None

    def _insert_attempt(
        self,
        candidate: dict,
        *,
        role: str,
        phase: str,
        prompt: str,
        raw: str,
        proof_artifact,
        critique_artifact,
        model_version: str,
    ) -> None:
        self.store.insert_attempt(
            candidate_id=candidate["id"],
            role=role,
            model_version=model_version,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            raw_response=raw,
            proof_artifact=proof_artifact,
            critique_artifact=critique_artifact,
            idempotency_key=f"{self.run_id}:{role}:{candidate['stable_id']}:{phase}",
            duration_ms=0,
        )

    def _lean(self, job: dict) -> str:
        request = self._lean_request(job)
        recorded = self._execute_lean(request)
        return self._finish_lean(job, request, recorded)

    def _lean_request(self, job: dict) -> dict:
        payload = json.loads(job["payload_json"])
        return self._bound_request(
            candidate_id=payload["candidate_id"],
            source=payload["source"],
            validation_type=payload["validation_type"],
            idempotency_key=job["idempotency_key"],
            counterexample_id=payload.get("counterexample_id"),
        )

    def _bound_request(
        self,
        *,
        candidate_id: int,
        source: str,
        validation_type: str,
        idempotency_key: str,
        counterexample_id,
    ) -> dict:
        if validation_type == "counterexample":
            if not counterexample_id:
                raise LearnError("counterexample validation requires a witness row")
            source = self._bound_counterexample_source(candidate_id, counterexample_id)
        elif validation_type in {"proof", "check"}:
            self._require_bound_source(candidate_id, validation_type, source)
        else:
            raise LearnError(f"unknown validation type: {validation_type}")
        return {
            "candidate_id": candidate_id,
            "source": source,
            "validation_type": validation_type,
            "idempotency_key": idempotency_key,
            "counterexample_id": counterexample_id,
        }

    def _execute_lean(self, request: dict) -> dict:
        """Lean only. Callers on other threads must not touch SQLite."""
        started = time.perf_counter()
        recorded = validate_source(
            request["source"],
            validation_type=request["validation_type"],
            project_dir=self.project_dir,
            timeout_s=self.lean_timeout_s,
            runner=self.runner,
        )
        recorded["lean_ms"] = int((time.perf_counter() - started) * 1000)
        return recorded

    def _finish_lean(self, job: dict, request: dict, recorded: dict) -> str:
        self.hooks.hit("after_validate_before_commit")
        if recorded["result"] == "unavailable":
            self._release_unavailable(job, recorded)
            return "released"
        self._write_lean(request, recorded, job)
        return "done"

    def _release_unavailable(self, job: dict, recorded: dict) -> None:
        # Do not write a validation. The job key would make the miss permanent.
        self.queue.release_job(job)
        self.lean_block = recorded["message"]
        self.pause_requested = True
        self.store.append_event(
            self.run_id,
            "lean_unavailable",
            {"job_id": job["id"], "message": recorded["message"][:500]},
        )

    def _write_lean(self, request: dict, recorded: dict, job) -> None:
        with self.store.transaction():
            row = self.store.insert_validation(
                candidate_id=request["candidate_id"],
                idempotency_key=request["idempotency_key"],
                **recorded,
            )
            if request["counterexample_id"] and row["accepted"]:
                self.store.set_certificate(request["counterexample_id"], row["id"])
            if job is not None:
                self.queue.complete(job)
            candidate = self.store.get_candidate(request["candidate_id"])
            enqueue_train(self.store, self.run_id, candidate)
        if self._language is not None and candidate is not None:
            try:
                self._language.note_verdict(self.store, candidate)
            except Exception as exc:
                print(f"lm verdict error: {exc}", flush=True)

    def _search(self, job: dict) -> None:
        payload = json.loads(job["payload_json"])
        witness = self.note_witness(payload["candidate_id"])
        with self.store.transaction():
            self.queue.complete(job)
            if witness is None:
                return
            candidate = self.store.get_candidate(payload["candidate_id"])
            source = negation_source(witness["instantiated_prop"], candidate["stable_id"])
            try:
                lane = json.loads(candidate["provenance"]).get("origin")
            except (TypeError, json.JSONDecodeError):
                lane = None
            self.queue.enqueue(
                self.run_id,
                "lean_validate",
                payload={
                    "candidate_id": candidate["id"],
                    "source": source,
                    "validation_type": "counterexample",
                    "counterexample_id": witness["id"],
                },
                idempotency_key=f"{self.run_id}:cert:{candidate['stable_id']}",
                origin="model" if lane == "model" else "generator",
            )

    def _fast_forward_scheduler(self, cursor: int) -> None:
        rows = self.store._all(
            """
            SELECT payload_json FROM events
            WHERE run_id=? AND kind='scheduler_committed' AND seq > ?
            ORDER BY seq
            """,
            (self.run_id, cursor),
        )
        for row in rows:
            payload = json.loads(row["payload_json"])
            self.scheduler["batch_index"] = int(payload["batch_index"])
            self.scheduler["last_mix"] = payload["last_mix"]
            self.rng.set_state(int(payload["rng_state"]))

    def _copy_gates(self, engine, level: int) -> None:
        if level == 1:
            return
        for previous in range(1, level):
            row = self.store._one(
                """
                SELECT * FROM curriculum_progress
                WHERE run_id=? AND level=? AND window_index=-1 AND gate_status='passed'
                LIMIT 1
                """,
                (self.run_id, previous),
            )
            if row is None:
                raise LearnError("checkpoint level is not justified by curriculum gates")
            engine.store.upsert_window(
                run_id=self.run_id,
                level=previous,
                window_index=-1,
                metrics_json=row["metrics_json"],
                gate_status="passed",
                evaluated_count=row["evaluated_count"],
            )
        engine.store.update_run(self.run_id, curriculum_level=level)

    def _require_bound_source(self, candidate_id: int, validation_type: str, source: str) -> None:
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        rows = self.store._all(
            """
            SELECT payload_json FROM events
            WHERE run_id=? AND kind='bound_source'
            ORDER BY seq
            """,
            (self.run_id,),
        )
        for row in rows:
            payload = json.loads(row["payload_json"])
            if payload["candidate_id"] != candidate_id or payload["validation_type"] != validation_type:
                continue
            if payload["sha256"] != digest:
                raise LearnError("validation source is not bound to the candidate")
            return
        raise LearnError("validation source is not bound to the candidate")

    def _bound_counterexample_source(self, candidate_id: int, counterexample_id: int) -> str:
        candidate = self.store.get_candidate(candidate_id)
        rows = self.store.list_counterexamples(candidate_id)
        row = next((item for item in rows if item["id"] == counterexample_id), None)
        if row is None:
            raise LearnError("counterexample does not belong to the candidate")
        statement = load_candidate_prop(candidate["canonical_ast_json"])
        expected = export_prop(false_proposition(statement, json.loads(row["assignment_json"])))
        if expected != row["instantiated_prop"]:
            raise LearnError("counterexample does not instantiate this candidate")
        return negation_source(expected, candidate["stable_id"])


def _same_outcomes(source, dest, run_id: str) -> bool:
    left = {row["stable_id"]: row["current_status"] for row in source.list_candidates(run_id)}
    right = {row["stable_id"]: row["current_status"] for row in dest.list_candidates(run_id)}
    return left == right
