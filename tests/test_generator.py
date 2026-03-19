from __future__ import annotations

import unittest
from pathlib import Path

from pydantic_migrator import (
    InvalidMigrationError,
    VersionedModel,
    generate_adjacent_migration_stub,
    generate_bidirectional_migration_stubs,
    generate_missing_adjacent_migration_stubs,
    build_registry,
    define_migration,
    versioned_model,
)


@versioned_model("account", 1)
class AccountV1(VersionedModel):
    email: str


@versioned_model("account", 2)
class AccountV2(VersionedModel):
    primary_email: str


@versioned_model("account", 3)
class AccountV3(VersionedModel):
    primary_email: str
    is_active: bool


@define_migration(from_model=AccountV1, to_model=AccountV2)
def migrate_account_v1_to_v2(model: AccountV1) -> AccountV2:
    return AccountV2(primary_email=model.email)


class StubGenerationTests(unittest.TestCase):
    def test_generate_adjacent_stub_writes_todo_markers(self) -> None:
        with self.subTest("adjacent stub"), tempfile_directory() as tmp_path:
            result = generate_adjacent_migration_stub(
                tmp_path,
                from_model=AccountV1,
                to_model=AccountV2,
            )

            content = result.path.read_text(encoding="utf-8")

            self.assertEqual(result.path.name, "account_v1_to_v2.py")
            self.assertIn("@define_migration(", content)
            self.assertIn("from_model=AccountV1", content)
            self.assertIn("to_model=AccountV2", content)
            self.assertIn("def migrate_account_v1_to_v2", content)
            self.assertIn("TODO: map source fields into the target model.", content)
            self.assertIn("raise NotImplementedError", content)

    def test_generate_bidirectional_stubs_creates_both_directions(self) -> None:
        with self.subTest("bidirectional stubs"), tempfile_directory() as tmp_path:
            upgrade, downgrade = generate_bidirectional_migration_stubs(
                tmp_path,
                older_model=AccountV1,
                newer_model=AccountV2,
            )

            self.assertTrue(upgrade.path.exists())
            self.assertTrue(downgrade.path.exists())
            self.assertEqual(upgrade.path.name, "account_v1_to_v2.py")
            self.assertEqual(downgrade.path.name, "account_v2_to_v1.py")

    def test_generate_adjacent_stub_rejects_non_adjacent_versions(self) -> None:
        with self.subTest("non-adjacent rejection"), tempfile_directory() as tmp_path:
            with self.assertRaises(InvalidMigrationError):
                generate_adjacent_migration_stub(
                    tmp_path,
                    from_model=AccountV1,
                    to_model=AccountV3,
                )

    def test_generate_missing_adjacent_stubs_for_schema_family(self) -> None:
        registry = build_registry(AccountV1, AccountV2, AccountV3, migrate_account_v1_to_v2)

        with self.subTest("missing stub generation"), tempfile_directory() as tmp_path:
            generated = generate_missing_adjacent_migration_stubs(
                tmp_path,
                registry=registry,
                schema_name="account",
            )

            self.assertEqual(
                [stub.path.name for stub in generated],
                [
                    "account_v2_to_v1.py",
                    "account_v2_to_v3.py",
                    "account_v3_to_v2.py",
                ],
            )


class tempfile_directory:
    def __enter__(self) -> Path:
        import tempfile

        self._temp_dir = tempfile.TemporaryDirectory()
        return Path(self._temp_dir.name)

    def __exit__(self, exc_type, exc, tb) -> None:
        self._temp_dir.cleanup()
