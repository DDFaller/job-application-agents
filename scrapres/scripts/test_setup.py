import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("setup.py")
SPEC = importlib.util.spec_from_file_location("job_application_setup", SCRIPT)
setup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_marketplace_update_is_idempotent_and_preserves_other_plugins(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".agents" / "plugins" / "marketplace.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "name": "personal", "interface": {"displayName": "Mine"},
                "plugins": [{"name": "other"}],
            }), encoding="utf-8")
            setup.update_marketplace(home)
            _, name = setup.update_marketplace(home)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["interface"]["displayName"], "Mine")
            self.assertEqual(name, "personal")
            self.assertEqual([item["name"] for item in data["plugins"]], ["other", setup.PLUGIN_NAME])

    def test_rules_allow_only_named_first_party_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            (plugin / "scripts").mkdir(parents=True)
            (plugin / "scripts" / "safe.py").write_text("", encoding="utf-8")
            (plugin / "scripts" / "test_skip.py").write_text("", encoding="utf-8")
            path = setup.write_rules(root, [plugin])
            content = path.read_text(encoding="utf-8")
            self.assertIn(str((plugin / "scripts" / "safe.py").resolve()), content)
            self.assertNotIn("test_skip.py", content)
            self.assertNotIn('pattern = ["python3"],', content)

    def test_dependency_commands_detect_dnf(self):
        with mock.patch.object(setup, "command_exists", side_effect=lambda name: name == "dnf"):
            command = setup.dependency_commands()[0]
        self.assertEqual(command[:4], ["sudo", "dnf", "install", "-y"])
        self.assertIn("texlive-xetex", command)


if __name__ == "__main__":
    unittest.main()
