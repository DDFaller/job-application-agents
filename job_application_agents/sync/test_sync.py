from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from job_application_agents.sync.firestore import FirestoreUserSyncRepository
from job_application_agents.sync.models import (
    ApplicationSyncSnapshot,
    ApplicationVersionSnapshot,
    CandidateEvidenceSnapshot,
    CurriculumSyncSnapshot,
    CurriculumVersionSnapshot,
    ProfileSyncSnapshot,
    ProfileVersionSnapshot,
    SyncResult,
    SyncStatusReport,
    UserContext,
)
from job_application_agents.sync.service import SyncService, file_sha256, slugify, write_json_atomic


class SyncModelUnitTests(unittest.TestCase):
    def test_user_context_serialization(self) -> None:
        user = UserContext(user_id="user-123", email="user@example.com", display_name="Test User")
        data = user.to_dict()
        self.assertEqual(data["user_id"], "user-123")
        self.assertEqual(data["email"], "user@example.com")
        self.assertEqual(data["sync_version"], 1)

    def test_curriculum_snapshot_roundtrip(self) -> None:
        original = CurriculumSyncSnapshot(
            version="v001",
            updated_at="2026-08-25T23:00:00Z",
            markdown_sources=["identity.md", "experience.md"],
            source_hashes={"identity.md": "a" * 64, "experience.md": "b" * 64},
            sources={"identity.md": "# Ada\n", "experience.md": "# Exp\n"},
            manifest={"schema_version": 2, "version": "v001"},
            photo={"filename": "profile-photo.jpg", "sha256": "c" * 64, "bytes": 100},
        )
        data = original.to_dict()
        restored = CurriculumSyncSnapshot.from_dict(data)
        self.assertEqual(restored.version, "v001")
        self.assertEqual(restored.markdown_sources, ["identity.md", "experience.md"])
        self.assertEqual(restored.sources["identity.md"], "# Ada\n")
        self.assertEqual(restored.photo["filename"], "profile-photo.jpg")

    def test_profile_snapshot_roundtrip(self) -> None:
        original = ProfileSyncSnapshot(
            version="p001",
            updated_at="2026-08-25T23:00:00Z",
            catalog={"catalog_status": "approved", "role_profiles": [{"role": "engineer"}]},
            catalog_sha256="d" * 64,
            source_manifest={"version": "v001"},
        )
        data = original.to_dict()
        restored = ProfileSyncSnapshot.from_dict(data)
        self.assertEqual(restored.version, "p001")
        self.assertEqual(restored.catalog_sha256, "d" * 64)
        self.assertEqual(restored.catalog["catalog_status"], "approved")

    def test_application_snapshot_roundtrip(self) -> None:
        version_snap = ApplicationVersionSnapshot(
            version="v001",
            generated_at="2026-08-25T23:00:00Z",
            manifest={"schema_version": 3, "version": "v001"},
            bundle={"schema_version": 5, "job": {"company": "Acme"}},
            job={"company": "Acme", "role": "Lead"},
            sources={"resume.tex": "\\documentclass...", "letter.tex": "Dear Hiring Team"},
            quality_gate={"automated": "passed"},
            semantic_review={"verdict": "accept"},
            document_text_sha256={"resume.pdf": "e" * 64},
            document_revision=0,
            source_provenance="agent_generated",
            artifacts={"resume.pdf": {"sha256": "f" * 64, "bytes": 500}},
            notion_page_url="https://notion.so/test-page",
        )
        app_snap = ApplicationSyncSnapshot(
            application_id="acme__lead__job123",
            company="Acme",
            company_slug="acme",
            role="Lead",
            role_slug="lead",
            job_id_or_hash="job123",
            status="TO_APPLY",
            current_version="v001",
            canonical_url="https://acme.com/jobs/123",
            notion_page_url="https://notion.so/test-page",
            match_summary="Strong match",
            selected_profile="lead",
            gaps=[],
            generated_at="2026-08-25T23:00:00Z",
            versions={"v001": version_snap},
        )
        data = app_snap.to_dict()
        restored = ApplicationSyncSnapshot.from_dict(data, versions={"v001": version_snap})
        self.assertEqual(restored.application_id, "acme__lead__job123")
        self.assertEqual(restored.company, "Acme")
        self.assertEqual(restored.versions["v001"].sources["letter.tex"], "Dear Hiring Team")

    def test_slugify(self) -> None:
        self.assertEqual(slugify("Example GmbH & Co. KG!"), "example-gmbh-co-kg")
        self.assertEqual(slugify("Senior Full-Stack Developer (Remote)"), "senior-full-stack-developer-remote")
        self.assertEqual(slugify(""), "unknown")


class SyncServiceUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.mock_repo = mock.MagicMock(spec=FirestoreUserSyncRepository)
        self.mock_repo.project_id = "test-project"
        self.service = SyncService(repository=self.mock_repo, default_data_root=self.data_root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_push_curriculum_success(self) -> None:
        sources_dir = self.data_root / "sources"
        sources_dir.mkdir(parents=True)
        (sources_dir / "identity.md").write_text("# Ada Example\n- [MC-ID-001] Name: Ada Example\n", encoding="utf-8")
        (sources_dir / "experience.md").write_text("# Experience\n- [MC-EXP-001] Worked at Acme\n", encoding="utf-8")
        write_json_atomic(sources_dir / "current.json", {
            "schema_version": 2,
            "version": "v001",
            "markdown_sources": ["experience.md", "identity.md"],
            "source_hashes": {
                "identity.md": file_sha256(sources_dir / "identity.md"),
                "experience.md": file_sha256(sources_dir / "experience.md"),
            },
            "updated_at": "2026-08-25T23:00:00Z",
        })

        snapshot = self.service.push_curriculum("user-1", self.data_root)
        self.assertEqual(snapshot.version, "v001")
        self.assertEqual(len(snapshot.markdown_sources), 2)
        self.mock_repo.save_curriculum.assert_called_once()
        _, kwargs = self.mock_repo.save_curriculum.call_args
        self.assertEqual(kwargs["user_id"], "user-1")
        self.assertEqual(kwargs["snapshot"].version, "v001")

    def test_push_profiles_success(self) -> None:
        profiles_dir = self.data_root / "master-curriculum" / "profiles"
        v_dir = profiles_dir / "versions" / "p001"
        v_dir.mkdir(parents=True)
        catalog_content = {
            "schema_version": 1,
            "catalog_status": "approved",
            "role_profiles": [{"role": "software-engineer"}],
            "source_manifest": {"version": "v001"},
        }
        (v_dir / "role-profiles.json").write_text(json.dumps(catalog_content), encoding="utf-8")
        write_json_atomic(profiles_dir / "current.json", {
            "schema_version": 1,
            "version": "p001",
            "catalog": str(v_dir / "role-profiles.json"),
            "catalog_sha256": file_sha256(v_dir / "role-profiles.json"),
            "source_manifest": {"version": "v001"},
            "updated_at": "2026-08-25T23:00:00Z",
        })

        snapshot = self.service.push_profiles("user-1", self.data_root)
        self.assertEqual(snapshot.version, "p001")
        self.mock_repo.save_profiles.assert_called_once()

    def test_push_applications_success(self) -> None:
        app_dir = self.data_root / "applications" / "example-corp" / "backend-eng" / "job99"
        v001 = app_dir / "v001"
        v001.mkdir(parents=True)
        manifest = {
            "schema_version": 3,
            "version": "v001",
            "job": {"company": "Example Corp", "role": "Backend Engineer", "url": "https://example.com/job99"},
            "generated_at": "2026-08-25T23:00:00Z",
            "notion_page_url": "https://notion.so/page123",
            "quality_gate": {"automated": "passed"},
            "semantic_review": {"verdict": "accept"},
            "artifacts": {"resume.pdf": {"sha256": "123", "bytes": 100}},
        }
        bundle = {
            "schema_version": 5,
            "job": {"company": "Example Corp", "role": "Backend Engineer"},
            "candidate": {"name": "Ada Example"},
            "tailoring_strategy": {"job_family": "backend", "selection_rationale": "High match"},
            "match_analysis": {"gaps": ["Kubernetes"]},
        }
        write_json_atomic(v001 / "manifest.json", manifest)
        write_json_atomic(v001 / "bundle.json", bundle)
        write_json_atomic(v001 / "job.json", manifest["job"])
        (v001 / "resume.tex").write_text("\\documentclass{article}", encoding="utf-8")
        write_json_atomic(app_dir / "current.json", {
            "version": "v001",
            "path": str(v001),
            "manifest": str(v001 / "manifest.json"),
        })

        results = self.service.push_applications("user-1", self.data_root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].company, "Example Corp")
        self.assertEqual(results[0].role, "Backend Engineer")
        self.assertEqual(results[0].gaps, ["Kubernetes"])
        self.mock_repo.save_application.assert_called_once()

    def test_pull_curriculum_writes_files(self) -> None:
        self.mock_repo.fetch_curriculum.return_value = CurriculumSyncSnapshot(
            version="v002",
            updated_at="2026-08-25T23:00:00Z",
            markdown_sources=["identity.md"],
            source_hashes={"identity.md": "abc"},
            sources={"identity.md": "# Pulled Identity\n- [MC-ID-001] Name: Test\n"},
            manifest={"schema_version": 2, "version": "v002"},
        )
        self.mock_repo.fetch_curriculum_versions.return_value = []

        success = self.service.pull_curriculum("user-1", self.data_root)
        self.assertTrue(success)
        pulled_file = self.data_root / "sources" / "identity.md"
        self.assertTrue(pulled_file.is_file())
        self.assertIn("Pulled Identity", pulled_file.read_text(encoding="utf-8"))

    def test_pull_applications_reconstructs_local_bundle(self) -> None:
        v_snap = ApplicationVersionSnapshot(
            version="v001",
            generated_at="2026-08-25T23:00:00Z",
            manifest={"schema_version": 3, "version": "v001"},
            bundle={"schema_version": 5},
            job={"company": "Pulled Corp"},
            sources={"resume.tex": "\\pulledtex"},
            quality_gate={"automated": "passed"},
            semantic_review={"verdict": "accept"},
            document_text_sha256={},
            document_revision=0,
            source_provenance="agent_generated",
            artifacts={},
        )
        app_snap = ApplicationSyncSnapshot(
            application_id="pulled-corp__dev__job1",
            company="Pulled Corp",
            company_slug="pulled-corp",
            role="Dev",
            role_slug="dev",
            job_id_or_hash="job1",
            status="TO_APPLY",
            current_version="v001",
            versions={"v001": v_snap},
        )
        self.mock_repo.list_applications.return_value = [app_snap]

        pulled = self.service.pull_applications("user-1", self.data_root)
        self.assertEqual(pulled, ["pulled-corp__dev__job1"])
        target_app = self.data_root / "applications" / "pulled-corp" / "dev" / "job1"
        self.assertTrue((target_app / "current.json").is_file())
        self.assertTrue((target_app / "v001" / "resume.tex").is_file())
        self.assertEqual((target_app / "v001" / "resume.tex").read_text(), "\\pulledtex")

    def test_status_drift_detection(self) -> None:
        self.mock_repo.fetch_curriculum.return_value = None
        self.mock_repo.fetch_profiles.return_value = None
        self.mock_repo.list_applications.return_value = []

        report = self.service.status("user-1", self.data_root)
        self.assertEqual(report.user_id, "user-1")
        self.assertFalse(report.curriculum_synced)
        self.assertFalse(report.profiles_synced)
        self.assertEqual(report.local_apps_count, 0)
        self.assertEqual(report.remote_apps_count, 0)


