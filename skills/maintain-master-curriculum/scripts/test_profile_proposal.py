from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_profile_proposal import load, validate


SKILL_DIR = Path(__file__).resolve().parent.parent


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProfileProposalTests(unittest.TestCase):
    def test_no_match_proposal_explains_and_cites_new_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "catalog.json"
            job = root / "job.json"
            candidate = root / "candidate.json"
            write(catalog, {"profiles": []})
            write(job, {"role": "Backend Engineer"})
            write(candidate, {"facts": [
                {"id": "E001", "source_fact_ids": ["MC-EXP-001"]},
                {"id": "E002", "source_fact_ids": ["MC-EXP-002"]},
                {"id": "E003", "source_fact_ids": ["MC-EXP-003"]},
            ]})
            proposal = load(SKILL_DIR / "references" / "profile-proposal-template.json")
            proposal.update({
                "inputs": {
                    "catalog_json": str(catalog), "catalog_sha256": digest(catalog),
                    "job_json": str(job), "job_sha256": digest(job),
                    "candidate_evidence_json": str(candidate), "candidate_evidence_sha256": digest(candidate),
                },
                "reason": "No approved profile covers the role's backend responsibilities.",
                "requested_profile": None,
                "proposed_profile": {
                    "id": "backend-engineer", "label": "Backend Engineer",
                    "narrative": "Backend services.", "target_roles": ["Backend Engineer"],
                    "canonical_headline": "Backend Engineer", "seniority_ceiling": "mid",
                    "anchor_fact_ids": ["MC-EXP-001"],
                    "supporting_fact_ids": ["MC-EXP-002", "MC-EXP-003"],
                    "technology_fact_ids": [],
                    "allowed_positioning_fact_ids": ["MC-EXP-001", "MC-EXP-002", "MC-EXP-003"],
                    "prohibited_claims": [], "risk_notes": [],
                },
                "gaps": ["No approved backend profile."],
                "generated_at": "2026-08-20T12:00:00+00:00",
            })
            errors = validate(proposal, load(SKILL_DIR / "references" / "profile-proposal-template.json"))
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
