import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("audit_data_roots.py")
SPEC = importlib.util.spec_from_file_location("audit_data_roots", SCRIPT)
audit_data_roots = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(audit_data_roots)


class DataRootAuditTests(unittest.TestCase):
    def test_reports_divergent_repository_shadow_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = base / "repo"
            canonical = base / "private"
            shadow = repository / "job-search"
            shadow.mkdir(parents=True)
            canonical.mkdir()
            (shadow / "sources").mkdir()
            (canonical / "sources").mkdir()
            (shadow / "sources" / "identity.md").write_text("shadow")
            (canonical / "sources" / "identity.md").write_text("canonical")
            report = audit_data_roots.audit(repository, canonical)
            self.assertTrue(report["shadow_exists"])
            self.assertTrue(report["divergent"])
            self.assertTrue(shadow.is_dir())


if __name__ == "__main__":
    unittest.main()
