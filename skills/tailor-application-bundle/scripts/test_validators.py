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
    source = root / "experience.md"
    source.write_text("evidence", encoding="utf-8")
    source_manifest = root / "current.json"
    source_hashes = {"experience.md": digest(source)}
    write_json(source_manifest, {
        "schema_version": 2, "version": "v001", "source_dir": str(root),
        "markdown_sources": ["experience.md"], "source_hashes": source_hashes,
    })
    profiles_path = root / "role-profiles.json"
    write_json(profiles_path, {
        "schema_version": 1, "catalog_status": "approved",
        "source_manifest": {
            "path": str(source_manifest), "sha256": digest(source_manifest),
            "fingerprint": hashlib.sha256(json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        },
        "profiles": [{
            "id": "systems-engineer", "label": "Systems Engineer", "narrative": "Build systems.",
            "target_roles": ["Engineer"], "canonical_headline": "Systems Engineer", "seniority_ceiling": "mid",
            "anchor_fact_ids": ["MC-EXP-001"], "supporting_fact_ids": ["MC-EXP-002", "MC-EXP-003"],
            "technology_fact_ids": [],
            "allowed_positioning_fact_ids": ["MC-EXP-001", "MC-EXP-002", "MC-EXP-003"],
            "prohibited_claims": [], "risk_notes": [],
        }], "generated_at": "2026-08-20T11:00:00+00:00",
    })
    write_json(job_path, {
        "company": "Example", "role": "Engineer", "canonical_url": "https://example.test/job",
        "field_evidence": {"responsibilities.0": ["Build systems"]},
    })
    write_json(candidate_path, {
        "candidate": {"name": "Candidate", "location": None, "contact": ["candidate@example.test"]},
        "sources": [{"path": str(source), "sha256": digest(source), "pages": None}],
        "facts": [
            {"id": "E001", "source_fact_ids": ["MC-EXP-001"]},
            {"id": "E002", "source_fact_ids": ["MC-EXP-002"]},
            {"id": "E003", "source_fact_ids": ["MC-EXP-003"]},
        ],
        "records": {"experience": [], "education": []},
    })
    bundle = json.loads((SKILL_DIR / "references" / "bundle-template.json").read_text(encoding="utf-8"))
    bundle.update({
        "inputs": {
            "job_json": str(job_path), "job_sha256": digest(job_path),
            "candidate_evidence_json": str(candidate_path),
            "candidate_evidence_sha256": digest(candidate_path),
            "role_profiles_json": str(profiles_path),
            "role_profiles_sha256": digest(profiles_path),
        },
        "job": {"company": "Example", "role": "Engineer", "canonical_url": "https://example.test/job"},
        "tailoring_strategy": {
            "job_family": "computing", "document_focus": "technical",
            "profile_ranking": [{
                "profile_id": "systems-engineer", "eligible": True, "score": 243,
                "candidate_evidence_ids": ["E001", "E002", "E003"],
                "job_evidence_keys": ["responsibilities.0"], "rationale": "Directly supported.",
            }],
            "selected_profile_id": "systems-engineer",
            "selected_profile_anchor_evidence_ids": ["E001"],
            "selected_profile_supporting_evidence_ids": ["E002", "E003"],
            "positioning_candidate_evidence_ids": ["E001", "E002", "E003"],
            "claim_scores": [{
                "candidate_evidence_id": evidence_id, "relevance": 3, "evidence_strength": 3,
                "specificity": 3, "recency": 3, "risk": 0, "redundancy": 0,
                "total": 81, "job_evidence_keys": ["responsibilities.0"],
            } for evidence_id in ("E001", "E002", "E003")],
            "job_priorities": [{"text": "Build systems", "job_evidence_keys": ["responsibilities.0"]}],
            "selected_candidate_evidence_ids": ["E001", "E002", "E003"],
            "deprioritized_candidate_evidence_ids": [],
            "fit_arguments": [{"text": "Relevant", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]}],
            "selection_rationale": {"text": "Relevant", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]},
        },
        "candidate": {
            "name": "Candidate", "headline": "Engineer", "headline_evidence_ids": ["E001"],
            "location": None, "contact": ["candidate@example.test"],
            "summary": {"text": "Engineer", "evidence_ids": ["E001", "E002", "E003"]},
        },
        "resume_sections": [{"title": "Skills", "items": [{"type": "one_line", "label": "Focus", "details": "Systems", "evidence_ids": ["E001"]}]}],
        "motivation_letter": {
            "date": None, "recipient": None, "subject": "Application", "salutation": "Hello",
            "paragraphs": [{"text": "I can contribute.", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]}],
            "closing": "Regards", "signature": "Candidate",
        },
        "match_analysis": {
            "matched": [{"text": "Relevant", "candidate_evidence_ids": ["E001"], "job_evidence_keys": ["responsibilities.0"]}],
            "gaps": [], "credibility_warnings": [],
        },
        "generated_at": "2026-08-20T12:00:00+00:00",
    })
    write_json(bundle_path, bundle)
    review = json.loads((SKILL_DIR / "references" / "tailoring-review-template.json").read_text(encoding="utf-8"))
    review.update({
        "inputs": {
            "job_json": str(job_path), "job_sha256": digest(job_path),
            "candidate_evidence_json": str(candidate_path), "candidate_evidence_sha256": digest(candidate_path),
            "role_profiles_json": str(profiles_path), "role_profiles_sha256": digest(profiles_path),
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

    def test_client_cannot_be_rendered_as_employer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, candidate_path, bundle_path, _ = fixture(root)
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["records"]["experience"] = [{
                "id": "X001", "legal_employer": None, "contracting_party": "RWS Group",
                "client": "Meta", "engagement_type": "freelancer", "official_title": "Data Annotator",
                "normalized_role_family": "Data Operations", "dates": "2025",
                "achievement_fact_ids": ["E001"], "evidence_ids": ["E001"],
            }]
            write_json(candidate_path, candidate)
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["inputs"]["candidate_evidence_sha256"] = digest(candidate_path)
            bundle["resume_sections"] = [{
                "title": "Experience", "items": [{
                    "type": "experience", "company": "Meta", "position": "Data Annotator",
                    "location": None, "dates": "2025", "summary": None, "highlights": [],
                    "evidence_ids": ["E001"],
                }],
            }]
            write_json(bundle_path, bundle)
            errors = bundle_validator.validate(
                bundle, bundle_validator.load(SKILL_DIR / "references" / "bundle-template.json"), bundle_path,
            )
            self.assertTrue(any("client cannot be the company" in error for error in errors))

    def test_education_must_copy_official_credential(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, candidate_path, bundle_path, _ = fixture(root)
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["records"]["education"] = [{
                "id": "D001", "institution": "PUC-Rio",
                "official_degree": "Postgraduate Specialization Certificate",
                "field": "Software Engineering", "track": None, "status": "completed",
                "credential_awarded": True, "dates": "2024", "evidence_ids": ["E001"],
            }]
            write_json(candidate_path, candidate)
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["inputs"]["candidate_evidence_sha256"] = digest(candidate_path)
            bundle["resume_sections"] = [{
                "title": "Education", "items": [{
                    "type": "education", "institution": "PUC-Rio", "area": "Software Engineering",
                    "degree": "Master's", "location": None, "dates": "2024", "summary": None,
                    "highlights": [], "evidence_ids": ["E001"],
                }],
            }]
            write_json(bundle_path, bundle)
            errors = bundle_validator.validate(
                bundle, bundle_validator.load(SKILL_DIR / "references" / "bundle-template.json"), bundle_path,
            )
            self.assertTrue(any("official degree" in error for error in errors))

    def test_claim_score_arithmetic_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, _, bundle_path, _ = fixture(Path(temporary))
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["tailoring_strategy"]["claim_scores"][0]["total"] = 80
            errors = bundle_validator.validate(
                bundle, bundle_validator.load(SKILL_DIR / "references" / "bundle-template.json"), bundle_path,
            )
            self.assertTrue(any("scoring formula" in error for error in errors))

    def test_freelancer_record_requires_explicit_contracting_party(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "experience.md"
            source.write_text("- [MC-EXP-001] Freelance annotation work.\n", encoding="utf-8")
            record = json.loads((SKILL_DIR / "references" / "candidate-evidence-template.json").read_text(encoding="utf-8"))
            record.update({
                "extraction_status": "complete",
                "candidate": {
                    "name": "Candidate", "headline": None, "location": None,
                    "contact": ["candidate@example.test"], "languages": [],
                },
                "sources": [{"path": str(source), "sha256": digest(source), "pages": None}],
                "facts": [{
                    "id": "E001", "category": "experience", "claim": "Freelance annotation work.",
                    "source_path": str(source), "page": None, "source_fact_ids": ["MC-EXP-001"],
                }],
                "records": {"experience": [{
                    "id": "X001", "legal_employer": None, "contracting_party": None,
                    "client": "Meta", "engagement_type": "freelancer", "official_title": "Annotator",
                    "normalized_role_family": "Data Operations", "dates": None,
                    "achievement_fact_ids": [], "evidence_ids": ["E001"],
                }], "education": []},
                "field_evidence": {"candidate.name": ["E001"], "candidate.contact.0": ["E001"]},
                "missing_fields": [], "warnings": ["Contracting party is ambiguous."],
                "extracted_at": "2026-08-20T12:00:00+00:00",
            })
            errors, _ = candidate_validator.validate(
                record, candidate_validator.load_bytes(
                    (SKILL_DIR / "references" / "candidate-evidence-template.json").read_bytes(),
                    SKILL_DIR / "references" / "candidate-evidence-template.json",
                ),
            )
            self.assertTrue(any("requires contracting_party" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
