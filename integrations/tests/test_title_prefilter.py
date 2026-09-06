"""Unit tests for JobTitlePrefilter and pipeline zero-token title gating."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from integrations.base import BaseEmailClient, BaseJobScraper
from integrations.models import EmailMessage, NormalizedJobPosting, ScrapedJobContent
from integrations.pipeline.destinations import FileSystemStagingDestination
from integrations.pipeline.orchestrator import JobIngestionPipeline
from integrations.pipeline.title_prefilter import (
    DEFAULT_EXCLUDED_TITLE_PATTERNS,
    JobTitlePrefilter,
    TitleFilterDecision,
    filter_job_by_title,
)


class TestJobTitlePrefilter(unittest.TestCase):

    def setUp(self) -> None:
        self.prefilter = JobTitlePrefilter()

    def test_default_excluded_titles_chef(self) -> None:
        chef_titles = [
            "Chef de projet informatique",
            "Chef de projet Etude et dev",
            "Chef.fe de projets informatique bâtimentaire",
            "Cheffe de projet digital",
            "Chef(fe) de service SI",
            "Chef-fe de projet réseau",
            "Chefs de projet SI",
            "CHEF DE PROJET DATA",
        ]
        for title in chef_titles:
            decision = self.prefilter.evaluate(title)
            self.assertFalse(decision.passed, f"Expected '{title}' to be rejected by title prefilter")
            self.assertIsNotNone(decision.matched_pattern)

    def test_default_excluded_titles_manager(self) -> None:
        manager_titles = [
            "Engineering Manager",
            "Project Manager",
            "IT Operations Manager",
            "Product Manager",
            "Managers de transition",
            "Lead Cloud Architect & Management",
            "Managing Consultant",
            "PROGRAM MANAGER",
        ]
        for title in manager_titles:
            decision = self.prefilter.evaluate(title)
            self.assertFalse(decision.passed, f"Expected '{title}' to be rejected by title prefilter")
            self.assertIsNotNone(decision.matched_pattern)

    def test_allowed_technical_titles(self) -> None:
        allowed_titles = [
            "Développeur Fullstack Python / Django",
            "Software Engineer - Backend",
            "Data Engineer",
            "Data Analyst",
            "Administrateur Systèmes et Réseaux",
            "Technicien Support Informatique",
            "DevOps Engineer",
            "Consultant Cybersécurité",
            "Architecte Cloud AWS",
            "Stagiaire Développeur Web",
            "Alternant Ingénieur Logiciel",
            "Lead Developer Python",
        ]
        for title in allowed_titles:
            decision = self.prefilter.evaluate(title)
            self.assertTrue(decision.passed, f"Expected '{title}' to pass title prefilter")
            self.assertIsNone(decision.matched_pattern)

    def test_evaluate_job_dict_and_model(self) -> None:
        job_dict = {"role": "Chef de projet SI", "company": "Acme"}
        decision = self.prefilter.evaluate_job(job_dict)
        self.assertFalse(decision.passed)

        job_posting = NormalizedJobPosting(
            source_job_id="test-1",
            role="Développeur Python",
            company="Acme",
            location="Paris",
            source_url="https://example.com/job",
            source="test",
        )
        decision2 = self.prefilter.evaluate_job(job_posting)
        self.assertTrue(decision2.passed)

    def test_filter_job_by_title_convenience_function(self) -> None:
        decision_pass = filter_job_by_title({"role": "Ingénieur DevOps"})
        self.assertTrue(decision_pass.passed)

        decision_reject = filter_job_by_title({"role": "Chef de projet"})
        self.assertFalse(decision_reject.passed)

    def test_disabled_prefilter(self) -> None:
        disabled_prefilter = JobTitlePrefilter(enabled=False)
        decision = disabled_prefilter.evaluate("Chef de projet informatique")
        self.assertTrue(decision.passed)
        self.assertIn("disabled", decision.reason.lower())

    def test_custom_excluded_patterns(self) -> None:
        custom_prefilter = JobTitlePrefilter(excluded_patterns=[r"\b(?:directeur|directrice)\b"])
        self.assertTrue(custom_prefilter.evaluate("Chef de projet").passed)
        self.assertFalse(custom_prefilter.evaluate("Directeur Technique").passed)


class TestPipelineTitlePrefilterIntegration(unittest.TestCase):

    def test_pipeline_skips_scoring_for_chef_or_manager_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_base = Path(tmpdir) / "staging_job"

            mock_email_client = MagicMock(spec=BaseEmailClient)
            email_html = """
            <!DOCTYPE html><html><body>
            <div>
              <a href="https://www.linkedin.com/comm/jobs/view/88888888">Chef de projet informatique</a>
              <div>Big Corp</div><div>Paris, France</div>
            </div>
            </body></html>
            """
            mock_msg = EmailMessage(
                uid="3002",
                message_id="msg-3002",
                sender="jobalerts-noreply@linkedin.com",
                recipient="candidate@example.com",
                subject="1 job alert",
                date_str="2026-09-04",
                body_html=email_html,
            )
            mock_email_client.fetch_messages.return_value = [mock_msg]

            mock_scraper = MagicMock(spec=BaseJobScraper)
            mock_scraper.scrape.return_value = ScrapedJobContent(
                source_url="https://www.linkedin.com/jobs/view/88888888",
                canonical_url="https://www.linkedin.com/jobs/view/88888888",
                title="Chef de projet informatique",
                company="Big Corp",
                location="Paris, France",
                visible_text="Chef de projet informatique pour piloter les projets applicatifs.",
                status_code=200,
            )

            destination = FileSystemStagingDestination(base_staging_dir=staging_base)

            pipeline = JobIngestionPipeline(
                email_client=mock_email_client,
                scraper=mock_scraper,
                enable_title_prefilter=True,
                destinations=[destination],
                ledger_path=staging_base.parent / "processed_emails.json",
            )

            result = pipeline.run_ingestion(min_match_score=60)

            self.assertEqual(result.total_jobs_scraped, 1)
            self.assertEqual(result.total_jobs_staged, 0)
            self.assertEqual(len(result.jobs), 1)
            self.assertEqual(result.jobs[0].status, "SKIPPED")
            self.assertIn("Title prefilter:", result.jobs[0].notes)
            self.assertEqual(result.jobs[0].match_score, 0)


if __name__ == "__main__":
    unittest.main()
