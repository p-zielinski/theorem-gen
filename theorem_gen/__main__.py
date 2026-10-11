"""Command line for the stage-1 generator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from theorem_gen.config import GeneratorConfig
from theorem_gen.errors import ExportError, GenerationError
from theorem_gen.export_lean import export_module
from theorem_gen.generate import generate
from theorem_gen.verify import exit_code_for, verify_source


def main(argv=None, verify_path=None) -> int:
    parser = argparse.ArgumentParser(prog="theorem_gen")
    sub = parser.add_subparsers(dest="command", required=True)
    generate_parser = sub.add_parser("generate")
    generate_parser.add_argument("--seed", type=int, required=True)
    generate_parser.add_argument("--count", type=int, required=True)
    generate_parser.add_argument("--out", type=Path, required=True)
    generate_parser.add_argument("--max-literal", type=int, default=9)
    generate_parser.add_argument("--max-depth", type=int, default=2)
    generate_parser.add_argument("--max-value", type=int, default=10000)
    generate_parser.add_argument("--max-attempts", type=int, default=None)
    generate_parser.add_argument("--rules", default=None)
    generate_parser.add_argument("--allow-duplicates", action="store_true")
    generate_parser.add_argument("--verify", action="store_true")
    generate_parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    return _generate(args, verify_path)


def _generate(args, verify_path) -> int:
    rules = None if args.rules is None else tuple(args.rules.split(","))
    try:
        config = GeneratorConfig(
            seed=args.seed,
            count=args.count,
            max_literal=args.max_literal,
            max_depth=args.max_depth,
            max_value=args.max_value,
            unique=not args.allow_duplicates,
            rules=rules,
            max_attempts=args.max_attempts,
        )
        theorems = generate(config)
        source = export_module(theorems, config)
    except (GenerationError, ExportError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(source, encoding="utf-8")
    print(f"generated {len(theorems)} theorems")
    print(f"wrote {args.out}")
    if not args.verify:
        return 0
    if verify_path is None:
        project_dir = Path(__file__).resolve().parents[1] / "lean"
        report = verify_source(
            source,
            destination=args.out,
            project_dir=project_dir,
            timeout_s=args.timeout,
        )
    else:
        report = verify_path(args.out, args.timeout)
    print(f"verification: {report.status}")
    print(report.message)
    return exit_code_for(report)


if __name__ == "__main__":
    sys.exit(main())
