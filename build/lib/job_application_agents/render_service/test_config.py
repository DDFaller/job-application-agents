from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from job_application_agents.config import (
    APPLICATION_BACKENDS,
    NOTION_SYNC_MODES,
    RENDER_ENGINES,
    RENDER_MODES,
    ConfigurationError,
    load_json_config,
    load_render_config,
    load_storage_config,
)


ROOT = Path(__file__).resolve().parents[2]


class ConfigurationTests(unittest.TestCase):
    def test_examples_document_the_loader_enums(self) -> None:
        config_example = (ROOT / "config.example.jsonc").read_text(encoding="utf-8")
        render_example = (ROOT / "render.example.jsonc").read_text(encoding="utf-8")

        for value in (*APPLICATION_BACKENDS, *NOTION_SYNC_MODES):
            self.assertIn(value, config_example)
        for value in RENDER_ENGINES:
            self.assertIn(value, render_example)
        for value in RENDER_MODES:
            self.assertIn(value, render_example)
        self.assertIn("//", config_example)
        self.assertIn("//", render_example)

    def test_jsonc_examples_are_not_runtime_input(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "invalid JSON configuration"):
            load_json_config(ROOT / "config.example.jsonc")
        with self.assertRaisesRegex(ConfigurationError, "invalid JSON configuration"):
            load_json_config(ROOT / "render.example.jsonc")

    def test_storage_config_reads_json_and_preserves_existing_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({
                "data_root": "~/configured-data",
                "storage": {
                    "application_backend": "local_only",
                    "notion_sync": "disabled",
                },
                "firestore_project_id": "configured-project",
                "notion_database_id": "configured-database",
            }), encoding="utf-8")
            config = load_storage_config(path, environ={
                "JAA_DATA_ROOT": "~/environment-data",
                "JAA_FIREBASE_PROJECT_ID": "environment-project",
                "NOTION_DATABASE_ID": "environment-database",
            })

        self.assertEqual(config.application_backend, "local_only")
        self.assertEqual(config.notion_sync, "disabled")
        self.assertEqual(config.data_root, (Path.home() / "environment-data").resolve())
        self.assertEqual(config.applications_root, config.data_root / "applications")
        self.assertEqual(config.firestore_project_id, "environment-project")
        self.assertEqual(config.notion_database_id, "environment-database")

    def test_storage_config_rejects_unknown_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"storage": {"application_backend": "unknown"}}), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "application_backend"):
                load_storage_config(path, environ={})

    def test_render_config_accepts_xelatex_and_rejects_unavailable_cvrender(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "render.json"
            path.write_text(json.dumps({"engine": "xelatex", "profile": "france"}), encoding="utf-8")
            config = load_render_config(path, environ={})
            self.assertEqual(config.engine, "xelatex")
            self.assertEqual(config.mode, "local")
            self.assertEqual(config.profile, "france")
            self.assertEqual(config.template, "builtin")

            path.write_text(json.dumps({"engine": "cvrender"}), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "adapter is unavailable"):
                load_render_config(path, environ={})

    def test_render_config_accepts_environment_mode_and_rejects_unknown_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "render.json"
            path.write_text(json.dumps({"mode": "cloud"}), encoding="utf-8")
            config = load_render_config(path, environ={})
            self.assertEqual(config.mode, "cloud")

            with self.assertRaisesRegex(ConfigurationError, "mode must be one of"):
                load_render_config(path, environ={"JAA_RENDER_MODE": "remote"})

    def test_render_config_accepts_slug_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "render.json"
            path.write_text(json.dumps({"profile": "france", "template": "compact-modern"}), encoding="utf-8")
            config = load_render_config(path, environ={"JAA_RENDER_PROFILE": "international"})

        self.assertEqual(config.profile, "international")
        self.assertEqual(config.template, "compact-modern")


if __name__ == "__main__":
    unittest.main()
