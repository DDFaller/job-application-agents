import os
import unittest
from unittest.mock import Mock, patch
from job_application_agents.retirement import require_active, RETIRED_PROJECT
from job_application_agents.render_service.client import RenderServiceClient
from job_application_agents.render_service.firestore import FirestoreRenderJobRepository

class RetirementTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_retired_project_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "retired"):
            require_active(RETIRED_PROJECT)
    @patch.dict(os.environ, {}, clear=True)
    def test_local_and_other_projects_allowed(self):
        require_active("demo-job-application-agents")
        require_active("local-direct", url="http://127.0.0.1:8000")
    @patch.dict(os.environ, {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"}, clear=True)
    def test_emulator_allowed(self):
        require_active(RETIRED_PROJECT)
    @patch.dict(os.environ, {}, clear=True)
    def test_queue_client_rejects_before_upload(self):
        artifacts=Mock(); repo=Mock(project_id=RETIRED_PROJECT)
        with self.assertRaisesRegex(RuntimeError, "retired"):
            RenderServiceClient(repo, artifacts).compile_and_wait(None, (), None, idempotency_key="test")
        artifacts.put_directory.assert_not_called()
        repo.enqueue.assert_not_called()
    @patch.dict(os.environ, {}, clear=True)
    def test_direct_client_rejects_retired_host_before_upload(self):
        artifacts=Mock()
        with self.assertRaisesRegex(RuntimeError, "retired"):
            RenderServiceClient(None, artifacts).compile_direct("https://jaa-latex-worker-l4k2wdufaa-ew.a.run.app", None, (), None)
        artifacts.put_directory.assert_not_called()
    @patch.dict(os.environ, {}, clear=True)
    def test_repository_rejects_before_sdk(self):
        repo=FirestoreRenderJobRepository(RETIRED_PROJECT, client=Mock())
        with patch.object(repo, "_sdk") as sdk:
            with self.assertRaisesRegex(RuntimeError, "retired"):
                repo.enqueue(None, "test")
            sdk.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    def test_notion_enqueue_and_claim_rejected(self):
        from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
        repo=FirestoreNotionJobRepository(RETIRED_PROJECT, client=Mock())
        with patch.object(repo, "_sdk") as sdk:
            with self.assertRaisesRegex(RuntimeError, "retired"):
                repo.enqueue("user", "application", "upsert", {})
            with self.assertRaisesRegex(RuntimeError, "retired"):
                repo.claim("worker")
            sdk.assert_not_called()
