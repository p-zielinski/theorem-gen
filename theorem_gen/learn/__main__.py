"""CLI: start, pause, resume, status, replay."""

from __future__ import annotations

import argparse
import signal
import sqlite3
import sys
from pathlib import Path

from theorem_gen.learn.clock import Clock
from theorem_gen.learn.engine import Engine
from theorem_gen.learn.errors import LearnError
from theorem_gen.learn.memory import report as memory_report
from theorem_gen.learn.store import Store

_DEFAULT_DB = Path("var/learn.sqlite")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="theorem_gen.learn")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    _run_args(start)
    start.add_argument("--curriculum", type=int, default=1)
    start.add_argument("--seed", type=int, default=1)
    start.add_argument("--count", type=int, default=4)
    start.add_argument("--until-pause", action="store_true")

    pause = sub.add_parser("pause")
    _db_args(pause)

    resume = sub.add_parser("resume")
    _run_args(resume)
    resume.add_argument("--until-pause", action="store_true")

    status = sub.add_parser("status")
    _db_args(status)

    replay = sub.add_parser("replay")
    _db_args(replay)
    replay.add_argument("--from-checkpoint", type=int, required=True)

    sub.add_parser("memory")

    args = parser.parse_args(argv)
    try:
        if args.command == "memory":
            info = memory_report()
            _print_memory(info)
            return 0 if info["within_budget"] else 1
        store = Store(args.db, clock=Clock())
        if args.command == "start":
            return _start(store, args)
        if args.command == "pause":
            return _pause(store, args)
        if args.command == "resume":
            return _resume(store, args)
        if args.command == "status":
            return _status(store, args)
        if args.command == "replay":
            return _replay(store, args)
    except (LearnError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


def _run_args(parser) -> None:
    _db_args(parser)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--checkpoint-interval", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=60.0)


def _db_args(parser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)


def _start(store, args) -> int:
    max_steps = args.max_steps
    if not args.until_pause and max_steps is None:
        max_steps = 50
    engine = Engine(
        store,
        run_id=args.run_id,
        seed=args.seed,
        batch_count=args.count,
        curriculum=args.curriculum,
        max_steps=max_steps,
        checkpoint_interval_s=args.checkpoint_interval,
        lean_timeout_s=args.timeout,
        until_pause=args.until_pause,
        refill_when_idle=True,
    )
    with _signals(engine):
        engine.start()
    _print_status(engine.status())
    return 0


def _pause(store, args) -> int:
    store.migrate()
    engine = _engine_for_existing(store, args, max_steps=0)
    engine.pause()
    _print_status(engine.status())
    return 0


def _resume(store, args) -> int:
    store.migrate()
    run = store.get_run(args.run_id)
    if run is None:
        raise LearnError(f"unknown run {args.run_id}")
    import json

    max_steps, until_pause, refill = _resume_limits(args, json.loads(run["config_json"]))
    engine = _engine_for_existing(
        store,
        args,
        max_steps=max_steps,
        until_pause=until_pause,
        refill_when_idle=refill,
    )
    with _signals(engine):
        engine.resume()
        engine.run_steps(engine.max_steps)
        engine.finish()
    _print_status(engine.status())
    return 0


def _status(store, args) -> int:
    store.migrate()
    engine = _engine_for_existing(store, args, max_steps=0)
    _print_status(engine.status())
    return 0


def _replay(store, args) -> int:
    store.migrate()
    engine = _engine_for_existing(store, args, max_steps=0)
    if engine.store.get_checkpoint(args.run_id, args.from_checkpoint) is None:
        raise LearnError("checkpoint not found")
    dest_path = args.db.with_name(args.db.stem + "-replay" + args.db.suffix)
    if dest_path.exists():
        raise LearnError(f"replay database already exists: {dest_path}")
    dest = Store(dest_path, clock=store.clock)
    matched = engine.replay_into(dest, args.from_checkpoint)
    print(f"replay_match: {'yes' if matched else 'no'}")
    return 0 if matched else 1


def _resume_limits(args, config: dict) -> tuple:
    """Step budget for resume. A continuous run stays unbounded until a signal."""
    stored_until = bool(config.get("until_pause"))
    if args.until_pause or (stored_until and args.max_steps is None):
        return args.max_steps, True, True
    max_steps = 50 if args.max_steps is None else args.max_steps
    return max_steps, False, True


def _engine_for_existing(store, args, *, max_steps, until_pause: bool = False, refill_when_idle: bool = False) -> Engine:
    run = store.get_run(args.run_id)
    if run is None:
        raise LearnError(f"unknown run {args.run_id}")
    import json

    config = json.loads(run["config_json"])
    interval = getattr(args, "checkpoint_interval", config["checkpoint_interval_s"])
    timeout = getattr(args, "timeout", config["lean_timeout_s"])
    return Engine(
        store,
        run_id=args.run_id,
        seed=config["seed"],
        batch_count=config["batch_count"],
        curriculum=1,
        max_steps=max_steps,
        checkpoint_interval_s=interval,
        high_water=config["high_water"],
        lease_ttl_s=config["lease_ttl_s"],
        lean_timeout_s=timeout,
        until_pause=until_pause,
        refill_when_idle=refill_when_idle,
    )


class _signals:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.previous = []

    def __enter__(self):
        def handler(signum, frame):
            self.engine.request_pause()

        for number in (signal.SIGINT, signal.SIGTERM):
            self.previous.append((number, signal.signal(number, handler)))
        return self

    def __exit__(self, exc_type, exc, tb):
        for number, previous in self.previous:
            signal.signal(number, previous)
        return False


def _print_status(info: dict) -> None:
    print(f"status: {info['status']}")
    print(f"curriculum_level: {info['curriculum_level']}")
    print(f"event_cursor: {info['event_cursor']}")
    print(f"model_version: {info['model_version']}")
    parts = [
        f"{name}={info['queue'][name]['queued']}"
        for name in sorted(info["queue"])
    ]
    print("queue: " + ",".join(parts))
    print(f"checkpoint_seq: {info['checkpoint_seq']}")
    print(f"learning: {'yes' if info['learning'] else 'no'}")


def _print_memory(info: dict) -> None:
    print(f"peak_rss_bytes: {info['peak_rss_bytes']}")
    print(f"budget_bytes: {info['budget_bytes']}")
    print(f"within_budget: {'yes' if info['within_budget'] else 'no'}")
    print(f"weights_loaded: {'yes' if info['weights_loaded'] else 'no'}")
    print(f"resident_copies: {info['resident_copies']}")
    print(info["note"])


if __name__ == "__main__":
    sys.exit(main())
