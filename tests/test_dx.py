from __future__ import annotations

import unittest

from pydantic_migrator import (
    MigrationRegistry,
    VersionedModel,
    build_registry,
    define_migration,
    versioned_model,
)


@versioned_model("customer", 1)
class CustomerV1(VersionedModel):
    full_name: str


@versioned_model("customer", 2)
class CustomerV2(VersionedModel):
    given_name: str
    family_name: str


@define_migration(from_model=CustomerV1, to_model=CustomerV2)
def migrate_customer_v1_to_v2(model: CustomerV1) -> CustomerV2:
    given_name, _, family_name = model.full_name.partition(" ")
    return CustomerV2(given_name=given_name, family_name=family_name)


class DxTests(unittest.TestCase):
    def test_versioned_model_decorator_sets_schema_metadata(self) -> None:
        schema = CustomerV1.schema_id()

        self.assertEqual(schema.schema_name, "customer")
        self.assertEqual(schema.version, 1)

    def test_build_registry_accepts_mixed_entries(self) -> None:
        registry = build_registry(CustomerV1, CustomerV2, migrate_customer_v1_to_v2)

        self.assertIs(registry.get_model("customer", 1), CustomerV1)
        migration = registry.get_migration("customer", 1, 2)
        self.assertIsNotNone(migration)
        self.assertEqual(migration.source, f"{__name__}.migrate_customer_v1_to_v2")
        self.assertIs(migration.from_model, CustomerV1)
        self.assertIs(migration.to_model, CustomerV2)

    def test_registry_register_accepts_models_and_functions(self) -> None:
        registry = MigrationRegistry().register(CustomerV1, CustomerV2, migrate_customer_v1_to_v2)

        self.assertIs(registry.get_model("customer", 2), CustomerV2)
        self.assertIsNotNone(registry.get_migration("customer", 1, 2))

    def test_register_migration_accepts_model_driven_arguments(self) -> None:
        registry = MigrationRegistry().register(CustomerV1, CustomerV2)

        definition = registry.register_migration(
            from_model=CustomerV1,
            to_model=CustomerV2,
            transform=migrate_customer_v1_to_v2,
        )

        self.assertEqual(definition.key, ("customer", 1, 2))
        self.assertIs(definition.from_model, CustomerV1)
        self.assertIs(definition.to_model, CustomerV2)
