"""Model and migration registry."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from typing import Any, Callable, TypeAlias, cast, get_type_hints

from pydantic import BaseModel

from .exceptions import InvalidMigrationError, MigrationRuntimeError, UnimplementedMigrationError
from .versioning import SchemaVersion, VersionedModel

MigrationTransform: TypeAlias = Callable[[BaseModel], BaseModel]
_MIGRATION_ATTR = "__pydantic_migrator_definition__"


@dataclass(frozen=True, slots=True)
class MigrationDefinition:
    """Adjacent migration between two schema versions."""

    schema_name: str
    from_version: int
    to_version: int
    from_model: type[VersionedModel] | None = None
    to_model: type[VersionedModel] | None = None
    transform: MigrationTransform | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if not self.schema_name:
            raise InvalidMigrationError("schema_name must be provided")
        if self.from_version < 1 or self.to_version < 1:
            raise InvalidMigrationError("migration versions must be >= 1")
        if self.from_version == self.to_version:
            raise InvalidMigrationError("from_version and to_version must differ")
        if abs(self.from_version - self.to_version) != 1:
            raise InvalidMigrationError("only adjacent migrations can be registered")
        if self.from_model is not None:
            from_schema = self.from_model.schema_id()
            if from_schema != self.from_schema:
                raise InvalidMigrationError(
                    "from_model metadata does not match the declared migration edge"
                )
        if self.to_model is not None:
            to_schema = self.to_model.schema_id()
            if to_schema != self.to_schema:
                raise InvalidMigrationError(
                    "to_model metadata does not match the declared migration edge"
                )
        if self.from_model is not None and self.to_model is not None:
            if self.from_model.schema_id().schema_name != self.to_model.schema_id().schema_name:
                raise InvalidMigrationError(
                    "migration models must belong to the same schema family"
                )

    @property
    def from_schema(self) -> SchemaVersion:
        return SchemaVersion(self.schema_name, self.from_version)

    @property
    def to_schema(self) -> SchemaVersion:
        return SchemaVersion(self.schema_name, self.to_version)

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.schema_name, self.from_version, self.to_version)

    def apply(self, model: BaseModel) -> BaseModel:
        if self.transform is None:
            raise UnimplementedMigrationError(
                f"Migration {self.schema_name} v{self.from_version} -> v{self.to_version} "
                "has no transform implementation"
            )
        if self.from_model is not None and not isinstance(model, self.from_model):
            raise MigrationRuntimeError(
                f"Migration {self.schema_name} v{self.from_version} -> v{self.to_version} "
                f"expected {self.from_model.__name__}, got {model.__class__.__name__}"
            )

        result = self.transform(model)
        if not isinstance(result, BaseModel):
            raise MigrationRuntimeError(
                f"Migration {self.schema_name} v{self.from_version} -> v{self.to_version} "
                f"returned {type(result).__name__}, expected a Pydantic model"
            )
        if self.to_model is not None and not isinstance(result, self.to_model):
            raise MigrationRuntimeError(
                f"Migration {self.schema_name} v{self.from_version} -> v{self.to_version} "
                f"returned {result.__class__.__name__}, expected {self.to_model.__name__}"
            )
        return result


@dataclass(frozen=True, slots=True)
class MissingMigration:
    """Adjacent migration edge that is missing for a schema family."""

    schema_name: str
    from_version: int
    to_version: int
    from_model: type[VersionedModel]
    to_model: type[VersionedModel]

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.schema_name, self.from_version, self.to_version)


def define_migration(
    *,
    schema_name: str | None = None,
    from_version: int | None = None,
    to_version: int | None = None,
    from_model: type[VersionedModel] | None = None,
    to_model: type[VersionedModel] | None = None,
) -> Callable[[MigrationTransform], MigrationTransform]:
    """Attach migration metadata to a transform function."""

    base_definition = _build_migration_definition(
        schema_name=schema_name,
        from_version=from_version,
        to_version=to_version,
        from_model=from_model,
        to_model=to_model,
    )

    def decorator(func: MigrationTransform) -> MigrationTransform:
        definition = _bind_transform_to_definition(base_definition, func)
        setattr(func, _MIGRATION_ATTR, definition)
        return func

    return decorator


def _build_migration_definition(
    *,
    schema_name: str | None,
    from_version: int | None,
    to_version: int | None,
    from_model: type[VersionedModel] | None,
    to_model: type[VersionedModel] | None,
) -> MigrationDefinition:
    has_model_pair = from_model is not None or to_model is not None
    has_explicit_versions = (
        schema_name is not None or from_version is not None or to_version is not None
    )

    if has_model_pair and has_explicit_versions:
        raise InvalidMigrationError(
            "Use either from_model/to_model or schema_name/from_version/to_version, not both"
        )

    if has_model_pair:
        if from_model is None or to_model is None:
            raise InvalidMigrationError("from_model and to_model must be provided together")

        from_schema = from_model.schema_id()
        to_schema = to_model.schema_id()
        if from_schema.schema_name != to_schema.schema_name:
            raise InvalidMigrationError("migration models must belong to the same schema family")

        return MigrationDefinition(
            schema_name=from_schema.schema_name,
            from_version=from_schema.version,
            to_version=to_schema.version,
            from_model=from_model,
            to_model=to_model,
        )

    if schema_name is None or from_version is None or to_version is None:
        raise InvalidMigrationError(
            "Provide either from_model/to_model or schema_name/from_version/to_version"
        )

    return MigrationDefinition(
        schema_name=schema_name,
        from_version=from_version,
        to_version=to_version,
    )


def _inspect_transform_annotations(
    func: MigrationTransform,
) -> tuple[type[VersionedModel] | None, type[VersionedModel] | None]:
    signature = inspect.signature(func)
    parameters = tuple(signature.parameters.values())
    if len(parameters) != 1:
        raise InvalidMigrationError(
            "migration transform must accept exactly one model argument"
        )

    parameter = parameters[0]
    if parameter.kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        raise InvalidMigrationError(
            "migration transform must accept a positional model argument"
        )

    try:
        hints = get_type_hints(func, globalns=func.__globals__, localns=None)
    except (NameError, TypeError) as exc:
        raise InvalidMigrationError(
            f"Could not resolve type annotations for {func.__module__}.{func.__name__}"
        ) from exc

    source_model = _extract_versioned_model_annotation(
        hints.get(parameter.name, signature.parameters[parameter.name].annotation),
        role="source",
    )
    target_model = _extract_versioned_model_annotation(
        hints.get("return", signature.return_annotation),
        role="target",
    )
    return (source_model, target_model)


def _extract_versioned_model_annotation(
    annotation: object,
    *,
    role: str,
) -> type[VersionedModel] | None:
    if annotation is inspect.Signature.empty:
        return None
    if isinstance(annotation, type) and issubclass(annotation, VersionedModel):
        return annotation
    raise InvalidMigrationError(
        f"{role} annotation must be a VersionedModel subclass when provided"
    )


def _resolve_transform_model(
    *,
    role: str,
    definition: MigrationDefinition,
    declared_model: type[VersionedModel] | None,
    annotated_model: type[VersionedModel] | None,
) -> type[VersionedModel] | None:
    expected_schema = definition.from_schema if role == "source" else definition.to_schema
    model = declared_model or annotated_model
    if annotated_model is not None:
        if declared_model is not None and annotated_model is not declared_model:
            raise InvalidMigrationError(
                f"{role} annotation does not match the declared migration model"
            )
        if annotated_model.schema_id() != expected_schema:
            raise InvalidMigrationError(
                f"{role} annotation metadata does not match the declared migration edge"
            )
    if model is not None and model.schema_id() != expected_schema:
        raise InvalidMigrationError(
            f"{role} model metadata does not match the declared migration edge"
        )
    return model


def _bind_transform_to_definition(
    definition: MigrationDefinition,
    transform: MigrationTransform,
    *,
    source: str | None = None,
) -> MigrationDefinition:
    annotated_from_model, annotated_to_model = _inspect_transform_annotations(transform)
    resolved_from_model = _resolve_transform_model(
        role="source",
        definition=definition,
        declared_model=definition.from_model,
        annotated_model=annotated_from_model,
    )
    resolved_to_model = _resolve_transform_model(
        role="target",
        definition=definition,
        declared_model=definition.to_model,
        annotated_model=annotated_to_model,
    )
    return replace(
        definition,
        from_model=resolved_from_model,
        to_model=resolved_to_model,
        transform=transform,
        source=source or _source_from_transform(transform),
    )


class MigrationRegistry:
    """In-memory registry for versioned models and adjacent migrations."""

    def __init__(self) -> None:
        self._models: dict[SchemaVersion, type[VersionedModel]] = {}
        self._migrations: dict[tuple[str, int, int], MigrationDefinition] = {}

    def register(self, *entries: object) -> "MigrationRegistry":
        models: list[type[VersionedModel]] = []
        non_models: list[object] = []
        for entry in entries:
            if isinstance(entry, type) and issubclass(entry, VersionedModel):
                models.append(entry)
                continue

            if isinstance(entry, MigrationDefinition) or callable(entry):
                non_models.append(entry)
                continue

            raise InvalidMigrationError(f"Unsupported registry entry: {entry!r}")

        for model_cls in models:
            self.register_model(model_cls)

        for entry in non_models:
            if isinstance(entry, MigrationDefinition):
                self.register_migration(entry)
                continue
            if callable(entry):
                self.register_migration_function(entry)
                continue

        return self

    def register_model(self, model_cls: type[VersionedModel]) -> type[VersionedModel]:
        schema_id = model_cls.schema_id()
        existing = self._models.get(schema_id)
        if existing is not None and existing is not model_cls:
            raise InvalidMigrationError(f"Duplicate model registration for {schema_id}")
        self._models[schema_id] = model_cls
        self._refresh_migration_models(schema_id.schema_name, schema_id.version)
        return model_cls

    def register_models(
        self, *model_classes: type[VersionedModel]
    ) -> tuple[type[VersionedModel], ...]:
        for model_cls in model_classes:
            self.register_model(model_cls)
        return model_classes

    def get_model(self, schema_name: str, version: int) -> type[VersionedModel] | None:
        return self._models.get(SchemaVersion(schema_name, version))

    def register_migration(
        self,
        definition: MigrationDefinition | None = None,
        *,
        schema_name: str | None = None,
        from_version: int | None = None,
        to_version: int | None = None,
        from_model: type[VersionedModel] | None = None,
        to_model: type[VersionedModel] | None = None,
        transform: MigrationTransform | None = None,
        source: str | None = None,
    ) -> MigrationDefinition:
        if definition is None:
            definition = _build_migration_definition(
                schema_name=schema_name,
                from_version=from_version,
                to_version=to_version,
                from_model=from_model,
                to_model=to_model,
            )
            if transform is not None:
                definition = _bind_transform_to_definition(definition, transform, source=source)
            else:
                definition = replace(definition, source=source)
        elif transform is not None:
            definition = _bind_transform_to_definition(definition, transform, source=source)
        elif definition.transform is not None:
            definition = _bind_transform_to_definition(
                definition,
                definition.transform,
                source=source or definition.source,
            )

        definition = self._attach_registered_models(definition)
        existing = self._migrations.get(definition.key)
        if existing is not None and existing is not definition:
            raise InvalidMigrationError(
                f"Duplicate migration registration for "
                f"{definition.schema_name} v{definition.from_version} -> v{definition.to_version}"
            )
        self._migrations[definition.key] = definition
        return definition

    def register_migration_function(self, func: Callable[..., Any]) -> MigrationDefinition:
        definition = cast(MigrationDefinition | None, getattr(func, _MIGRATION_ATTR, None))
        if definition is None:
            raise InvalidMigrationError(
                f"{func!r} is missing migration metadata; use @define_migration(...)"
            )
        return self.register_migration(definition)

    def get_migration(
        self, schema_name: str, from_version: int, to_version: int
    ) -> MigrationDefinition | None:
        return self._migrations.get((schema_name, from_version, to_version))

    def iter_migrations(
        self, schema_name: str | None = None
    ) -> tuple[MigrationDefinition, ...]:
        migrations = tuple(
            sorted(
                self._migrations.values(),
                key=lambda migration: (
                    migration.schema_name,
                    migration.from_version,
                    migration.to_version,
                ),
            )
        )
        if schema_name is None:
            return migrations
        return tuple(m for m in migrations if m.schema_name == schema_name)

    def iter_models(
        self, schema_name: str | None = None
    ) -> tuple[type[VersionedModel], ...]:
        models = tuple(
            sorted(
                self._models.values(),
                key=lambda model_cls: (
                    model_cls.schema_id().schema_name,
                    model_cls.schema_id().version,
                    model_cls.__module__,
                    model_cls.__name__,
                ),
            )
        )
        if schema_name is None:
            return models
        return tuple(model for model in models if model.schema_id().schema_name == schema_name)

    def schema_names(self) -> tuple[str, ...]:
        names = {schema.schema_name for schema in self._models}
        names.update(migration.schema_name for migration in self._migrations.values())
        return tuple(sorted(names))

    def neighbors(self, schema_name: str, version: int) -> tuple[MigrationDefinition, ...]:
        neighbors = [
            migration
            for migration in self._migrations.values()
            if migration.schema_name == schema_name and migration.from_version == version
        ]
        neighbors.sort(key=lambda migration: migration.to_version)
        return tuple(neighbors)

    def missing_adjacent_migrations(
        self,
        schema_name: str,
        *,
        require_bidirectional: bool = True,
    ) -> tuple[MissingMigration, ...]:
        models = self.iter_models(schema_name)
        if len(models) < 2:
            return ()

        missing: list[MissingMigration] = []
        for index in range(len(models) - 1):
            from_model = models[index]
            to_model = models[index + 1]
            from_schema = from_model.schema_id()
            to_schema = to_model.schema_id()
            if to_schema.version - from_schema.version != 1:
                continue
            if self.get_migration(schema_name, from_schema.version, to_schema.version) is None:
                missing.append(
                    MissingMigration(
                        schema_name=schema_name,
                        from_version=from_schema.version,
                        to_version=to_schema.version,
                        from_model=from_model,
                        to_model=to_model,
                    )
                )
            if require_bidirectional and (
                self.get_migration(schema_name, to_schema.version, from_schema.version) is None
            ):
                missing.append(
                    MissingMigration(
                        schema_name=schema_name,
                        from_version=to_schema.version,
                        to_version=from_schema.version,
                        from_model=to_model,
                        to_model=from_model,
                    )
                )

        return tuple(missing)

    def _attach_registered_models(self, definition: MigrationDefinition) -> MigrationDefinition:
        from_model = definition.from_model
        to_model = definition.to_model

        registered_from_model = self.get_model(definition.schema_name, definition.from_version)
        if registered_from_model is not None:
            if from_model is not None and from_model is not registered_from_model:
                raise InvalidMigrationError(
                    "Registered source model does not match migration source model"
                )
            from_model = registered_from_model

        registered_to_model = self.get_model(definition.schema_name, definition.to_version)
        if registered_to_model is not None:
            if to_model is not None and to_model is not registered_to_model:
                raise InvalidMigrationError(
                    "Registered target model does not match migration target model"
                )
            to_model = registered_to_model

        if from_model is definition.from_model and to_model is definition.to_model:
            return definition

        return replace(definition, from_model=from_model, to_model=to_model)

    def _refresh_migration_models(self, schema_name: str, version: int) -> None:
        for key, definition in tuple(self._migrations.items()):
            if definition.schema_name != schema_name:
                continue
            if definition.from_version != version and definition.to_version != version:
                continue
            self._migrations[key] = self._attach_registered_models(definition)


def _source_from_transform(transform: MigrationTransform | None) -> str | None:
    if transform is None:
        return None
    return f"{transform.__module__}.{transform.__name__}"
