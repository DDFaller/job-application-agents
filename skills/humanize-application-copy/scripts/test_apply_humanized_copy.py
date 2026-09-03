from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("apply_humanized_copy.py")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HumanizedCopyTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path]:
        bundle = root / "bundle.json"
        write_json(bundle, {
            "candidate": {"summary": {"text": "Old profile.", "evidence_ids": ["E001"]}},
            "motivation_letter": {"paragraphs": [{"text": "Old letter.", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]}]},
            "locked": {"job": "Example", "ids": ["E001"]},
        })
        rewrites = root / "rewrites.json"
        write_json(rewrites, {
            "schema_version": 1,
            "humanizer_version": "2.11.2",
            "humanizer_skill_sha256": "a" * 64,
            "input_bundle_sha256": digest(bundle),
            "rewrites": [
                {"path": "candidate.summary.text", "before": "Old profile.", "after": "A concise profile."},
                {"path": "motivation_letter.paragraphs.0.text", "before": "Old letter.", "after": "A concise letter."},
            ],
        })
        return bundle, rewrites

    def test_applies_only_allowed_prose_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, rewrites = self.fixture(root)
            output = root / "out.json"
            receipt = root / "receipt.json"
            result = subprocess.run([
                sys.executable, str(SCRIPT), "--bundle", str(bundle),
                "--rewrites", str(rewrites), "--output-bundle", str(output),
                "--receipt", str(receipt),
            ], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["candidate"]["summary"]["text"], "A concise profile.")
            self.assertEqual(value["motivation_letter"]["paragraphs"][0]["text"], "A concise letter.")
            self.assertEqual(value["candidate"]["summary"]["evidence_ids"], ["E001"])
            self.assertEqual(value["locked"], {"job": "Example", "ids": ["E001"]})
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["status"], "accepted")

    def test_rejects_non_target_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, rewrites = self.fixture(root)
            value = json.loads(rewrites.read_text(encoding="utf-8"))
            value["rewrites"][0]["path"] = "locked.job"
            write_json(rewrites, value)
            result = subprocess.run([
                sys.executable, str(SCRIPT), "--bundle", str(bundle),
                "--rewrites", str(rewrites), "--output-bundle", str(root / "out.json"),
                "--receipt", str(root / "receipt.json"),
            ], capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "out.json").exists())


if __name__ == "__main__":
    unittest.main()
