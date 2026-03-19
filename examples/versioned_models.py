"""Realistic versioned models used in the README and local experiments."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pydantic_migrator import (
    MigrationPlanner,
    VersionedModel,
    build_registry,
    define_migration,
    migrate,
    versioned_model,
)


class CustomerSnapshotV1(BaseModel):
    full_name: str
    email: str
    loyalty_tier: str | None = None


class AddressV1(BaseModel):
    street: str
    city: str
    country_code: str


class LineItemV1(BaseModel):
    sku: str
    quantity: int
    unit_price_cents: int
    tags: list[str] = Field(default_factory=list)


@versioned_model("order", 1)
class OrderV1(VersionedModel):
    legacy_order_id: str
    customer: CustomerSnapshotV1
    shipping_address: AddressV1
    items: list[LineItemV1]
    notes: list[str] = Field(default_factory=list)


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
    postal_code: str | None = None


class LineItemV2(BaseModel):
    sku: str
    quantity: int
    unit_price: MoneyV2
    tags: list[str] = Field(default_factory=list)


@versioned_model("order", 2)
class OrderV2(VersionedModel):
    order_id: str
    customer: CustomerProfileV2
    shipping_address: AddressV2
    items: list[LineItemV2]
    status: str
    notes: list[str] = Field(default_factory=list)


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
    tags: list[str] = Field(default_factory=list)


class FulfillmentWindowV3(BaseModel):
    timezone: str
    instructions: list[str] = Field(default_factory=list)


class OrderTotalsV3(BaseModel):
    subtotal: MoneyV2
    line_count: int


@versioned_model("order", 3)
class OrderV3(VersionedModel):
    order_id: str
    customer: CustomerProfileV3
    shipping_address: AddressV2
    lines: list[LineItemV3]
    fulfillment: FulfillmentWindowV3
    totals: OrderTotalsV3
    notes: list[str] = Field(default_factory=list)


def _split_full_name(full_name: str) -> tuple[str, str]:
    given_name, _, family_name = full_name.partition(" ")
    return given_name, family_name


@define_migration(from_model=OrderV1, to_model=OrderV2)
def migrate_order_v1_to_v2(model: OrderV1) -> OrderV2:
    given_name, family_name = _split_full_name(model.customer.full_name)
    segment = model.customer.loyalty_tier or "standard"
    return OrderV2(
        order_id=model.legacy_order_id,
        customer=CustomerProfileV2(
            name=CustomerNameV2(given_name=given_name, family_name=family_name),
            primary_email=model.customer.email,
            segment=segment,
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
                tags=list(item.tags),
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
            tags=list(item.tags),
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
        fulfillment=FulfillmentWindowV3(
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
                tags=list(line.tags),
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
            loyalty_tier=model.customer.segment,
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
                tags=list(item.tags),
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


registry = build_order_registry()


def plan_order_migration(start_version: int, target_version: int):
    return MigrationPlanner(registry).plan("order", start_version, target_version)


def migrate_order_to_v3(model: OrderV1 | OrderV2 | OrderV3) -> OrderV3:
    result = migrate(model, target_version=3, registry=registry)
    if not isinstance(result, OrderV3):
        raise TypeError(f"expected OrderV3, got {result.__class__.__name__}")
    return result
