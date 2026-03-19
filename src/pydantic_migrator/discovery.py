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
    module = import_module_with_pythonpath(module_name, pythonpath=pythonpath, reload=True)

    models, migrations = discover_module_items(module)
    return build_registry(*models, *migrations)


def import_module_with_pythonpath(
    module_name: str,
    *,
    pythonpath: Iterable[str | Path] = (),
    reload: bool = False,
) -> ModuleType:
    normalized_pythonpath = _normalize_pythonpath(pythonpath)
    with _temporary_pythonpath(normalized_pythonpath):
        importlib.invalidate_caches()
        try:
            if reload:
                _clear_module_cache(module_name)
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name or module_name.startswith(f"{exc.name}."):
                searched = ", ".join(str(path) for path in normalized_pythonpath) or "(none)"
                raise ModuleNotFoundError(
                    f"Could not import {module_name!r}. Searched with pythonpath {searched}. "
                    "Pass --pythonpath to the directory that contains the top-level package."
                ) from exc
            raise


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


def _clear_module_cache(module_name: str) -> None:
    module_prefix = f"{module_name}."
    for loaded_module_name in tuple(sys.modules):
        if loaded_module_name == module_name or loaded_module_name.startswith(module_prefix):
            sys.modules.pop(loaded_module_name, None)


def _normalize_pythonpath(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    normalized = tuple(Path(path) for path in paths)
    missing = [path for path in normalized if not path.exists()]
    if missing:
        missing_paths = ", ".join(str(path) for path in missing)
        raise ImportError(f"--pythonpath contains paths that do not exist: {missing_paths}")
    return normalized
