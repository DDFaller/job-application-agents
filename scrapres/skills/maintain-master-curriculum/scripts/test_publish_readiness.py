import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("publish_readiness.py")
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("publish_readiness", SCRIPT)
publish = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(publish)


class ProfileTests(unittest.TestCase):
    def test_profile_is_evidence_index_not_new_claims(self):
        evidence = {
            "extraction_status": "complete",
            "candidate": {"name": "Ada Example", "headline": "Engineer", "location": None,
                          "contact": ["ada@example.test"], "languages": ["English — C1"]},
            "facts": [{"id": "E001", "category": "experience", "claim": "Built APIs.",
                       "source_path": "/sources/experience.md", "quote": "- [MC-EXP-001] Built APIs."}],
            "missing_fields": ["location"], "warnings": []
        }
        report = {"source_version": "v007"}
        result = publish.profile_markdown(evidence, Path("/sources"), report)
        self.assertIn("`E001` Built APIs.", result)
        self.assertIn("Quote: - [MC-EXP-001] Built APIs.", result)
        self.assertIn("Missing: location", result)
        self.assertNotIn("Ada Example is", result)


if __name__ == "__main__":
    unittest.main()
