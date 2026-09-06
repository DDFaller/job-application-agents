from __future__ import annotations

from pathlib import Path
import unittest

from job_application_agents.auto_apply.draft_models import (
    ApplicationDraft,
    ApplicationField,
    ApplicationState,
    ApprovalToken,
    FieldSource,
    FieldType,
    VerificationScore,
)


class TestDraftModels(unittest.TestCase):
    def test_draft_hash_determinism(self):
        fields1 = [
            ApplicationField(id="name", label="Name", type=FieldType.TEXT, value="Jane Doe", source=FieldSource.PROFILE),
            ApplicationField(id="email", label="Email", type=FieldType.TEXT, value="daniel@example.com", source=FieldSource.PROFILE),
        ]
        fields2 = [
            ApplicationField(id="email", label="Email", type=FieldType.TEXT, value="daniel@example.com", source=FieldSource.PROFILE),
            ApplicationField(id="name", label="Name", type=FieldType.TEXT, value="Jane Doe", source=FieldSource.PROFILE),
        ]

        draft1 = ApplicationDraft(
            application_id="app-001",
            company="Acme",
            job_title="Software Engineer",
            target_url="https://jobs.lever.co/acme/1",
            revision=1,
            fields=fields1,
            resume_path="/path/to/resume.pdf",
        )
        draft2 = ApplicationDraft(
            application_id="app-001",
            company="Acme",
            job_title="Software Engineer",
            target_url="https://jobs.lever.co/acme/1",
            revision=1,
            fields=fields2,
            resume_path="/path/to/resume.pdf",
        )

        self.assertEqual(draft1.draft_hash, draft2.draft_hash)
        self.assertTrue(draft1.draft_hash.startswith("sha256:"))

    def test_draft_hash_changes_on_edit(self):
        fields = [
            ApplicationField(id="name", label="Name", type=FieldType.TEXT, value="Jane Doe", source=FieldSource.PROFILE),
            ApplicationField(id="years", label="Years Python", type=FieldType.NUMBER, value="4", source=FieldSource.AI),
        ]
        draft1 = ApplicationDraft(
            application_id="app-001",
            company="Acme",
            job_title="Software Engineer",
            target_url="https://jobs.lever.co/acme/1",
            revision=1,
            fields=fields,
            resume_path="/path/to/resume.pdf",
        )

        # Edit field
        fields_edited = [
            ApplicationField(id="name", label="Name", type=FieldType.TEXT, value="Jane Doe", source=FieldSource.PROFILE),
            ApplicationField(id="years", label="Years Python", type=FieldType.NUMBER, value="6", source=FieldSource.USER),
        ]
        draft2 = ApplicationDraft(
            application_id="app-001",
            company="Acme",
            job_title="Software Engineer",
            target_url="https://jobs.lever.co/acme/1",
            revision=2,
            fields=fields_edited,
            resume_path="/path/to/resume.pdf",
        )

        self.assertNotEqual(draft1.draft_hash, draft2.draft_hash)

    def test_verification_score_scoring_matrix(self):
        # Full confirmation
        v_high = VerificationScore(
            redirect_detected=True,       # 35
            success_text_found=True,      # 40
            confirmation_id="CONF-1234",  # 50
            submit_button_gone=True,      # 15
        )
        self.assertEqual(v_high.total_score, 140)
        self.assertEqual(v_high.verdict, ApplicationState.SUBMITTED_CONFIRMED)

        # Uncertain timeout
        v_uncertain = VerificationScore(
            redirect_detected=False,
            success_text_found=False,
            submit_button_gone=True,  # 15
        )
        self.assertEqual(v_uncertain.total_score, 15)
        self.assertEqual(v_uncertain.verdict, ApplicationState.SUBMISSION_UNCERTAIN)

        # Failed
        v_fail = VerificationScore()
        self.assertEqual(v_fail.total_score, 0)
        self.assertEqual(v_fail.verdict, ApplicationState.FAILED)


if __name__ == "__main__":
    unittest.main()
