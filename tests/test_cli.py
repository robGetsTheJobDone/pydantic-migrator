from __future__ import annotations

import contextlib
import io
import tempfile
import textwrap
import unittest
import uuid
from pathlib import Path

from pydantic_migrator.cli import main


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


def _write_module(source: str) -> tuple[str, str]:
    temp_dir = tempfile.TemporaryDirectory()
    module_name = f"temp_cli_models_{uuid.uuid4().hex}"
    module_path = Path(temp_dir.name) / f"{module_name}.py"
    module_path.write_text(textwrap.dedent(source), encoding="utf-8")

    _TEMP_DIRS.append(temp_dir)
    return (module_name, temp_dir.name)


_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []
