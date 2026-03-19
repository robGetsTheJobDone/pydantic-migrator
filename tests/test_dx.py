from __future__ import annotations

import unittest

from pydantic import BaseModel

from pydantic_migrator import (
    MigrationRegistry,
    VersionedModel,
    build_registry,
    define_migration,
    versioned_model,
)


class CustomerSnapshotV1(BaseModel):
    full_name: str
    email: str


class AddressV1(BaseModel):
    street: str
    city: str
    country_code: str


class LineItemV1(BaseModel):
    sku: str
    quantity: int
    unit_price_cents: int


@versioned_model("order", 1)
class OrderV1(VersionedModel):
    legacy_order_id: str
    customer: CustomerSnapshotV1
    shipping_address: AddressV1
    items: list[LineItemV1]


class CustomerNameV2(BaseModel):
    given_name: str
    family_name: str


class CustomerProfileV2(BaseModel):
    name: CustomerNameV2
    primary_email: str


class MoneyV2(BaseModel):
    amount_minor: int
    currency: str


class AddressV2(BaseModel):
    line1: str
    city: str
    country_code: str


class LineItemV2(BaseModel):
    sku: str
    quantity: int
    unit_price: MoneyV2


@versioned_model("order", 2)
class OrderV2(VersionedModel):
    order_id: str
    customer: CustomerProfileV2
    shipping_address: AddressV2
    items: list[LineItemV2]
    status: str


@define_migration(from_model=OrderV1, to_model=OrderV2)
def migrate_order_v1_to_v2(model: OrderV1) -> OrderV2:
    given_name, _, family_name = model.customer.full_name.partition(" ")
    return OrderV2(
        order_id=model.legacy_order_id,
        customer=CustomerProfileV2(
            name=CustomerNameV2(given_name=given_name, family_name=family_name),
            primary_email=model.customer.email,
        ),
        shipping_address=AddressV2(
            line1=model.shipping_address.street,
            city=model.shipping_address.city,
            country_code=model.shipping_address.country_code,
        ),
        items=[
            LineItemV2(
                sku=item.sku,
                quantity=item.quantity,
                unit_price=MoneyV2(amount_minor=item.unit_price_cents, currency="USD"),
            )
            for item in model.items
        ],
        status="pending",
    )


class DxTests(unittest.TestCase):
    def test_versioned_model_decorator_sets_schema_metadata(self) -> None:
        schema = OrderV1.schema_id()

        self.assertEqual(schema.schema_name, "order")
        self.assertEqual(schema.version, 1)

    def test_build_registry_accepts_mixed_entries(self) -> None:
        registry = build_registry(OrderV1, OrderV2, migrate_order_v1_to_v2)

        self.assertIs(registry.get_model("order", 1), OrderV1)
        migration = registry.get_migration("order", 1, 2)
        self.assertIsNotNone(migration)
        self.assertEqual(migration.source, f"{__name__}.migrate_order_v1_to_v2")
        self.assertIs(migration.from_model, OrderV1)
        self.assertIs(migration.to_model, OrderV2)

    def test_registry_register_accepts_models_and_functions(self) -> None:
        registry = MigrationRegistry().register(OrderV1, OrderV2, migrate_order_v1_to_v2)

        self.assertIs(registry.get_model("order", 2), OrderV2)
        self.assertIsNotNone(registry.get_migration("order", 1, 2))

    def test_register_migration_accepts_model_driven_arguments(self) -> None:
        registry = MigrationRegistry().register(OrderV1, OrderV2)

        definition = registry.register_migration(
            from_model=OrderV1,
            to_model=OrderV2,
            transform=migrate_order_v1_to_v2,
        )

        self.assertEqual(definition.key, ("order", 1, 2))
        self.assertIs(definition.from_model, OrderV1)
        self.assertIs(definition.to_model, OrderV2)

    def test_model_driven_migration_maps_nested_models_and_lists(self) -> None:
        result = migrate_order_v1_to_v2(
            OrderV1(
                legacy_order_id="ord_123",
                customer=CustomerSnapshotV1(
                    full_name="Ada Lovelace",
                    email="ada@example.com",
                ),
                shipping_address=AddressV1(
                    street="12 Analytical Engine Way",
                    city="London",
                    country_code="GB",
                ),
                items=[
                    LineItemV1(
                        sku="gear-1",
                        quantity=2,
                        unit_price_cents=1599,
                    )
                ],
            )
        )

        self.assertEqual(result.order_id, "ord_123")
        self.assertEqual(result.customer.name.given_name, "Ada")
        self.assertEqual(result.customer.name.family_name, "Lovelace")
        self.assertEqual(result.shipping_address.line1, "12 Analytical Engine Way")
        self.assertEqual(result.items[0].unit_price.amount_minor, 1599)
        self.assertEqual(result.items[0].unit_price.currency, "USD")
        self.assertEqual(result.status, "pending")
