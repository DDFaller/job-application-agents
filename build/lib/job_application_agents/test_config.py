from pathlib import Path
import json
import tempfile
import unittest

from job_application_agents.config import ConfigurationError, resolve_data_root


class ResolveDataRootTests(unittest.TestCase):
    def test_precedence_is_explicit_then_environment_then_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"storage": {"data_root": str(root / "configured")}}))
            self.assertEqual(
                resolve_data_root(root / "explicit", environ={"JAA_DATA_ROOT": str(root / "env")}, config_path=config),
                (root / "explicit").resolve(),
            )
            self.assertEqual(
                resolve_data_root(environ={"JAA_DATA_ROOT": str(root / "env")}, config_path=config),
                (root / "env").resolve(),
            )

    def test_never_falls_back_to_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with self.assertRaises(ConfigurationError):
                resolve_data_root(environ={}, config_path=missing)

    def test_rejects_repository_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repo"
            with self.assertRaises(ConfigurationError):
                resolve_data_root(repository / "job-search", repository_root=repository)

    def test_load_dotenv_parses_values_and_exports(self) -> None:
        import os
        from job_application_agents.config import load_dotenv
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# Comment line\n"
                "NOTION_TOKEN=\"secret_token_123\"\n"
                "export NOTION_DATABASE_ID='db_456'\n"
                "ANOTHER_VAR=unquoted_value\n",
                encoding="utf-8",
            )
            loaded = load_dotenv(env_file, override=True)
            self.assertEqual(loaded.get("NOTION_TOKEN"), "secret_token_123")
            self.assertEqual(loaded.get("NOTION_DATABASE_ID"), "db_456")
            self.assertEqual(loaded.get("ANOTHER_VAR"), "unquoted_value")
            self.assertEqual(os.environ.get("NOTION_TOKEN"), "secret_token_123")
            self.assertEqual(os.environ.get("NOTION_DATABASE_ID"), "db_456")


if __name__ == "__main__":
    unittest.main()
