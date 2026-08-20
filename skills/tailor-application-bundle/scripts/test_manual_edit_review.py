import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_manual_edit_review.py")
SPEC = importlib.util.spec_from_file_location("manual_review", SCRIPT)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(validator)


class ManualEditReviewTests(unittest.TestCase):
    def test_accept_must_match_current_revision_inputs_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            version = Path(directory) / "v001"
            version.mkdir()
            job = version / "job.json"
            evidence = version / "candidate-evidence.json"
            job.write_text("{}", encoding="utf-8")
            evidence.write_text("{}", encoding="utf-8")
            text_hashes = {"resume.pdf": "a", "motivation-letter.pdf": "b"}
            (version / "manifest.json").write_text(json.dumps({
                "document_revision": 2, "document_text_sha256": text_hashes,
            }), encoding="utf-8")
            review = {
                "schema_version": 1, "version_directory": str(version.resolve()),
                "document_revision": 2,
                "inputs": {
                    "job_json": str(job.resolve()), "job_sha256": hashlib.sha256(job.read_bytes()).hexdigest(),
                    "candidate_evidence_json": str(evidence.resolve()),
                    "candidate_evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                },
                "document_text_sha256": text_hashes,
                "checks": {key: True for key in validator.CHECKS},
                "findings": [], "verdict": "accept", "reviewed_at": "2026-08-20T12:00:00+00:00",
            }
            self.assertEqual(validator.validate(review, version), [])
            review["document_text_sha256"]["resume.pdf"] = "changed"
            self.assertIn("document text hashes do not match the current PDFs", validator.validate(review, version))


if __name__ == "__main__":
    unittest.main()
