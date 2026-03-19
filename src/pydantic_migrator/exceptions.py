"""Exceptions used by pydantic-migrator."""


class PydanticMigratorError(Exception):
    """Base exception for the package."""


class InvalidVersionedModelError(PydanticMigratorError):
    """Raised when a versioned model is missing required metadata."""


class InvalidMigrationError(PydanticMigratorError):
    """Raised when migration definitions are invalid."""


class MigrationRuntimeError(PydanticMigratorError):
    """Raised when a migration transform fails runtime contract checks."""


class MigrationPlanningError(PydanticMigratorError):
    """Raised when a migration path cannot be planned."""


class UnimplementedMigrationError(PydanticMigratorError):
    """Raised when a planned migration exists but has no executable transform."""


class ScaffoldLayoutError(PydanticMigratorError):
    """Raised when a scaffolded schema family is incomplete or inconsistent."""
