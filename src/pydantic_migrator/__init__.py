"""Public API for pydantic-migrator."""

from .api import build_registry, migrate, plan_migration
from .exceptions import (
    InvalidMigrationError,
    MigrationRuntimeError,
    InvalidVersionedModelError,
    MigrationPlanningError,
    UnimplementedMigrationError,
)
from .generator import (
    GeneratedStub,
    generate_adjacent_migration_stub,
    generate_bidirectional_migration_stubs,
    generate_missing_adjacent_migration_stubs,
)
from .planner import MigrationPlan, MigrationPlanner
from .registry import MigrationDefinition, MigrationRegistry, MissingMigration, define_migration
from .versioning import SchemaVersion, VersionedModel, versioned_model
from .api import find_missing_adjacent_migrations

__all__ = [
    "GeneratedStub",
    "InvalidMigrationError",
    "MigrationRuntimeError",
    "InvalidVersionedModelError",
    "MigrationDefinition",
    "MigrationPlan",
    "MigrationPlanner",
    "MigrationPlanningError",
    "MigrationRegistry",
    "MissingMigration",
    "SchemaVersion",
    "UnimplementedMigrationError",
    "VersionedModel",
    "build_registry",
    "define_migration",
    "find_missing_adjacent_migrations",
    "generate_adjacent_migration_stub",
    "generate_bidirectional_migration_stubs",
    "generate_missing_adjacent_migration_stubs",
    "migrate",
    "plan_migration",
    "versioned_model",
]
