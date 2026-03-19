from __future__ import annotations

import contextlib
import io
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

from pydantic_migrator.cli import main
from pydantic_migrator.discovery import build_registry_from_module, import_module_with_pythonpath


class CliTests(unittest.TestCase):
    def test_check_reports_ok_for_complete_schema_family(self) -> None:
        module_name, pythonpath = _write_module(
            """
            from pydantic_migrator import VersionedModel, define_migration, versioned_model


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
            """
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["check", "--module", module_name, "--pythonpath", pythonpath])

        self.assertEqual(exit_code, 0)
        self.assertIn("OK widget: no missing adjacent migrations", stdout.getvalue())

    def test_plan_prints_simple_path(self) -> None:
        module_name, pythonpath = _write_module(
            """
            from pydantic_migrator import VersionedModel, define_migration, versioned_model


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
            """
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "plan",
                    "--module",
                    module_name,
                    "--pythonpath",
                    pythonpath,
                    "--schema",
                    "widget",
                    "--from-version",
                    "1",
                    "--to-version",
                    "3",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), "widget: v1 -> v2 -> v3")

    def test_create_scaffolds_importable_schema_family(self) -> None:
        output_dir, pythonpath, module_base = _write_package_root()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "create",
                    "customer-profile",
                    "--path",
                    str(output_dir),
                ]
            )

        family_dir = output_dir / "customer_profile"
        self.assertEqual(exit_code, 0)
        self.assertTrue((family_dir / "__init__.py").exists())
        self.assertTrue((family_dir / "registry.py").exists())
        self.assertTrue((family_dir / "models" / "__init__.py").exists())
        self.assertTrue((family_dir / "models" / "v1.py").exists())
        self.assertTrue((family_dir / "migrations" / "__init__.py").exists())
        self.assertTrue((family_dir / "tests" / "__init__.py").exists())
        self.assertTrue((family_dir / "tests" / "test_customer_profile_migrations.py").exists())
        self.assertIn("Next steps:", stdout.getvalue())

        registry = build_registry_from_module(
            f"{module_base}.customer_profile",
            pythonpath=(pythonpath,),
        )
        model = registry.get_model("customer-profile", 1)
        self.assertIsNotNone(model)
        self.assertEqual(model.__name__, "CustomerProfileV1")

        registry_module = import_module_with_pythonpath(
            f"{module_base}.customer_profile.registry",
            pythonpath=(pythonpath,),
        )
        self.assertIs(registry_module.registry.get_model("customer-profile", 1), model)

    def test_create_supports_legacy_flag_style(self) -> None:
        output_dir, _, _ = _write_package_root()

        exit_code = main(
            [
                "create",
                "--schema",
                "customer",
                "--output-dir",
                str(output_dir),
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue((output_dir / "customer" / "registry.py").exists())

    def test_create_requires_importable_package_path(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(temp_dir.name) / "schemas"
        root_dir.mkdir(parents=True, exist_ok=True)
        _TEMP_DIRS.append(temp_dir)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["create", "customer", "--path", str(root_dir)])

        self.assertEqual(exit_code, 1)
        self.assertIn("must already be an importable package directory", stdout.getvalue())

    def test_bump_adds_next_model_and_adjacent_migration_stubs(self) -> None:
        output_dir, pythonpath, module_base = _write_package_root()
        create_exit_code = main(
            [
                "create",
                "customer",
                "--path",
                str(output_dir),
            ]
        )
        self.assertEqual(create_exit_code, 0)

        module_name = f"{module_base}.customer"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "bump",
                    module_name,
                    "--pythonpath",
                    pythonpath,
                ]
            )

        family_dir = output_dir / "customer"
        self.assertEqual(exit_code, 0)
        self.assertTrue((family_dir / "models" / "v2.py").exists())
        self.assertTrue((family_dir / "migrations" / "customer_v1_to_v2.py").exists())
        self.assertTrue((family_dir / "migrations" / "customer_v2_to_v1.py").exists())
        self.assertIn("Created customer v2", stdout.getvalue())

        check_stdout = io.StringIO()
        with contextlib.redirect_stdout(check_stdout):
            check_exit_code = main(
                [
                    "check",
                    "--module",
                    module_name,
                    "--pythonpath",
                    pythonpath,
                ]
            )

        self.assertEqual(check_exit_code, 0)
        self.assertIn("OK customer: no missing adjacent migrations", check_stdout.getvalue())

    def test_bump_supports_legacy_module_flag(self) -> None:
        output_dir, pythonpath, module_base = _write_package_root()
        create_exit_code = main(
            [
                "create",
                "--schema",
                "invoice",
                "--output-dir",
                str(output_dir),
            ]
        )
        self.assertEqual(create_exit_code, 0)

        exit_code = main(
            [
                "bump",
                "--module",
                f"{module_base}.invoice",
                "--pythonpath",
                pythonpath,
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue((output_dir / "invoice" / "models" / "v2.py").exists())

    def test_bump_reports_clear_error_for_malformed_managed_exports(self) -> None:
        output_dir, pythonpath, module_base = _write_package_root()
        create_exit_code = main(["create", "ledger", "--path", str(output_dir)])
        self.assertEqual(create_exit_code, 0)

        family_dir = output_dir / "ledger"
        (family_dir / "models" / "__init__.py").write_text(
            textwrap.dedent(
                """
                \"\"\"Versioned models for this schema family.\"\"\"

                # BEGIN pydantic-migrator managed exports
                from .v1 import LedgerV1
                """
            ),
            encoding="utf-8",
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "bump",
                    f"{module_base}.ledger",
                    "--pythonpath",
                    pythonpath,
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "must contain exactly one begin marker and one end marker",
            stdout.getvalue(),
        )

    def test_check_reports_version_gaps_for_scaffolded_family(self) -> None:
        output_dir, pythonpath, module_base = _write_package_root()
        create_exit_code = main(
            [
                "create",
                "ledger",
                "--path",
                str(output_dir),
            ]
        )
        self.assertEqual(create_exit_code, 0)

        family_dir = output_dir / "ledger"
        (family_dir / "models" / "v3.py").write_text(
            textwrap.dedent(
                """
                from pydantic_migrator import VersionedModel, versioned_model


                @versioned_model("ledger", 3)
                class LedgerV3(VersionedModel):
                    pass
                """
            ),
            encoding="utf-8",
        )
        (family_dir / "models" / "__init__.py").write_text(
            textwrap.dedent(
                """
                \"\"\"Versioned models for this schema family.\"\"\"

                # BEGIN pydantic-migrator managed exports
                from .v1 import LedgerV1
                from .v3 import LedgerV3

                __all__ = [
                    "LedgerV1",
                    "LedgerV3",
                ]
                # END pydantic-migrator managed exports
                """
            ),
            encoding="utf-8",
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "check",
                    "--module",
                    f"{module_base}.ledger",
                    "--pythonpath",
                    pythonpath,
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "GAP ledger: missing model version v2 between v1 and v3",
            stdout.getvalue(),
        )


def _write_module(source: str) -> tuple[str, str]:
    temp_dir = tempfile.TemporaryDirectory()
    module_name = f"temp_cli_models_{uuid.uuid4().hex}"
    module_path = Path(temp_dir.name) / f"{module_name}.py"
    module_path.write_text(textwrap.dedent(source), encoding="utf-8")

    _TEMP_DIRS.append(temp_dir)
    return (module_name, temp_dir.name)


def _write_package_root() -> tuple[Path, str, str]:
    temp_dir = tempfile.TemporaryDirectory()
    package_name = f"temp_cli_pkg_{uuid.uuid4().hex}"
    root_dir = Path(temp_dir.name)
    output_dir = root_dir / package_name / "schemas"
    output_dir.mkdir(parents=True, exist_ok=True)
    (root_dir / package_name / "__init__.py").write_text("", encoding="utf-8")
    (output_dir / "__init__.py").write_text("", encoding="utf-8")

    _TEMP_DIRS.append(temp_dir)
    return (output_dir, temp_dir.name, f"{package_name}.schemas")


_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []
