"""Planning for multi-hop migrations."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from pydantic import BaseModel

from .exceptions import MigrationPlanningError
from .registry import MigrationDefinition, MigrationRegistry


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Ordered adjacent steps from one version to another."""

    schema_name: str
    start_version: int
    target_version: int
    steps: tuple[MigrationDefinition, ...]

    def apply(self, model: BaseModel) -> BaseModel:
        current = model
        for step in self.steps:
            current = step.apply(current)
        return current


class MigrationPlanner:
    """Finds a path between schema versions using adjacent migrations."""

    def __init__(self, registry: MigrationRegistry) -> None:
        self.registry = registry

    def plan(self, schema_name: str, start_version: int, target_version: int) -> MigrationPlan:
        if start_version == target_version:
            return MigrationPlan(
                schema_name=schema_name,
                start_version=start_version,
                target_version=target_version,
                steps=(),
            )

        queue: deque[tuple[int, tuple[MigrationDefinition, ...]]] = deque(
            [(start_version, ())]
        )
        visited = {start_version}

        while queue:
            current_version, path = queue.popleft()
            for migration in self.registry.neighbors(schema_name, current_version):
                if migration.to_version in visited:
                    continue

                next_path = (*path, migration)
                if migration.to_version == target_version:
                    return MigrationPlan(
                        schema_name=schema_name,
                        start_version=start_version,
                        target_version=target_version,
                        steps=next_path,
                    )

                visited.add(migration.to_version)
                queue.append((migration.to_version, next_path))

        raise MigrationPlanningError(
            f"No migration path found for {schema_name} v{start_version} -> v{target_version}"
        )
