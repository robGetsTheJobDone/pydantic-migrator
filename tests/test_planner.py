from __future__ import annotations

import unittest

from pydantic import BaseModel, ValidationError

from pydantic_migrator import (
    MigrationPlanner,
    MigrationPlanningError,
    MigrationRuntimeError,
    VersionedModel,
    build_registry,
    define_migration,
    migrate,
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
    notes: list[str]


class CustomerNameV2(BaseModel):
    given_name: str
    family_name: str


class CustomerProfileV2(BaseModel):
    name: CustomerNameV2
    primary_email: str
    segment: str


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
    notes: list[str]


class ContactMethodV3(BaseModel):
    kind: str
    value: str
    is_primary: bool = False


class CustomerProfileV3(BaseModel):
    name: CustomerNameV2
    contacts: list[ContactMethodV3]
    segment: str


class LineItemV3(BaseModel):
    sku: str
    quantity: int
    price: MoneyV2


class FulfillmentV3(BaseModel):
    timezone: str
    instructions: list[str]


class OrderTotalsV3(BaseModel):
    subtotal: MoneyV2
    line_count: int


@versioned_model("order", 3)
class OrderV3(VersionedModel):
    order_id: str
    customer: CustomerProfileV3
    shipping_address: AddressV2
    lines: list[LineItemV3]
    fulfillment: FulfillmentV3
    totals: OrderTotalsV3
    notes: list[str]


def _split_full_name(full_name: str) -> tuple[str, str]:
    given_name, _, family_name = full_name.partition(" ")
    return given_name, family_name


@define_migration(from_model=OrderV1, to_model=OrderV2)
def migrate_order_v1_to_v2(model: OrderV1) -> OrderV2:
    given_name, family_name = _split_full_name(model.customer.full_name)
    return OrderV2(
        order_id=model.legacy_order_id,
        customer=CustomerProfileV2(
            name=CustomerNameV2(given_name=given_name, family_name=family_name),
            primary_email=model.customer.email,
            segment="standard",
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
        notes=list(model.notes),
    )


@define_migration(from_model=OrderV2, to_model=OrderV3)
def migrate_order_v2_to_v3(model: OrderV2) -> OrderV3:
    lines = [
        LineItemV3(
            sku=item.sku,
            quantity=item.quantity,
            price=item.unit_price,
        )
        for item in model.items
    ]
    subtotal_minor = sum(line.quantity * line.price.amount_minor for line in lines)
    return OrderV3(
        order_id=model.order_id,
        customer=CustomerProfileV3(
            name=model.customer.name,
            contacts=[
                ContactMethodV3(
                    kind="email",
                    value=model.customer.primary_email,
                    is_primary=True,
                )
            ],
            segment=model.customer.segment,
        ),
        shipping_address=model.shipping_address,
        lines=lines,
        fulfillment=FulfillmentV3(
            timezone="UTC",
            instructions=list(model.notes),
        ),
        totals=OrderTotalsV3(
            subtotal=MoneyV2(amount_minor=subtotal_minor, currency="USD"),
            line_count=len(lines),
        ),
        notes=list(model.notes),
    )


@define_migration(from_model=OrderV3, to_model=OrderV2)
def migrate_order_v3_to_v2(model: OrderV3) -> OrderV2:
    primary_contact = next(
        (contact for contact in model.customer.contacts if contact.kind == "email" and contact.is_primary),
        None,
    )
    if primary_contact is None:
        primary_contact = next(
            (contact for contact in model.customer.contacts if contact.kind == "email"),
            ContactMethodV3(kind="email", value="unknown@example.com"),
        )

    return OrderV2(
        order_id=model.order_id,
        customer=CustomerProfileV2(
            name=model.customer.name,
            primary_email=primary_contact.value,
            segment=model.customer.segment,
        ),
        shipping_address=model.shipping_address,
        items=[
            LineItemV2(
                sku=line.sku,
                quantity=line.quantity,
                unit_price=line.price,
            )
            for line in model.lines
        ],
        status="pending",
        notes=list(model.notes),
    )


@define_migration(from_model=OrderV2, to_model=OrderV1)
def migrate_order_v2_to_v1(model: OrderV2) -> OrderV1:
    full_name = " ".join(
        part for part in (model.customer.name.given_name, model.customer.name.family_name) if part
    )
    return OrderV1(
        legacy_order_id=model.order_id,
        customer=CustomerSnapshotV1(
            full_name=full_name,
            email=model.customer.primary_email,
        ),
        shipping_address=AddressV1(
            street=model.shipping_address.line1,
            city=model.shipping_address.city,
            country_code=model.shipping_address.country_code,
        ),
        items=[
            LineItemV1(
                sku=item.sku,
                quantity=item.quantity,
                unit_price_cents=item.unit_price.amount_minor,
            )
            for item in model.items
        ],
        notes=list(model.notes),
    )


def build_order_registry():
    return build_registry(
        OrderV1,
        OrderV2,
        OrderV3,
        migrate_order_v1_to_v2,
        migrate_order_v2_to_v3,
        migrate_order_v3_to_v2,
        migrate_order_v2_to_v1,
    )


class MigrationPlannerTests(unittest.TestCase):
    def test_planner_composes_upgrade_path(self) -> None:
        registry = build_order_registry()
        plan = MigrationPlanner(registry).plan("order", 1, 3)

        self.assertEqual(
            [(step.from_version, step.to_version) for step in plan.steps],
            [(1, 2), (2, 3)],
        )

    def test_planner_composes_downgrade_path(self) -> None:
        registry = build_order_registry()
        plan = MigrationPlanner(registry).plan("order", 3, 1)

        self.assertEqual(
            [(step.from_version, step.to_version) for step in plan.steps],
            [(3, 2), (2, 1)],
        )

    def test_migrate_applies_planned_steps_to_nested_models(self) -> None:
        registry = build_order_registry()
        result = migrate(
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
                    LineItemV1(sku="gear-1", quantity=2, unit_price_cents=1500),
                    LineItemV1(sku="gear-2", quantity=1, unit_price_cents=2500),
                ],
                notes=["leave at front desk"],
            ),
            target_version=3,
            registry=registry,
        )

        self.assertIsInstance(result, OrderV3)
        self.assertEqual(result.order_id, "ord_123")
        self.assertEqual(result.customer.name.given_name, "Ada")
        self.assertEqual(result.customer.contacts[0].value, "ada@example.com")
        self.assertEqual(result.shipping_address.line1, "12 Analytical Engine Way")
        self.assertEqual([line.sku for line in result.lines], ["gear-1", "gear-2"])
        self.assertEqual(result.totals.subtotal.amount_minor, 5500)
        self.assertEqual(result.totals.line_count, 2)
        self.assertEqual(result.fulfillment.instructions, ["leave at front desk"])

    def test_migrate_raises_for_wrong_runtime_return_type(self) -> None:
        @define_migration(from_model=OrderV1, to_model=OrderV2)
        def bad_order_v1_to_v2(model: OrderV1) -> OrderV2:
            return model

        registry = build_registry(OrderV1, OrderV2, bad_order_v1_to_v2)

        with self.assertRaises(MigrationRuntimeError):
            migrate(
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
                    items=[LineItemV1(sku="gear-1", quantity=1, unit_price_cents=1000)],
                    notes=[],
                ),
                target_version=2,
                registry=registry,
            )

    def test_nested_target_validation_still_runs(self) -> None:
        @define_migration(from_model=OrderV1, to_model=OrderV2)
        def invalid_order_v1_to_v2(model: OrderV1) -> OrderV2:
            return OrderV2(
                order_id=model.legacy_order_id,
                customer=CustomerProfileV2(
                    name=CustomerNameV2(given_name="Ada", family_name="Lovelace"),
                    primary_email=model.customer.email,
                    segment="standard",
                ),
                shipping_address=AddressV2(
                    line1=model.shipping_address.street,
                    city=model.shipping_address.city,
                    country_code=model.shipping_address.country_code,
                ),
                items=[
                    LineItemV2(
                        sku="gear-1",
                        quantity=1,
                        unit_price=[],
                    )
                ],
                status="pending",
                notes=[],
            )

        registry = build_registry(OrderV1, OrderV2, invalid_order_v1_to_v2)

        with self.assertRaises(ValidationError):
            migrate(
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
                    items=[LineItemV1(sku="gear-1", quantity=1, unit_price_cents=1000)],
                    notes=[],
                ),
                target_version=2,
                registry=registry,
            )

    def test_planner_raises_when_route_is_missing(self) -> None:
        registry = build_registry(OrderV1, OrderV2, OrderV3, migrate_order_v1_to_v2)

        with self.assertRaises(MigrationPlanningError):
            MigrationPlanner(registry).plan("order", 1, 3)
