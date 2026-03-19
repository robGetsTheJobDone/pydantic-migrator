"""Small explicit CLI for pydantic-migrator."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .api import find_missing_adjacent_migrations, plan_migration
from .discovery import build_registry_from_module
from .exceptions import PydanticMigratorError
from .generator import generate_missing_adjacent_migration_stubs
from .scaffold import bump_schema_family, create_schema_family, format_version_gap_messages


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pydantic-migrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create",
        help="Create an opinionated schema family scaffold",
    )
    create_parser.add_argument("schema", nargs="?", help="Schema family name")
    create_parser.add_argument("--schema", dest="schema_flag", help="Schema family name")
    create_parser.add_argument(
        "--path",
        "--output-dir",
        dest="output_dir",
        type=Path,
        help="Importable package directory that will contain the scaffolded family",
    )
    create_parser.add_argument("--overwrite", action="store_true")
    create_parser.set_defaults(handler=_run_create)

    bump_parser = subparsers.add_parser(
        "bump",
        help="Create the next model version and adjacent migration stubs",
    )
    _add_module_arguments(bump_parser)
    bump_parser.add_argument("--overwrite", action="store_true")
    bump_parser.add_argument(
        "--no-bidirectional",
        action="store_true",
        help="Only generate the forward adjacent migration stub.",
    )
    bump_parser.set_defaults(handler=_run_bump)

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
    generate_parser.add_argument(
        "--path",
        "--output-dir",
        required=True,
        type=Path,
        dest="output_dir",
        help="Directory where generated migration stubs will be written",
    )
    generate_parser.add_argument("--overwrite", action="store_true")
    generate_parser.add_argument(
        "--no-bidirectional",
        action="store_true",
        help="Only generate forward adjacent migrations.",
    )
    generate_parser.set_defaults(handler=_run_generate)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (FileExistsError, ImportError, ModuleNotFoundError, PydanticMigratorError) as exc:
        print(f"ERROR {exc}")
        return 1


def _add_module_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("module", nargs="?", help="Import path that defines the models/migrations")
    parser.add_argument(
        "--module",
        dest="module_flag",
        help="Import path that defines the models/migrations",
    )
    parser.add_argument(
        "--pythonpath",
        action="append",
        default=[],
        help="Extra path to add while importing the target module. Can be repeated.",
    )


def _run_check(args: argparse.Namespace) -> int:
    module_name = _resolve_required_cli_value(
        positional=args.module,
        flagged=args.module_flag,
        label="module",
        flag_name="--module",
    )
    registry = build_registry_from_module(module_name, pythonpath=args.pythonpath)
    schema_names = [args.schema] if args.schema else list(registry.schema_names())
    gap_messages = format_version_gap_messages(registry, schema_names)
    if gap_messages:
        for message in gap_messages:
            print(message)
        return 1

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
    module_name = _resolve_required_cli_value(
        positional=args.module,
        flagged=args.module_flag,
        label="module",
        flag_name="--module",
    )
    registry = build_registry_from_module(module_name, pythonpath=args.pythonpath)
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
    module_name = _resolve_required_cli_value(
        positional=args.module,
        flagged=args.module_flag,
        label="module",
        flag_name="--module",
    )
    registry = build_registry_from_module(module_name, pythonpath=args.pythonpath)
    gap_messages = format_version_gap_messages(registry, (args.schema,))
    if gap_messages:
        for message in gap_messages:
            print(message)
        return 1
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


def _run_create(args: argparse.Namespace) -> int:
    schema_name = _resolve_required_cli_value(
        positional=args.schema,
        flagged=args.schema_flag,
        label="schema",
        flag_name="--schema",
    )
    output_dir = _resolve_required_path(args.output_dir, flag_name="--path")
    created = create_schema_family(
        output_dir,
        schema_name=schema_name,
        overwrite=args.overwrite,
    )
    print(f"Created schema family scaffold at {created.package_dir}")
    print("Next steps:")
    print(f"  - Define your initial model fields in {created.package_dir / 'models' / 'v1.py'}")
    print(
        f"  - Import the package from your app and run "
        f"`pydantic-migrator bump <your.package.{created.package_name}> --pythonpath <path>` "
        f"for v2"
    )
    return 0


def _run_bump(args: argparse.Namespace) -> int:
    module_name = _resolve_required_cli_value(
        positional=args.module,
        flagged=args.module_flag,
        label="module",
        flag_name="--module",
    )
    bumped = bump_schema_family(
        module_name,
        pythonpath=args.pythonpath,
        overwrite=args.overwrite,
        bidirectional=not args.no_bidirectional,
    )
    print(f"Created {bumped.schema_name} v{bumped.next_version} at {bumped.model_path}")
    for migration_path in bumped.migration_paths:
        print(migration_path)
    print("Next steps:")
    print(f"  - Define the new model fields in {bumped.model_path}")
    print("  - Replace the generated migration stubs with domain-specific logic")
    return 0


def _resolve_required_cli_value(
    *,
    positional: str | None,
    flagged: str | None,
    label: str,
    flag_name: str,
) -> str:
    value = flagged or positional
    if not value:
        raise PydanticMigratorError(
            f"Missing required {label}. Provide it positionally or with {flag_name}."
        )
    if positional and flagged and positional != flagged:
        raise PydanticMigratorError(
            f"Conflicting {label} values: positional {positional!r} does not match "
            f"{flag_name} {flagged!r}"
        )
    return value


def _resolve_required_path(path: Path | None, *, flag_name: str) -> Path:
    if path is None:
        raise PydanticMigratorError(f"Missing required path. Provide it with {flag_name}.")
    return path
