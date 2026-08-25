#!/usr/bin/env python3
"""Regression tests for tailoring validator public interfaces."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def load_module(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle_validator = load_module("validate_bundle.py", "test_validate_bundle")
review_validator = load_module("validate_tailoring_review.py", "test_validate_review")
candidate_validator = load_module("validate_candidate_evidence.py", "test_validate_candidate")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    job_path = root / "job.json"
    candidate_path = root / "candidate-evidence.json"
    bundle_path = root / "bundle.json"
    review_path = root / "tailoring-review.json"
    write_json(job_path, {
        "company": "Example", "role": "Engineer", "canonical_url": "https://example.test/job",
        "field_evidence": {"responsibilities.0": ["Build systems"]},
    })
    write_json(candidate_path, {
        "candidate": {"name": "Candidate", "location": None, "contact": ["candidate@example.test"]},
        "facts": [{"id": "E001"}],
    })
    bundle = json.loads((SKILL_DIR / "references" / "bundle-template.json").read_text(encoding="utf-8"))
    bundle.update({
        "inputs": {
            "job_json": str(job_path), "job_sha256": digest(job_path),
            "candidate_evidence_json": str(candidate_path),
            "candidate_evidence_sha256": digest(candidate_path),
        },
        "job": {"company": "Example", "role": "Engineer", "canonical_url": "https://example.test/job"},
        "tailoring_strategy": {
            "job_family": "computing", "document_focus": "technical",
            "job_priorities": [{"text": "Build systems", "job_evidence_keys": ["responsibilities.0"]}],
            "selected_candidate_evidence_ids": ["E001"],
            "deprioritized_candidate_evidence_ids": [],
            "fit_arguments": [{"text": "Relevant", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]}],
            "selection_rationale": {"text": "Relevant", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]},
        },
        "candidate": {
            "name": "Candidate", "headline": "Engineer", "headline_evidence_ids": ["E001"],
            "location": None, "contact": ["candidate@example.test"],
            "summary": {"text": "Engineer", "evidence_ids": ["E001"]},
        },
        "resume_sections": [{"title": "Skills", "items": [{"type": "one_line", "label": "Focus", "details": "Systems", "evidence_ids": ["E001"]}]}],
        "motivation_letter": {
            "date": None, "recipient": None, "subject": "Application", "salutation": "Hello",
            "paragraphs": [{"text": "I can contribute.", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]}],
            "closing": "Regards", "signature": "Candidate",
        },
        "match_analysis": {
            "matched": [{"text": "Relevant", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]}],
            "gaps": [],
        },
        "generated_at": "2026-08-20T12:00:00+00:00",
    })
    write_json(bundle_path, bundle)
    review = json.loads((SKILL_DIR / "references" / "tailoring-review-template.json").read_text(encoding="utf-8"))
    review.update({
        "inputs": {
            "job_json": str(job_path), "job_sha256": digest(job_path),
            "candidate_evidence_json": str(candidate_path), "candidate_evidence_sha256": digest(candidate_path),
            "bundle_json": str(bundle_path), "bundle_sha256": digest(bundle_path),
        },
        "checks": {key: True for key in review["checks"]},
        "findings": [], "verdict": "accept", "reviewed_at": "2026-08-20T12:01:00+00:00",
    })
    write_json(review_path, review)
    return job_path, candidate_path, bundle_path, review_path


class ValidatorTests(unittest.TestCase):
    def run_cli(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_DIR / script), *args],
            text=True, capture_output=True, check=False,
        )

    def test_bundle_and_review_cli_accept_valid_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, _, bundle, review = fixture(Path(temporary))
            bundle_result = self.run_cli("validate_bundle.py", "--bundle", str(bundle))
            review_result = self.run_cli("validate_tailoring_review.py", "--review", str(review))
            self.assertEqual(bundle_result.returncode, 0, bundle_result.stderr)
            self.assertEqual(review_result.returncode, 0, review_result.stderr)

    def test_cli_reports_bad_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "invalid.json"
            invalid.write_bytes(b"\xff")
            result = self.run_cli("validate_bundle.py", "--bundle", str(invalid))
            self.assertEqual(result.returncode, 1)
            self.assertIn("validation failed", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_review_must_use_bundle_input_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, candidate, _, review_path = fixture(root)
            alternate = root / "candidate-copy.json"
            alternate.write_bytes(candidate.read_bytes())
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["inputs"]["candidate_evidence_json"] = str(alternate)
            write_json(review_path, review)
            template = review_validator.load(SKILL_DIR / "references" / "tailoring-review-template.json")
            errors = review_validator.validate(review, template)
            self.assertIn("review candidate_evidence_json does not match the bundle input path", errors)

    def test_certification_is_a_supported_candidate_category(self) -> None:
        self.assertIn("certification", candidate_validator.CATEGORIES)


if __name__ == "__main__":
    unittest.main()
