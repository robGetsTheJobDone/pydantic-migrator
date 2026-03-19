# pydantic-migrator

`pydantic-migrator` is a focused library for versioned Pydantic model migrations.

It keeps the migration model explicit and strict:

- every versioned model declares a schema name and version
- migrations are registered for adjacent versions only
- multi-hop upgrades and downgrades are planned by composing those adjacent edges
- generated stubs intentionally stop at `NotImplementedError` because domain transforms still need human logic

This is meant to be usable as-is for teams that want boring, auditable schema evolution instead of magic inference.

## Install

```bash
pip install -e .
# or, for development:
pip install -e ".[dev]"
```

## Workflow

### 1. Define versioned models

Real schema evolution usually involves nested models and typed collections, not just field renames.

```python
from pydantic import BaseModel, Field

from pydantic_migrator import VersionedModel, versioned_model


class CustomerSnapshotV1(BaseModel):
    full_name: str
    email: str


class LineItemV1(BaseModel):
    sku: str
    quantity: int
    unit_price_cents: int


@versioned_model("order", 1)
class OrderV1(VersionedModel):
    legacy_order_id: str
    customer: CustomerSnapshotV1
    items: list[LineItemV1]
    notes: list[str] = Field(default_factory=list)


class CustomerNameV2(BaseModel):
    given_name: str
    family_name: str


class MoneyV2(BaseModel):
    amount_minor: int
    currency: str


class CustomerProfileV2(BaseModel):
    name: CustomerNameV2
    primary_email: str
    segment: str


class LineItemV2(BaseModel):
    sku: str
    quantity: int
    unit_price: MoneyV2


@versioned_model("order", 2)
class OrderV2(VersionedModel):
    order_id: str
    customer: CustomerProfileV2
    items: list[LineItemV2]
    status: str
    notes: list[str] = Field(default_factory=list)
```

The full example in [`examples/versioned_models.py`](examples/versioned_models.py) continues this schema family through `OrderV3`.

### 2. Define adjacent migrations

Use model-driven decorators so the edge definition stays coupled to the typed source and target models.

```python
from pydantic_migrator import define_migration


def split_full_name(full_name: str) -> tuple[str, str]:
    given_name, _, family_name = full_name.partition(" ")
    return given_name, family_name


@define_migration(from_model=OrderV1, to_model=OrderV2)
def migrate_order_v1_to_v2(model: OrderV1) -> OrderV2:
    given_name, family_name = split_full_name(model.customer.full_name)
    return OrderV2(
        order_id=model.legacy_order_id,
        customer=CustomerProfileV2(
            name=CustomerNameV2(
                given_name=given_name,
                family_name=family_name,
            ),
            primary_email=model.customer.email,
            segment="standard",
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
```

The explicit edge form still works when needed:

```python
@define_migration(schema_name="order", from_version=1, to_version=2)
def migrate_order_v1_to_v2(model: OrderV1) -> OrderV2:
    ...
```

### 3. Build a registry, plan paths, and migrate models

```python
from pydantic_migrator import MigrationPlanner, build_registry, migrate


registry = build_registry(
    OrderV1,
    OrderV2,
    OrderV3,
    migrate_order_v1_to_v2,
    migrate_order_v2_to_v3,
    migrate_order_v3_to_v2,
    migrate_order_v2_to_v1,
)

plan = MigrationPlanner(registry).plan("order", 1, 3)
assert [(step.from_version, step.to_version) for step in plan.steps] == [(1, 2), (2, 3)]

order_v3 = migrate(order_v1, target_version=3, registry=registry)
```

### 4. Scaffold a new schema family and bump versions

For a new schema family, start with the scaffolded package layout:

```bash
pydantic-migrator create order --path src/myapp/schemas
```

That creates:

- `src/myapp/schemas/order/__init__.py`
- `src/myapp/schemas/order/registry.py`
- `src/myapp/schemas/order/models/__init__.py`
- `src/myapp/schemas/order/models/v1.py`
- `src/myapp/schemas/order/migrations/__init__.py`
- `src/myapp/schemas/order/tests/__init__.py`
- `src/myapp/schemas/order/tests/test_order_migrations.py`

`--path` must point at an existing importable package directory. In the example above, `src/myapp/schemas/__init__.py` should already exist, and `--pythonpath src` makes the family importable as `myapp.schemas.order`.

When you are ready for the next version:

```bash
pydantic-migrator bump myapp.schemas.order --pythonpath src
```

By default `bump` writes:

- `models/v2.py`
- `migrations/order_v1_to_v2.py`
- `migrations/order_v2_to_v1.py`

Those migration files are intentionally generated as typed stubs with `TODO` markers and `NotImplementedError` placeholders. The library can scaffold the edge and the imports, but only the application owner can supply the business transformation logic.

You can also generate stubs directly:

```python
from pathlib import Path

from examples.versioned_models import OrderV1, OrderV2, registry
from pydantic_migrator import (
    generate_bidirectional_migration_stubs,
    generate_missing_adjacent_migration_stubs,
)


generate_bidirectional_migration_stubs(
    Path("migrations"),
    older_model=OrderV1,
    newer_model=OrderV2,
)

generate_missing_adjacent_migration_stubs(
    Path("migrations"),
    registry=registry,
    schema_name="order",
)
```

## Strictness

Migrations are validated strictly:

- only adjacent edges are allowed
- duplicate model versions and duplicate migration edges are rejected
- source and target model metadata must match the declared edge
- typed annotations must agree with the declaration
- runtime return values must match the target model type when it is known

For scaffolded families, `check`, `generate`, and `bump` also fail fast if model versions are not contiguous. A family with `v1` and `v3` but no `v2` reports a clear `GAP ...` error instead of silently skipping the hole.

## CLI

Point the CLI at a module or scaffolded family package that exposes your versioned models and decorated migrations.

```bash
pydantic-migrator create order --path src/myapp/schemas
pydantic-migrator bump myapp.schemas.order --pythonpath src
pydantic-migrator check --module myapp.order_migrations
pydantic-migrator plan --module myapp.order_migrations --schema order --from-version 1 --to-version 3
pydantic-migrator generate --module myapp.order_migrations --schema order --path migrations
```

The CLI accepts both the newer positional form and the older flag-based form for `create` and module-based commands such as `bump`. The positional form is preferred:

```bash
pydantic-migrator create order --path src/myapp/schemas
pydantic-migrator create --schema order --output-dir src/myapp/schemas

pydantic-migrator bump myapp.schemas.order --pythonpath src
pydantic-migrator bump --module myapp.schemas.order --pythonpath src
```

## Public API

- `VersionedModel`
- `SchemaVersion`
- `MigrationRegistry`
- `MigrationPlanner`
- `MigrationPlan`
- `MigrationDefinition`
- `define_migration`
- `versioned_model`
- `plan_migration(...)`
- `find_missing_adjacent_migrations(...)`
- `migrate(...)`
- `generate_adjacent_migration_stub(...)`
- `generate_bidirectional_migration_stubs(...)`
- `generate_missing_adjacent_migration_stubs(...)`

## Example

[`examples/versioned_models.py`](examples/versioned_models.py) contains a realistic `OrderV1` -> `OrderV2` -> `OrderV3` evolution story with nested models, list fields, adjacent migrations, a registry, and helper functions for planning and migrating.
