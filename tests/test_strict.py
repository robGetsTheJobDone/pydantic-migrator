from __future__ import annotations

import unittest

from pydantic_migrator import (
    InvalidMigrationError,
    MigrationRegistry,
    VersionedModel,
    build_registry,
    define_migration,
    find_missing_adjacent_migrations,
    versioned_model,
)


@versioned_model("invoice", 1)
class InvoiceV1(VersionedModel):
    total_cents: int


@versioned_model("invoice", 2)
class InvoiceV2(VersionedModel):
    total_cents: int
    currency: str


@versioned_model("invoice", 3)
class InvoiceV3(VersionedModel):
    total_minor_units: int
    currency: str


@define_migration(from_model=InvoiceV1, to_model=InvoiceV2)
def migrate_invoice_v1_to_v2(model: InvoiceV1) -> InvoiceV2:
    return InvoiceV2(total_cents=model.total_cents, currency="USD")


class StrictValidationTests(unittest.TestCase):
    def test_duplicate_model_versions_raise(self) -> None:
        @versioned_model("invoice", 1)
        class InvoiceV1Duplicate(VersionedModel):
            total_cents: int

        registry = MigrationRegistry().register(InvoiceV1)

        with self.assertRaises(InvalidMigrationError):
            registry.register(InvoiceV1Duplicate)

    def test_duplicate_migration_edges_raise(self) -> None:
        @define_migration(from_model=InvoiceV1, to_model=InvoiceV2)
        def migrate_invoice_v1_to_v2_alt(model: InvoiceV1) -> InvoiceV2:
            return InvoiceV2(total_cents=model.total_cents, currency="EUR")

        with self.assertRaises(InvalidMigrationError):
            build_registry(
                InvoiceV1,
                InvoiceV2,
                migrate_invoice_v1_to_v2,
                migrate_invoice_v1_to_v2_alt,
            )

    def test_mismatched_annotations_raise(self) -> None:
        with self.assertRaises(InvalidMigrationError):
            @define_migration(schema_name="invoice", from_version=1, to_version=2)
            def bad_invoice_migration(model: InvoiceV1) -> InvoiceV3:
                return InvoiceV3(total_minor_units=model.total_cents, currency="USD")

    def test_missing_adjacent_migrations_are_reported_structurally(self) -> None:
        registry = build_registry(InvoiceV1, InvoiceV2, InvoiceV3, migrate_invoice_v1_to_v2)

        missing = find_missing_adjacent_migrations(registry, schema_name="invoice")

        self.assertEqual(
            [edge.key for edge in missing],
            [
                ("invoice", 2, 1),
                ("invoice", 2, 3),
                ("invoice", 3, 2),
            ],
        )

    def test_missing_adjacent_migrations_can_be_forward_only(self) -> None:
        registry = build_registry(InvoiceV1, InvoiceV2, InvoiceV3, migrate_invoice_v1_to_v2)

        missing = find_missing_adjacent_migrations(
            registry,
            schema_name="invoice",
            require_bidirectional=False,
        )

        self.assertEqual([edge.key for edge in missing], [("invoice", 2, 3)])
