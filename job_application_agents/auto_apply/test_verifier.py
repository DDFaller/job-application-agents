from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from job_application_agents.auto_apply.draft_models import ApplicationState
from job_application_agents.auto_apply.verifier import SubmissionVerifier


class TestSubmissionVerifier(unittest.TestCase):
    def test_verifies_success_redirect_and_text(self):
        mock_page = MagicMock()
        mock_page.url = "https://jobs.lever.co/company/thank-you"

        mock_body = MagicMock()
        mock_body.inner_text.return_value = "Thank you for applying! Your application has been submitted. Reference: REF-987654"

        mock_submit = MagicMock()
        mock_submit.count.return_value = 0
        mock_submit.is_visible.return_value = False

        def locator_mock(selector, **kwargs):
            if selector == "body":
                return mock_body
            return mock_submit

        mock_page.locator.side_effect = locator_mock

        score = SubmissionVerifier.evaluate(
            page=mock_page,
            initial_url="https://jobs.lever.co/company/123/apply",
        )

        self.assertTrue(score.redirect_detected)
        self.assertTrue(score.success_text_found)
        self.assertEqual(score.confirmation_id, "REF-987654")
        self.assertTrue(score.submit_button_gone)
        self.assertEqual(score.verdict, ApplicationState.SUBMITTED_CONFIRMED)


if __name__ == "__main__":
    unittest.main()
