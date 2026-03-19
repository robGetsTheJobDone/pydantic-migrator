"""Opinionated scaffold helpers for the CLI."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .api import build_registry
from .discovery import discover_module_items, import_module_with_pythonpath
from .exceptions import ScaffoldLayoutError
from .generator import (
    generate_adjacent_migration_stub,
    generate_bidirectional_migration_stubs,
)
from .registry import MigrationRegistry
from .versioning import VersionedModel

_MANAGED_BEGIN = "# BEGIN pydantic-migrator managed exports"
_MANAGED_END = "# END pydantic-migrator managed exports"


@dataclass(frozen=True, slots=True)
class CreatedFamily:
    schema_name: str
    package_name: str
    package_dir: Path
    created_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class ScaffoldedFamily:
    module_name: str
    schema_name: str
    package_dir: Path
    models_dir: Path
    migrations_dir: Path
    class_stem: str
    versions: tuple[int, ...]
    latest_model: type[VersionedModel]


@dataclass(frozen=True, slots=True)
class BumpedFamily:
    module_name: str
    schema_name: str
    next_version: int
    model_path: Path
    migration_paths: tuple[Path, ...]


def create_schema_family(
    output_dir: str | Path,
    *,
    schema_name: str,
    overwrite: bool = False,
) -> CreatedFamily:
    root_dir = Path(output_dir)
    _validate_scaffold_root(root_dir)
    package_name = package_name_for_schema(schema_name)
    class_stem = class_name_for_schema(schema_name)
    package_dir = root_dir / package_name
    models_dir = package_dir / "models"
    migrations_dir = package_dir / "migrations"
    tests_dir = package_dir / "tests"

    if package_dir.exists() and any(package_dir.iterdir()) and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing schema family scaffold: {package_dir}"
        )

    package_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    files_to_write = {
        package_dir / "__init__.py": _render_package_init(),
        package_dir / "registry.py": _render_registry_module(),
        models_dir / "__init__.py": _render_models_init(class_stem=class_stem, versions=(1,)),
        models_dir / "v1.py": _render_model_module(
            schema_name=schema_name,
            class_stem=class_stem,
            version=1,
        ),
        migrations_dir / "__init__.py": _render_migrations_init(schema_name=schema_name, edges=()),
        tests_dir / "__init__.py": '"""Tests for this schema family."""\n',
        tests_dir / f"test_{package_name}_migrations.py": _render_scaffold_test_module(
            schema_name=schema_name,
            class_stem=class_stem,
        ),
    }
    for file_path in files_to_write:
        if file_path.exists() and not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing scaffold file: {file_path}")
    for file_path, content in files_to_write.items():
        file_path.write_text(content, encoding="utf-8")

    return CreatedFamily(
        schema_name=schema_name,
        package_name=package_name,
        package_dir=package_dir,
        created_paths=(
            package_dir,
            models_dir,
            migrations_dir,
            tests_dir,
            package_dir / "__init__.py",
            package_dir / "registry.py",
            models_dir / "__init__.py",
            models_dir / "v1.py",
            migrations_dir / "__init__.py",
            tests_dir / "__init__.py",
            tests_dir / f"test_{package_name}_migrations.py",
        ),
    )


def load_scaffolded_family(
    module_name: str,
    *,
    pythonpath: Iterable[str | Path] = (),
) -> ScaffoldedFamily:
    try:
        module = import_module_with_pythonpath(module_name, pythonpath=pythonpath, reload=True)
    except (ImportError, ModuleNotFoundError) as exc:
        raise ScaffoldLayoutError(
            f"Could not import scaffolded schema family {module_name!r}. "
            "Ensure the package path is importable and pass --pythonpath to the directory "
            "that contains its top-level package. "
            f"Original error: {exc}"
        ) from exc
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        raise ScaffoldLayoutError(f"Module {module_name!r} does not have a filesystem path")

    package_init = Path(module_file)
    if package_init.name != "__init__.py":
        raise ScaffoldLayoutError(
            f"Module {module_name!r} is not a scaffolded schema family package"
        )

    package_dir = package_init.parent
    models_dir = package_dir / "models"
    migrations_dir = package_dir / "migrations"
    _validate_scaffold_family_layout(
        module_name,
        package_dir=package_dir,
        models_dir=models_dir,
        migrations_dir=migrations_dir,
    )

    models, migrations = discover_module_items(module)
    registry = build_registry(*models, *migrations)
    schema_names = registry.schema_names()
    if len(schema_names) != 1:
        found = ", ".join(schema_names) or "(none)"
        raise ScaffoldLayoutError(
            f"Module {module_name!r} must expose exactly one schema family, found: {found}"
        )

    schema_name = schema_names[0]
    models = registry.iter_models(schema_name)
    if not models:
        raise ScaffoldLayoutError(f"Module {module_name!r} does not expose any versioned models")

    versions = tuple(model.schema_id().version for model in models)
    gap_messages = format_version_gap_messages(registry, (schema_name,))
    if gap_messages:
        raise ScaffoldLayoutError(gap_messages[0])

    latest_model = models[-1]
    class_stem = class_name_stem(latest_model, schema_name=schema_name)

    return ScaffoldedFamily(
        module_name=module_name,
        schema_name=schema_name,
        package_dir=package_dir,
        models_dir=models_dir,
        migrations_dir=migrations_dir,
        class_stem=class_stem,
        versions=versions,
        latest_model=latest_model,
    )


def bump_schema_family(
    module_name: str,
    *,
    pythonpath: Iterable[str | Path] = (),
    overwrite: bool = False,
    bidirectional: bool = True,
) -> BumpedFamily:
    family = load_scaffolded_family(module_name, pythonpath=pythonpath)
    next_version = family.versions[-1] + 1
    model_path = family.models_dir / f"v{next_version}.py"
    if model_path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing model file: {model_path}")

    model_path.write_text(
        _render_model_module(
            schema_name=family.schema_name,
            class_stem=family.class_stem,
            version=next_version,
        ),
        encoding="utf-8",
    )
    _rewrite_managed_exports(
        family.models_dir / "__init__.py",
        _render_models_exports(
            class_stem=family.class_stem,
            versions=(*family.versions, next_version),
        ),
    )

    new_model_module = import_module_with_pythonpath(
        f"{module_name}.models.v{next_version}",
        pythonpath=pythonpath,
        reload=True,
    )
    new_model_name = f"{family.class_stem}V{next_version}"
    new_model = getattr(new_model_module, new_model_name, None)
    if not isinstance(new_model, type) or not issubclass(new_model, VersionedModel):
        raise ScaffoldLayoutError(
            f"Generated model module {module_name}.models.v{next_version} did not expose {new_model_name}"
        )

    if bidirectional:
        generated_stubs = generate_bidirectional_migration_stubs(
            family.migrations_dir,
            older_model=family.latest_model,
            newer_model=new_model,
            overwrite=overwrite,
        )
    else:
        generated_stubs = (
            generate_adjacent_migration_stub(
                family.migrations_dir,
                from_model=family.latest_model,
                to_model=new_model,
                overwrite=overwrite,
            ),
        )

    _rewrite_managed_exports(
        family.migrations_dir / "__init__.py",
        _render_migrations_exports(
            schema_name=family.schema_name,
            edges=_collect_migration_edges(family.migrations_dir, family.schema_name),
        ),
    )

    return BumpedFamily(
        module_name=module_name,
        schema_name=family.schema_name,
        next_version=next_version,
        model_path=model_path,
        migration_paths=tuple(stub.path for stub in generated_stubs),
    )


def format_version_gap_messages(
    registry: MigrationRegistry,
    schema_names: Iterable[str],
) -> tuple[str, ...]:
    messages: list[str] = []
    for schema_name in schema_names:
        versions = [model.schema_id().version for model in registry.iter_models(schema_name)]
        gaps = find_version_gaps(versions)
        if not gaps:
            continue
        gap_descriptions = ", ".join(_format_gap(prev, current) for prev, current in gaps)
        messages.append(f"GAP {schema_name}: {gap_descriptions}")
    return tuple(messages)


def find_version_gaps(versions: Iterable[int]) -> tuple[tuple[int, int], ...]:
    ordered_versions = tuple(sorted(set(versions)))
    gaps: list[tuple[int, int]] = []
    for index in range(1, len(ordered_versions)):
        previous_version = ordered_versions[index - 1]
        current_version = ordered_versions[index]
        if current_version - previous_version > 1:
            gaps.append((previous_version, current_version))
    return tuple(gaps)


def package_name_for_schema(schema_name: str) -> str:
    return _python_identifier(schema_name, default_prefix="schema")


def class_name_for_schema(schema_name: str) -> str:
    candidate = "".join(part.capitalize() for part in re.findall(r"[A-Za-z0-9]+", schema_name))
    if not candidate:
        return "Schema"
    if candidate[0].isdigit():
        return f"Schema{candidate}"
    return candidate


def class_name_stem(model_cls: type[VersionedModel], *, schema_name: str) -> str:
    match = re.match(r"^(?P<stem>.+)V\d+$", model_cls.__name__)
    if match is not None:
        return match.group("stem")
    return class_name_for_schema(schema_name)


def _render_package_init() -> str:
    return '''"""Scaffolded schema family package."""

from . import migrations as _migrations
from . import models as _models
from .registry import registry
from .models import *
from .migrations import *

__all__ = ["registry", *getattr(_models, "__all__", ()), *getattr(_migrations, "__all__", ())]
'''


def _render_registry_module() -> str:
    return '''"""Registry for this schema family."""

from __future__ import annotations

from pydantic_migrator import build_registry

from . import migrations, models

registry = build_registry(
    *(getattr(models, name) for name in getattr(models, "__all__", ())),
    *(getattr(migrations, name) for name in getattr(migrations, "__all__", ())),
)

__all__ = ["registry"]
'''


def _render_models_init(*, class_stem: str, versions: tuple[int, ...]) -> str:
    return _render_init_module(
        docstring="Versioned models for this schema family.",
        exports=_render_models_exports(class_stem=class_stem, versions=versions),
    )


def _render_migrations_init(
    *,
    schema_name: str,
    edges: tuple[tuple[int, int], ...],
) -> str:
    return _render_init_module(
        docstring="Adjacent migrations for this schema family.",
        exports=_render_migrations_exports(schema_name=schema_name, edges=edges),
    )


def _render_init_module(*, docstring: str, exports: str) -> str:
    return f'''"""{docstring}"""

{_MANAGED_BEGIN}
{exports}
{_MANAGED_END}
'''


def _render_models_exports(*, class_stem: str, versions: tuple[int, ...]) -> str:
    import_lines = [f"from .v{version} import {class_stem}V{version}" for version in versions]
    all_entries = [f'    "{class_stem}V{version}",' for version in versions]
    return "\n".join(
        [
            *import_lines,
            "",
            "__all__ = [",
            *all_entries,
            "]",
        ]
    )


def _render_migrations_exports(
    *,
    schema_name: str,
    edges: tuple[tuple[int, int], ...],
) -> str:
    slug = _slugify(schema_name)
    if not edges:
        return "__all__ = []"

    import_lines = [
        f"from .{slug}_v{from_version}_to_v{to_version} import "
        f"migrate_{slug}_v{from_version}_to_v{to_version}"
        for from_version, to_version in edges
    ]
    all_entries = [
        f'    "migrate_{slug}_v{from_version}_to_v{to_version}",'
        for from_version, to_version in edges
    ]
    return "\n".join(
        [
            *import_lines,
            "",
            "__all__ = [",
            *all_entries,
            "]",
        ]
    )


def _render_model_module(*, schema_name: str, class_stem: str, version: int) -> str:
    class_name = f"{class_stem}V{version}"
    return f'''"""Schema model {schema_name} v{version}."""

from __future__ import annotations

from pydantic_migrator import VersionedModel, versioned_model


@versioned_model("{schema_name}", {version})
class {class_name}(VersionedModel):
    """TODO: define the fields for {schema_name} v{version}."""

    pass
'''


def _render_scaffold_test_module(*, schema_name: str, class_stem: str) -> str:
    return f'''"""Smoke tests for the {schema_name} schema family."""

from __future__ import annotations

from ..models import {class_stem}V1
from ..registry import registry


def test_{_slugify(schema_name)}_v1_is_registered() -> None:
    assert registry.get_model("{schema_name}", 1) is {class_stem}V1
'''


def _rewrite_managed_exports(file_path: Path, exports: str) -> None:
    existing = file_path.read_text(encoding="utf-8")
    lines = existing.splitlines(keepends=True)
    begin_indexes = [
        index for index, line in enumerate(lines) if line.rstrip("\r\n") == _MANAGED_BEGIN
    ]
    end_indexes = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == _MANAGED_END]
    if len(begin_indexes) != 1 or len(end_indexes) != 1:
        raise ScaffoldLayoutError(
            f"Managed export block in {file_path} must contain exactly one begin marker "
            "and one end marker on their own lines"
        )

    begin_index = begin_indexes[0]
    end_index = end_indexes[0]
    if end_index <= begin_index:
        raise ScaffoldLayoutError(
            f"Managed export block in {file_path} has the end marker before the begin marker"
        )

    newline = "\r\n" if lines[begin_index].endswith("\r\n") else "\n"
    export_lines = [f"{line}{newline}" for line in exports.rstrip("\n").split("\n")]
    updated = "".join(
        [
            *lines[:begin_index],
            lines[begin_index],
            *export_lines,
            lines[end_index],
            *lines[end_index + 1 :],
        ]
    )
    file_path.write_text(updated, encoding="utf-8")


def _collect_migration_edges(migrations_dir: Path, schema_name: str) -> tuple[tuple[int, int], ...]:
    slug = _slugify(schema_name)
    pattern = re.compile(rf"^{re.escape(slug)}_v(?P<from_version>\d+)_to_v(?P<to_version>\d+)\.py$")
    edges: list[tuple[int, int]] = []
    for file_path in sorted(migrations_dir.glob("*.py")):
        if file_path.name == "__init__.py":
            continue
        match = pattern.match(file_path.name)
        if match is None:
            continue
        edges.append((int(match.group("from_version")), int(match.group("to_version"))))
    edges.sort()
    return tuple(edges)


def _format_gap(previous_version: int, current_version: int) -> str:
    missing_versions = tuple(range(previous_version + 1, current_version))
    rendered_missing = ", ".join(f"v{version}" for version in missing_versions)
    label = "version" if len(missing_versions) == 1 else "versions"
    return (
        f"missing model {label} {rendered_missing} "
        f"between v{previous_version} and v{current_version}"
    )


def _python_identifier(value: str, *, default_prefix: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    if not normalized:
        normalized = default_prefix
    if normalized[0].isdigit():
        normalized = f"{default_prefix}_{normalized}"
    return normalized.lower()


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _validate_scaffold_root(root_dir: Path) -> None:
    package_init = root_dir / "__init__.py"
    if not root_dir.exists() or not root_dir.is_dir() or not package_init.is_file():
        raise ScaffoldLayoutError(
            f"Scaffold path {root_dir} must already be an importable package directory with "
            f"{package_init}. Pass --path to a package like src/myapp/schemas and then use "
            "--pythonpath src when running bump."
        )


def _validate_scaffold_family_layout(
    module_name: str,
    *,
    package_dir: Path,
    models_dir: Path,
    migrations_dir: Path,
) -> None:
    missing_paths = [
        path
        for path in (
            package_dir / "__init__.py",
            models_dir,
            models_dir / "__init__.py",
            migrations_dir,
            migrations_dir / "__init__.py",
        )
        if not path.exists()
    ]
    if not missing_paths:
        return

    missing = ", ".join(str(path) for path in missing_paths)
    raise ScaffoldLayoutError(
        f"Module {module_name!r} is not a complete scaffolded schema family. "
        f"Missing required paths: {missing}"
    )
