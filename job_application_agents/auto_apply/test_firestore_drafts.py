from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from job_application_agents.auto_apply.draft_models import (
    ApplicationDraft,
    ApplicationField,
    ApprovalToken,
    FieldSource,
    FieldType,
)
from job_application_agents.auto_apply.firestore import FirestoreDraftRepository


class TestFirestoreDraftRepository(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.repo = FirestoreDraftRepository(project_id="demo-test", client=self.mock_client)

    def test_save_draft_sets_subcollection_and_root(self):
        draft = ApplicationDraft(
            application_id="app-123",
            company="Acme",
            job_title="Engineer",
            target_url="https://example.com/apply",
            revision=1,
            fields=[
                ApplicationField(id="name", label="Name", type=FieldType.TEXT, value="Daniel", source=FieldSource.PROFILE),
            ],
            resume_path="/path/resume.pdf",
        )

        mock_draft_doc = MagicMock()
        mock_draft_doc.path = "users/u1/applications/app-123/drafts/1"
        self.mock_client.collection().document().collection().document().collection().document.return_value = mock_draft_doc

        path = self.repo.save_draft(user_id="u1", draft=draft)
        self.assertEqual(path, "users/u1/applications/app-123/drafts/1")
        self.assertTrue(mock_draft_doc.set.called)

    def test_enqueue_submission_job(self):
        token = ApprovalToken(
            application_id="app-123",
            revision=2,
            draft_hash="sha256:abcd1234",
        )

        job_id = self.repo.enqueue_submission_job(user_id="u1", application_id="app-123", token=token)
        self.assertEqual(job_id, "sub_app-123_r2")
        self.assertTrue(self.mock_client.collection("submissionJobs").document("sub_app-123_r2").set.called)


if __name__ == "__main__":
    unittest.main()
