"""Convenience helpers for the public API."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Callable, TypeAlias

from .planner import MigrationPlan, MigrationPlanner
from .registry import MigrationDefinition, MigrationRegistry, MissingMigration
from .versioning import VersionedModel

RegistryItem: TypeAlias = type[VersionedModel] | MigrationDefinition | Callable[..., object]


def build_registry(
    *items: RegistryItem,
    models: Iterable[type[VersionedModel]] = (),
    migrations: Iterable[MigrationDefinition | Callable[..., object]] = (),
) -> MigrationRegistry:
    registry = MigrationRegistry()
    registry.register(*tuple(items), *tuple(models))
    for migration in migrations:
        registry.register(migration)
    return registry


def plan_migration(
    registry: MigrationRegistry,
    *,
    schema_name: str,
    start_version: int,
    target_version: int,
) -> MigrationPlan:
    return MigrationPlanner(registry).plan(schema_name, start_version, target_version)


def migrate(model: VersionedModel, *, target_version: int, registry: MigrationRegistry):
    schema_id = model.__class__.schema_id()
    plan = plan_migration(
        registry,
        schema_name=schema_id.schema_name,
        start_version=schema_id.version,
        target_version=target_version,
    )
    return plan.apply(model)


def find_missing_adjacent_migrations(
    registry: MigrationRegistry,
    *,
    schema_name: str,
    require_bidirectional: bool = True,
) -> tuple[MissingMigration, ...]:
    return registry.missing_adjacent_migrations(
        schema_name,
        require_bidirectional=require_bidirectional,
    )
