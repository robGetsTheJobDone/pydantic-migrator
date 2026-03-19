# pydantic-migrator

`pydantic-migrator` is a small library scaffold for versioned Pydantic model migrations.

The design is intentionally narrow:

- Model identity is explicit: every versioned model declares a schema name and version.
- Adjacent migrations are the source of truth.
- Multi-hop upgrades and downgrades are planned by composing adjacent migrations.
- Generated migration files are stubs on purpose. Humans fill in the domain transformation logic.

## Status

This is an initial scaffold, not a full migration framework. Generated stubs raise `NotImplementedError` until you implement them.

## Install

```bash
pip install -e .
# or, for development:
pip install -e ".[dev]"
```

## Core Concepts

### Versioned models

```python
from pydantic_migrator import VersionedModel, versioned_model


@versioned_model("customer", 1)
class CustomerV1(VersionedModel):
    full_name: str


@versioned_model("customer", 2)
class CustomerV2(VersionedModel):
    given_name: str
    family_name: str
```

### Adjacent migrations

You register migrations for neighboring versions only. The library plans longer paths by composing them.

```python
from pydantic_migrator import build_registry, define_migration


@define_migration(from_model=CustomerV1, to_model=CustomerV2)
def migrate_customer_v1_to_v2(model: CustomerV1) -> CustomerV2:
    parts = model.full_name.split(maxsplit=1)
    return CustomerV2(
        given_name=parts[0],
        family_name=parts[1] if len(parts) > 1 else "",
    )


registry = build_registry(
    CustomerV1,
    CustomerV2,
    migrate_customer_v1_to_v2,
)
```

The preferred declaration is model-driven. The explicit edge form still works when needed:

```python
@define_migration(schema_name="customer", from_version=1, to_version=2)
def migrate_customer_v1_to_v2(model: CustomerV1) -> CustomerV2:
    ...
```

Migrations are validated strictly:

- only adjacent edges are allowed
- duplicate model versions and duplicate migration edges are rejected
- source and target model metadata must match the declared edge
- typed annotations must agree with the declaration
- runtime return values must match the target model type when it is known

### Planning multi-hop upgrades or downgrades

```python
from pydantic_migrator import MigrationPlanner


planner = MigrationPlanner(registry)
plan = planner.plan("customer", 1, 3)

for step in plan.steps:
    print(step.from_version, "->", step.to_version)
```

If a caller wants `v3 -> v1`, the planner walks the registered adjacent downgrade migrations in reverse order.

### Missing migration detection

```python
from pydantic_migrator import find_missing_adjacent_migrations


missing = find_missing_adjacent_migrations(registry, schema_name="customer")
for edge in missing:
    print(edge.from_version, "->", edge.to_version)
```

## Stub Generation

You can generate migration stubs for adjacent versions:

```python
from pathlib import Path

from examples.versioned_models import CustomerV1, CustomerV2
from pydantic_migrator import generate_bidirectional_migration_stubs


generate_bidirectional_migration_stubs(
    Path("migrations"),
    older_model=CustomerV1,
    newer_model=CustomerV2,
)
```

Or generate every missing adjacent edge already implied by a registered schema family:

```python
from pydantic_migrator import generate_missing_adjacent_migration_stubs


generate_missing_adjacent_migration_stubs(
    Path("migrations"),
    registry=registry,
    schema_name="customer",
)
```

That produces files like:

- `customer_v1_to_v2.py`
- `customer_v2_to_v1.py`

Each generated file contains:

- A `define_migration(...)` decorator
- Typed source and target models
- `TODO` markers where human transform logic belongs
- An explicit `NotImplementedError` placeholder until the migration is written

## CLI

The CLI stays explicit. Point it at a module that defines your versioned models and decorated migrations.

```bash
pydantic-migrator check --module myapp.customer_migrations
pydantic-migrator plan --module myapp.customer_migrations --schema customer --from-version 1 --to-version 3
pydantic-migrator generate --module myapp.customer_migrations --schema customer --output-dir migrations
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

## Example Layout

- [`examples/versioned_models.py`](examples/versioned_models.py) contains `CustomerV1`, `CustomerV2`, and `CustomerV3`.
- Tests cover planning, DX helpers, and stub generation and can be run with `pytest`.
