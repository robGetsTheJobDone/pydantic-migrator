"""Version metadata for Pydantic schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ClassVar, TypeVar

from pydantic import BaseModel

from .exceptions import InvalidVersionedModelError


@dataclass(frozen=True, order=True, slots=True)
class SchemaVersion:
    """Unique identifier for a versioned schema."""

    schema_name: str
    version: int

    def __post_init__(self) -> None:
        if not self.schema_name:
            raise InvalidVersionedModelError("schema_name must be a non-empty string")
        if self.version < 1:
            raise InvalidVersionedModelError("version must be >= 1")

    def is_adjacent_to(self, other: "SchemaVersion") -> bool:
        return self.schema_name == other.schema_name and abs(self.version - other.version) == 1

    def __str__(self) -> str:
        return f"{self.schema_name}:v{self.version}"


class VersionedModel(BaseModel):
    """Base class for models that participate in versioned migrations."""

    schema_name: ClassVar[str]
    schema_version: ClassVar[int]

    @classmethod
    def schema_id(cls) -> SchemaVersion:
        schema_name = getattr(cls, "schema_name", None)
        schema_version = getattr(cls, "schema_version", None)

        if not isinstance(schema_name, str) or not schema_name.strip():
            raise InvalidVersionedModelError(
                f"{cls.__name__} must define a non-empty class var `schema_name`"
            )
        if not isinstance(schema_version, int):
            raise InvalidVersionedModelError(
                f"{cls.__name__} must define an integer class var `schema_version`"
            )

        return SchemaVersion(schema_name=schema_name, version=schema_version)


ModelT = TypeVar("ModelT", bound=type[VersionedModel])


def versioned_model(schema_name: str, version: int) -> Callable[[ModelT], ModelT]:
    """Attach schema metadata to a ``VersionedModel`` subclass."""

    schema = SchemaVersion(schema_name=schema_name, version=version)

    def decorator(model_cls: ModelT) -> ModelT:
        if not issubclass(model_cls, VersionedModel):
            raise InvalidVersionedModelError(
                "@versioned_model can only be applied to VersionedModel subclasses"
            )

        model_cls.schema_name = schema.schema_name
        model_cls.schema_version = schema.version
        model_cls.schema_id()
        return model_cls

    return decorator
