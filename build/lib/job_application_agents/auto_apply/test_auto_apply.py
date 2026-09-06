from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from job_application_agents.auto_apply.models import CandidateProfile, FormFillResult, SubmissionReceipt
from job_application_agents.auto_apply.drivers.base import BaseFormDriver
from job_application_agents.auto_apply.drivers.lever import LeverFormDriver
from job_application_agents.auto_apply.drivers.ashby import AshbyFormDriver
from job_application_agents.auto_apply.drivers.greenhouse import GreenhouseFormDriver
from job_application_agents.auto_apply.drivers.generic import GenericFormDriver
from job_application_agents.auto_apply.drivers import DriverRegistry
from job_application_agents.auto_apply.service import AutoApplyService, SUBMISSION_CONFIRMATION, validate_public_target_url


class TestAutoApplyModels(unittest.TestCase):
    def test_candidate_profile_roundtrip(self):
        data = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "phone": "+1234567890",
            "location": "San Francisco, CA",
            "linkedin_url": "https://linkedin.com/in/janedoe",
            "github_url": "https://github.com/janedoe",
            "portfolio_url": "https://janedoe.dev",
            "notice_period_weeks": 2,
        }
        profile = CandidateProfile.from_dict(data)
        self.assertEqual(profile.full_name, "Jane Doe")
        self.assertEqual(profile.email, "jane@example.com")
        self.assertEqual(profile.notice_period_weeks, 2)

    def test_submission_receipt_serialization(self):
        receipt = SubmissionReceipt(
            success=True,
            driver_name="lever",
            job_url="https://jobs.lever.co/test/123",
            applied_at="2026-08-26T00:00:00Z",
            confirmation_text="Thank you for applying",
        )
        d = receipt.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["driver_name"], "lever")
        self.assertEqual(d["confirmation_text"], "Thank you for applying")


class TestDriverRouting(unittest.TestCase):
    def setUp(self):
        self.registry = DriverRegistry()

    def test_routes_lever_url(self):
        driver = self.registry.resolve("https://jobs.lever.co/openai/123-abc")
        self.assertIsInstance(driver, LeverFormDriver)

    def test_routes_ashby_url(self):
        driver = self.registry.resolve("https://jobs.ashbyhq.com/gorgias/456-def")
        self.assertIsInstance(driver, AshbyFormDriver)

    def test_routes_greenhouse_url(self):
        driver = self.registry.resolve("https://boards.greenhouse.io/stripe/jobs/789")
        self.assertIsInstance(driver, GreenhouseFormDriver)

    def test_routes_unknown_to_generic(self):
        driver = self.registry.resolve("https://company.careers.com/job/001")
        self.assertIsInstance(driver, GenericFormDriver)


class TestMockDriverExecution(unittest.TestCase):
    def test_mock_lever_form_fill(self):
        driver = LeverFormDriver()
        mock_page = MagicMock()
        mock_page.url = "https://jobs.lever.co/company/role"

        # Setup mock locators
        mock_locator = MagicMock()
        mock_locator.is_visible.return_value = True
        mock_locator.count.return_value = 1
        mock_locator.first = mock_locator
        mock_page.locator.return_value = mock_locator



        candidate = CandidateProfile(
            first_name="John",
            last_name="Smith",
            email="john@example.com",
            phone="+33600000000",
            location="Paris",
            linkedin_url="https://linkedin.com/in/johnsmith",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            resume_pdf = tmp_path / "resume.pdf"
            resume_pdf.write_bytes(b"%PDF-1.4 mock")

            result = driver.fill_form(
                page=mock_page,
                candidate=candidate,
                resume_pdf=resume_pdf,
            )

            self.assertTrue(result.success)
            self.assertTrue(result.resume_uploaded)
            self.assertIn("name", result.fields_filled)
            self.assertIn("email", result.fields_filled)


class TestHandsOffGuards(unittest.TestCase):
    def test_target_url_must_be_http_or_https(self) -> None:
        self.assertEqual(
            validate_public_target_url("https://jobs.example.test/role"),
            "https://jobs.example.test/role",
        )
        for value in ("javascript:alert(1)", "file:///tmp/job", "not-a-url"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_public_target_url(value)

    def test_submission_opt_in_requires_exact_environment_gate(self) -> None:
        service = AutoApplyService()
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(PermissionError):
                service.apply(
                    app_dir=Path(tmpdir),
                    mode="supervised",
                    allow_submission=True,
                )
        self.assertEqual(SUBMISSION_CONFIRMATION, "I_UNDERSTAND_SUBMISSION")


if __name__ == "__main__":
    unittest.main()
