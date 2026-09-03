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
    def test_humanizer_lock_is_valid_and_reproducible(self):
        lock = setup.load_humanizer_lock(Path(__file__).resolve().parent.parent)
        self.assertEqual(lock["name"], "humanizer")
        self.assertEqual(lock["version"], "2.11.2")
        self.assertEqual(len(lock["skill_sha256"]), 64)

    def test_humanizer_payload_validation_rejects_drift(self):
        lock = setup.load_humanizer_lock(Path(__file__).resolve().parent.parent)
        with self.assertRaises(ValueError):
            setup.validate_humanizer_payload(b"---\nmetadata:\n  version: '2.11.2'\n---\n", lock)

    def test_install_humanizer_skill_uses_pinned_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            plugin = root / "plugin"
            (repo / setup.HUMANIZER_LOCK.parent).mkdir(parents=True)
            (repo / setup.HUMANIZER_LOCK).write_text(
                (Path(__file__).resolve().parent.parent / setup.HUMANIZER_LOCK).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            lock = setup.load_humanizer_lock(repo)
            skill = b"---\nmetadata:\n  version: \"2.11.2\"\n---\ncontent\n"
            license_bytes = b"MIT\n"
            import hashlib
            lock["skill_sha256"] = hashlib.sha256(skill).hexdigest()
            lock["license_sha256"] = hashlib.sha256(license_bytes).hexdigest()
            (repo / setup.HUMANIZER_LOCK).write_text(json.dumps(lock), encoding="utf-8")

            class Response:
                def __init__(self, value):
                    self.value = value
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    return False
                def read(self):
                    return self.value

            with mock.patch.object(setup.urllib.request, "urlopen", side_effect=[Response(skill), Response(license_bytes)]):
                path, version = setup.install_humanizer_skill(repo, plugin)
            self.assertEqual(version, "2.11.2")
            self.assertEqual(path.read_bytes(), skill)
            self.assertEqual((path.parent / "LICENSE").read_bytes(), license_bytes)

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

    def test_docker_compose_check_requires_success(self):
        with mock.patch.object(setup, "command_exists", return_value=True), \
                mock.patch.object(setup.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(setup.docker_compose_ready())
            run.assert_called_once_with(
                ["docker", "compose", "version"], capture_output=True, text=True, check=False
            )

    def test_local_latex_tools_report_latexmk_and_package_hint(self):
        def installed(name):
            return name == "dnf" or name in {"xelatex", "kpsewhich", "pdfinfo", "pdftotext"}

        with mock.patch.object(
            setup.shutil, "which",
            side_effect=lambda name: "/usr/bin/tool" if installed(name) else None,
        ):
            self.assertEqual(setup.missing_local_latex_tools(), ["latexmk"])
            self.assertEqual(
                setup.local_latex_install_hint(["latexmk"]),
                "sudo dnf install -y latexmk",
            )
            self.assertEqual(
                setup.local_latex_install_commands(["latexmk"]),
                [["sudo", "dnf", "install", "-y", "latexmk"]],
            )


class RenderServiceScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script_path = Path(__file__).with_name("render_service.py")
        spec = importlib.util.spec_from_file_location("render_service_cli", script_path)
        cls.render_service = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(cls.render_service)

    def test_run_tests_unit_only_runs_step1_and_step2(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = {"JAA_ARTIFACT_ROOT": str(root / "artifacts")}
            base = ["docker", "compose", "-p", "jaa-test"]
            args = mock.MagicMock()
            args.unit_only = True
            args.live = False
            args.no_cleanup = False

            with mock.patch.object(self.render_service.subprocess, "run") as mock_run:
                mock_run.return_value.returncode = 0
                result = self.render_service.run_tests(args, root, env, base)
                self.assertEqual(result, 0)
                self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
