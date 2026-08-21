from __future__ import annotations

import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_manifest import manifest_for, write_json_atomic
from validate_role_profiles import fingerprint, load, validate


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RoleProfileTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, dict]:
        source = root / "sources"
        source.mkdir()
        (source / "identity.md").write_text(
            "# Identity\n- [MC-ID-001] Name: Ada Example\n- [MC-ID-002] Email: ada@example.test\n",
            encoding="utf-8",
        )
        (source / "experience.md").write_text(
            "# Experience\n- [MC-EXP-001] Built APIs.\n- [MC-EXP-002] Operated pipelines.\n- [MC-EXP-003] Monitored services.\n",
            encoding="utf-8",
        )
        manifest_path = source / "current.json"
        write_json_atomic(manifest_path, manifest_for(source, "v001"))
        manifest = load(manifest_path)
        catalog = load(SKILL_DIR / "references" / "role-profiles-template.json")
        catalog.update({
            "catalog_status": "staged",
            "source_manifest": {
                "path": str(manifest_path.resolve()),
                "sha256": digest(manifest_path),
                "fingerprint": fingerprint(manifest["source_hashes"]),
            },
            "profiles": [{
                "id": "backend-platform", "label": "Backend Platform Engineer",
                "narrative": "Backend systems and observable data workflows.",
                "target_roles": ["Backend Engineer"], "canonical_headline": "Backend Platform Engineer",
                "seniority_ceiling": "mid", "anchor_fact_ids": ["MC-EXP-001"],
                "supporting_fact_ids": ["MC-EXP-002", "MC-EXP-003"], "technology_fact_ids": [],
                "allowed_positioning_fact_ids": ["MC-EXP-001", "MC-EXP-002", "MC-EXP-003"],
                "prohibited_claims": ["Senior ownership"], "risk_notes": ["Keep scope explicit"],
            }],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        return manifest_path, catalog

    def test_valid_catalog_is_source_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, catalog = self.fixture(Path(temporary))
            template = load(SKILL_DIR / "references" / "role-profiles-template.json")
            self.assertEqual(validate(catalog, template), [])

    def test_catalog_becomes_stale_when_source_manifest_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path, catalog = self.fixture(Path(temporary))
            manifest_path.write_text(manifest_path.read_text() + "\n", encoding="utf-8")
            errors = validate(catalog, load(SKILL_DIR / "references" / "role-profiles-template.json"))
            self.assertTrue(any("source manifest" in error for error in errors))

    def test_profile_requires_anchor_and_two_supports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, catalog = self.fixture(Path(temporary))
            catalog["profiles"][0]["supporting_fact_ids"] = ["MC-EXP-002"]
            errors = validate(catalog, load(SKILL_DIR / "references" / "role-profiles-template.json"))
            self.assertTrue(any("supporting_fact_ids" in error for error in errors))

    def test_approved_catalog_is_versioned_and_resolvable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, catalog = self.fixture(root)
            catalog_path = root / "role-profiles.json"
            catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
            review = load(SKILL_DIR / "references" / "profile-review-template.json")
            review.update({
                "inputs": {"catalog_json": str(catalog_path), "catalog_sha256": digest(catalog_path)},
                "checks": {key: True for key in review["checks"]},
                "findings": [], "verdict": "accept",
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            })
            review_path = root / "profile-review.json"
            review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
            state = root / "state"
            commit = subprocess.run([
                sys.executable, str(SCRIPT_DIR / "commit_profile_update.py"),
                "--catalog", str(catalog_path), "--review", str(review_path),
                "--state-root", str(state), "--approval", "APPROVED",
            ], text=True, capture_output=True, check=False)
            self.assertEqual(commit.returncode, 0, commit.stderr)
            resolve = subprocess.run([
                sys.executable, str(SCRIPT_DIR / "resolve_profiles.py"),
                "--state-root", str(state),
            ], text=True, capture_output=True, check=False)
            self.assertEqual(resolve.returncode, 0, resolve.stderr)
            self.assertEqual(json.loads(resolve.stdout)["profiles"], ["backend-platform"])


if __name__ == "__main__":
    unittest.main()
