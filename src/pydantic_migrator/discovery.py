"""Explicit module discovery helpers for the CLI."""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator

from .api import build_registry
from .registry import _MIGRATION_ATTR, MigrationDefinition, MigrationRegistry
from .versioning import VersionedModel


def build_registry_from_module(
    module_name: str,
    *,
    pythonpath: Iterable[str | Path] = (),
) -> MigrationRegistry:
    with _temporary_pythonpath(pythonpath):
        module = importlib.import_module(module_name)

    models, migrations = discover_module_items(module)
    return build_registry(*models, *migrations)


def discover_module_items(
    module: ModuleType,
) -> tuple[tuple[type[VersionedModel], ...], tuple[object, ...]]:
    models: list[type[VersionedModel]] = []
    migrations: list[object] = []

    for _, value in inspect.getmembers(module):
        if inspect.isclass(value) and issubclass(value, VersionedModel) and value is not VersionedModel:
            models.append(value)
            continue
        if isinstance(getattr(value, _MIGRATION_ATTR, None), MigrationDefinition):
            migrations.append(value)

    models.sort(
        key=lambda model_cls: (
            model_cls.schema_id().schema_name,
            model_cls.schema_id().version,
            model_cls.__module__,
            model_cls.__name__,
        )
    )
    migrations.sort(
        key=lambda migration: (
            getattr(migration, "__module__", ""),
            getattr(migration, "__name__", ""),
        )
    )
    return (tuple(models), tuple(migrations))


@contextmanager
def _temporary_pythonpath(paths: Iterable[str | Path]) -> Iterator[None]:
    additions = [str(Path(path)) for path in paths]
    for path in reversed(additions):
        sys.path.insert(0, path)
    try:
        yield
    finally:
        for path in additions:
            try:
                sys.path.remove(path)
            except ValueError:
                continue
