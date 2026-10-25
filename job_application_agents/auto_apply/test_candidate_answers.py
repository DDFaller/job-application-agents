from pathlib import Path
import unittest
from unittest.mock import patch

from job_application_agents.auto_apply.draft_models import FieldSource
from job_application_agents.auto_apply.draft_service import DraftService
from job_application_agents.auto_apply.models import CandidateProfile
from job_application_agents.auto_apply.preprocessor import CompressedFormTree, FormFieldNode


class CandidateAnswerTests(unittest.TestCase):
    def test_missing_or_null_profile_answers_remain_unknown(self):
        for data in ({}, {"requires_sponsorship": None, "notice_period_weeks": None}):
            with self.subTest(data=data):
                profile = CandidateProfile.from_dict(data)
                self.assertIsNone(profile.requires_sponsorship)
                self.assertIsNone(profile.notice_period_weeks)
                self.assertIsNone(profile.work_authorization)
        profile = CandidateProfile.from_dict({"requires_sponsorship": False, "notice_period_weeks": 0})
        self.assertIs(profile.requires_sponsorship, False)
        self.assertEqual(profile.notice_period_weeks, 0)
        with self.assertRaisesRegex(ValueError, "boolean or null"):
            CandidateProfile.from_dict({"requires_sponsorship": "false"})

    def test_draft_leaves_job_specific_declarations_unanswered(self):
        profile = CandidateProfile("Jane", "Doe", "jane@example.test", "+33123456789", "Paris",
                                   work_authorization="Authorized", requires_sponsorship=False)
        fields = self.make_draft(profile).fields
        self.assertEqual([field.value for field in fields], ["", "", "", ""])

    def test_exact_answers_override_heuristics_and_preserve_attribution(self):
        profile = CandidateProfile("Jane", "Doe", "jane@example.test", "+33123456789", "Paris",
                                   custom_answers={"work": "Yes", "visa_field": "No",
                                                   "Can you work from our office?": "Yes",
                                                   "conflict": "No"})
        fields = self.make_draft(profile).fields
        self.assertEqual([field.value for field in fields], ["Yes", "No", "Yes", "No"])
        self.assertTrue(all(field.source == FieldSource.USER for field in fields))

    @staticmethod
    def make_draft(profile):
        nodes = [
            FormFieldNode("work", "work_field", "input", "text", "Are you authorized to work here?", True),
            FormFieldNode("visa", "visa_field", "input", "text", "Do you need visa sponsorship?", True),
            FormFieldNode("office", "office_field", "input", "text", "Can you work from our office?", True),
            FormFieldNode("conflict", "conflict_field", "input", "text", "Any conflict of interest?", True),
        ]
        tree = CompressedFormTree("https://example.test/apply", "Application", nodes)
        with patch("job_application_agents.auto_apply.draft_service.FormDOMPreprocessor.extract_from_page",
                   return_value=tree):
            return DraftService.create_draft_from_page(
                object(), "test", "Example", "Developer", profile, Path("resume.pdf"))
