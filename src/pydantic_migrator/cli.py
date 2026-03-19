"""Small explicit CLI for pydantic-migrator."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .api import find_missing_adjacent_migrations, plan_migration
from .discovery import build_registry_from_module
from .generator import generate_missing_adjacent_migration_stubs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pydantic-migrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Check for missing adjacent migrations")
    _add_module_arguments(check_parser)
    check_parser.add_argument("--schema", help="Schema family to check. Defaults to all loaded families.")
    check_parser.add_argument(
        "--no-bidirectional",
        action="store_true",
        help="Only require forward adjacent migrations.",
    )
    check_parser.set_defaults(handler=_run_check)

    plan_parser = subparsers.add_parser("plan", help="Plan a migration path")
    _add_module_arguments(plan_parser)
    plan_parser.add_argument("--schema", required=True, help="Schema family to plan")
    plan_parser.add_argument("--from-version", required=True, type=int, dest="from_version")
    plan_parser.add_argument("--to-version", required=True, type=int, dest="to_version")
    plan_parser.set_defaults(handler=_run_plan)

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate stubs for missing adjacent migrations",
    )
    _add_module_arguments(generate_parser)
    generate_parser.add_argument("--schema", required=True, help="Schema family to generate")
    generate_parser.add_argument("--output-dir", required=True, type=Path, dest="output_dir")
    generate_parser.add_argument("--overwrite", action="store_true")
    generate_parser.add_argument(
        "--no-bidirectional",
        action="store_true",
        help="Only generate forward adjacent migrations.",
    )
    generate_parser.set_defaults(handler=_run_generate)

    args = parser.parse_args(argv)
    return args.handler(args)


def _add_module_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--module", required=True, help="Import path that defines the models/migrations")
    parser.add_argument(
        "--pythonpath",
        action="append",
        default=[],
        help="Extra path to add while importing the target module. Can be repeated.",
    )


def _run_check(args: argparse.Namespace) -> int:
    registry = build_registry_from_module(args.module, pythonpath=args.pythonpath)
    schema_names = [args.schema] if args.schema else list(registry.schema_names())

    require_bidirectional = not args.no_bidirectional
    all_missing = []
    for schema_name in schema_names:
        missing = find_missing_adjacent_migrations(
            registry,
            schema_name=schema_name,
            require_bidirectional=require_bidirectional,
        )
        all_missing.extend(missing)

    if not all_missing:
        scope = args.schema or ", ".join(schema_names) or "(no schemas found)"
        direction = "bidirectional" if require_bidirectional else "forward-only"
        print(f"OK {scope}: no missing adjacent migrations ({direction})")
        return 0

    for missing in all_missing:
        print(f"MISSING {missing.schema_name} v{missing.from_version} -> v{missing.to_version}")
    return 1


def _run_plan(args: argparse.Namespace) -> int:
    registry = build_registry_from_module(args.module, pythonpath=args.pythonpath)
    plan = plan_migration(
        registry,
        schema_name=args.schema,
        start_version=args.from_version,
        target_version=args.to_version,
    )
    versions = [str(plan.start_version), *(str(step.to_version) for step in plan.steps)]
    print(f"{plan.schema_name}: v" + " -> v".join(versions))
    return 0


def _run_generate(args: argparse.Namespace) -> int:
    registry = build_registry_from_module(args.module, pythonpath=args.pythonpath)
    generated = generate_missing_adjacent_migration_stubs(
        args.output_dir,
        registry=registry,
        schema_name=args.schema,
        overwrite=args.overwrite,
        require_bidirectional=not args.no_bidirectional,
    )
    if not generated:
        print(f"No missing adjacent migrations for {args.schema}")
        return 0

    for stub in generated:
        print(stub.path)
    return 0
