from __future__ import annotations

import unittest

from pydantic_migrator import (
    MigrationPlanner,
    MigrationPlanningError,
    MigrationRuntimeError,
    build_registry,
    VersionedModel,
    define_migration,
    migrate,
    versioned_model,
)


@versioned_model("widget", 1)
class WidgetV1(VersionedModel):
    name: str


@versioned_model("widget", 2)
class WidgetV2(VersionedModel):
    display_name: str


@versioned_model("widget", 3)
class WidgetV3(VersionedModel):
    title: str


@define_migration(from_model=WidgetV1, to_model=WidgetV2)
def migrate_widget_v1_to_v2(model: WidgetV1) -> WidgetV2:
    return WidgetV2(display_name=model.name)


@define_migration(from_model=WidgetV2, to_model=WidgetV3)
def migrate_widget_v2_to_v3(model: WidgetV2) -> WidgetV3:
    return WidgetV3(title=model.display_name)


@define_migration(from_model=WidgetV3, to_model=WidgetV2)
def migrate_widget_v3_to_v2(model: WidgetV3) -> WidgetV2:
    return WidgetV2(display_name=model.title)


@define_migration(from_model=WidgetV2, to_model=WidgetV1)
def migrate_widget_v2_to_v1(model: WidgetV2) -> WidgetV1:
    return WidgetV1(name=model.display_name)


def build_widget_registry():
    return build_registry(
        WidgetV1,
        WidgetV2,
        WidgetV3,
        migrate_widget_v1_to_v2,
        migrate_widget_v2_to_v3,
        migrate_widget_v3_to_v2,
        migrate_widget_v2_to_v1,
    )


class MigrationPlannerTests(unittest.TestCase):
    def test_planner_composes_upgrade_path(self) -> None:
        registry = build_widget_registry()
        plan = MigrationPlanner(registry).plan("widget", 1, 3)

        self.assertEqual(
            [(step.from_version, step.to_version) for step in plan.steps],
            [(1, 2), (2, 3)],
        )

    def test_planner_composes_downgrade_path(self) -> None:
        registry = build_widget_registry()
        plan = MigrationPlanner(registry).plan("widget", 3, 1)

        self.assertEqual(
            [(step.from_version, step.to_version) for step in plan.steps],
            [(3, 2), (2, 1)],
        )

    def test_migrate_applies_planned_steps(self) -> None:
        registry = build_widget_registry()
        result = migrate(WidgetV1(name="alpha"), target_version=3, registry=registry)

        self.assertIsInstance(result, WidgetV3)
        self.assertEqual(result.title, "alpha")

    def test_migrate_raises_for_wrong_runtime_return_type(self) -> None:
        @define_migration(from_model=WidgetV1, to_model=WidgetV2)
        def bad_widget_v1_to_v2(model: WidgetV1) -> WidgetV2:
            return WidgetV1(name=model.name)

        registry = build_registry(WidgetV1, WidgetV2, bad_widget_v1_to_v2)

        with self.assertRaises(MigrationRuntimeError):
            migrate(WidgetV1(name="alpha"), target_version=2, registry=registry)

    def test_planner_raises_when_route_is_missing(self) -> None:
        registry = build_registry(WidgetV1, WidgetV2, WidgetV3, migrate_widget_v1_to_v2)

        with self.assertRaises(MigrationPlanningError):
            MigrationPlanner(registry).plan("widget", 1, 3)