@unittest.skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "Firestore emulator is unavailable")
class FirestoreUserSyncRepositoryEmulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = FirestoreUserSyncRepository("demo-job-application-agents")

    def setUp(self) -> None:
        self.user_a = f"test-user-a-{uuid4()}"
        self.user_b = f"test-user-b-{uuid4()}"

    def tearDown(self) -> None:
        # Clean up test users
        for u in (self.user_a, self.user_b):
            try:
                user_doc = self.repository._user_ref(u)
                # Delete subcollections
                for col in ("curriculum", "curriculum_versions", "profiles", "profile_versions", "applications"):
                    for doc in user_doc.collection(col).stream():
                        doc.reference.delete()
                user_doc.delete()
            except Exception:
                pass

    def test_user_metadata_lifecycle(self) -> None:
        meta = self.repository.ensure_user(self.user_a, email="a@example.com", display_name="User A")
        self.assertEqual(meta["user_id"], self.user_a)
        self.assertEqual(meta["email"], "a@example.com")

        fetched = self.repository.fetch_user_meta(self.user_a)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["email"], "a@example.com")

    def test_curriculum_and_version_history_sync(self) -> None:
        snap = CurriculumSyncSnapshot(
            version="v001",
            updated_at="2026-08-25T23:00:00Z",
            markdown_sources=["identity.md"],
            source_hashes={"identity.md": "hash123"},
            sources={"identity.md": "# Ada\n"},
            manifest={"schema_version": 2, "version": "v001"},
        )
        v_snap = CurriculumVersionSnapshot(
            version="v001",
            created_at="2026-08-25T23:00:00Z",
            source_hashes={"identity.md": "hash123"},
            sources={"identity.md": "# Ada\n"},
            manifest={"schema_version": 1, "version": "v001"},
        )
        self.repository.save_curriculum(self.user_a, snap, versions=[v_snap])

        fetched_curr = self.repository.fetch_curriculum(self.user_a)
        self.assertIsNotNone(fetched_curr)
        self.assertEqual(fetched_curr.version, "v001")
        self.assertEqual(fetched_curr.sources["identity.md"], "# Ada\n")

        fetched_versions = self.repository.fetch_curriculum_versions(self.user_a)
        self.assertEqual(len(fetched_versions), 1)
        self.assertEqual(fetched_versions[0].version, "v001")

        # User B should have nothing
        self.assertIsNone(self.repository.fetch_curriculum(self.user_b))

    def test_application_and_subcollection_sync(self) -> None:
        v1 = ApplicationVersionSnapshot(
            version="v001",
            generated_at="2026-08-25T23:00:00Z",
            manifest={"schema_version": 3, "version": "v001"},
            bundle={"schema_version": 5},
            job={"company": "Emulator Corp"},
            sources={"resume.tex": "\\emulatortex"},
            quality_gate={"automated": "passed"},
            semantic_review={"verdict": "accept"},
            document_text_sha256={},
            document_revision=0,
            source_provenance="agent_generated",
            artifacts={},
        )
        app = ApplicationSyncSnapshot(
            application_id="emulator-corp__dev__job1",
            company="Emulator Corp",
            company_slug="emulator-corp",
            role="Dev",
            role_slug="dev",
            job_id_or_hash="job1",
            status="TO_APPLY",
            current_version="v001",
            versions={"v001": v1},
        )
        self.repository.save_application(self.user_a, app)

        fetched = self.repository.fetch_application(self.user_a, "emulator-corp__dev__job1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.company, "Emulator Corp")
        self.assertIn("v001", fetched.versions)
        self.assertEqual(fetched.versions["v001"].sources["resume.tex"], "\\emulatortex")

        # List apps for user A
        apps_list = self.repository.list_applications(self.user_a)
        self.assertEqual(len(apps_list), 1)
        self.assertEqual(apps_list[0].application_id, "emulator-corp__dev__job1")

        # User B should see 0 apps
        self.assertEqual(len(self.repository.list_applications(self.user_b)), 0)


if __name__ == "__main__":
    unittest.main()
