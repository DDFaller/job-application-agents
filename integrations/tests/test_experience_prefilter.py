"""Unit tests for JobExperiencePrefilter and pipeline zero-token experience gating."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from integrations.base import BaseEmailClient, BaseJobScraper
from integrations.models import EmailMessage, NormalizedJobPosting, ScrapedJobContent
from integrations.pipeline.destinations import FileSystemStagingDestination
from integrations.pipeline.experience_prefilter import (
    ExperienceFilterDecision,
    JobExperiencePrefilter,
    filter_job_by_experience,
    parse_experience_years,
)
from integrations.pipeline.orchestrator import JobIngestionPipeline


class TestExperienceParser(unittest.TestCase):

    def test_parse_france_travail_patterns(self) -> None:
        self.assertEqual(parse_experience_years("Expérience exigée de 1 An(s)"), 1.0)
        self.assertEqual(parse_experience_years("Expérience exigée de 2 An(s)"), 2.0)
        self.assertEqual(parse_experience_years("Expérience souhaitée de 3 An(s)"), 3.0)
        self.assertEqual(parse_experience_years("Expérience exigée de 6 Mois"), 0.5)
        self.assertEqual(parse_experience_years("Débutant accepté"), 0.0)
        self.assertEqual(parse_experience_years("Débutant accepté (0)"), 0.0)

    def test_parse_general_french_patterns(self) -> None:
        self.assertEqual(parse_experience_years("1 an d'expérience minimum"), 1.0)
        self.assertEqual(parse_experience_years("2 ans d'expérience"), 2.0)
        self.assertEqual(parse_experience_years("3 à 5 ans d'expérience"), 3.0)
        self.assertEqual(parse_experience_years("Expérience requise : 2 ans"), 2.0)
        self.assertEqual(parse_experience_years("Expérience d'au moins 3 ans"), 3.0)
        self.assertEqual(parse_experience_years("Profil junior / débutant"), 0.0)

    def test_parse_english_patterns(self) -> None:
        self.assertEqual(parse_experience_years("1+ year of experience with Python"), 1.0)
        self.assertEqual(parse_experience_years("5+ years of software engineering experience"), 5.0)
        self.assertEqual(parse_experience_years("1-2 years of experience"), 1.0)
        self.assertEqual(parse_experience_years("Minimum 3 years of hands-on experience"), 3.0)
        self.assertEqual(parse_experience_years("Experience required: 2 years"), 2.0)
        self.assertEqual(parse_experience_years("Entry-level role, no experience required"), 0.0)

    def test_parse_wttj_and_operator_patterns(self) -> None:
        self.assertEqual(parse_experience_years("> 5 ans"), 5.0)
        self.assertEqual(parse_experience_years("> 4 ans"), 4.0)
        self.assertEqual(parse_experience_years("> 6 mois"), 0.5)
        self.assertEqual(parse_experience_years("Expérience :\n> 5 ans"), 5.0)
        self.assertEqual(parse_experience_years("Expérience : > 5 ans"), 5.0)
        self.assertEqual(parse_experience_years("Expérience : > 6 mois"), 0.5)
        self.assertEqual(parse_experience_years("&gt; 5 ans"), 5.0)
        self.assertEqual(parse_experience_years("0 à 1 an"), 0.0)
        self.assertEqual(parse_experience_years("1 à 2 ans"), 1.0)
        self.assertEqual(parse_experience_years("3 à 5 ans"), 3.0)
        self.assertEqual(parse_experience_years("Expérience : Débutant"), 0.0)
    def test_parse_word_numbers_and_user_cases(self) -> None:
        self.assertEqual(
            parse_experience_years("Titulaire d’un diplôme de formation supérieure de type bac + 5 en informatique, vous justifiez au minimum de cinq années d’expérience au sein d’une DSI."),
            5.0,
        )
        self.assertEqual(
            parse_experience_years("Expérience\n5 An(s)    Cette expérience est indispensable"),
            5.0,
        )
        self.assertEqual(parse_experience_years("Expérience 5 An(s)"), 5.0)
        self.assertEqual(parse_experience_years("Expérience: 5 An(s)"), 5.0)
        self.assertEqual(parse_experience_years("Expérience\n5 An(s)"), 5.0)
        self.assertEqual(parse_experience_years("vous justifiez d'au moins 3 ans d'expérience"), 3.0)
        self.assertEqual(parse_experience_years("justifiant de deux années d'expérience"), 2.0)
        self.assertEqual(parse_experience_years("minimum of five years of experience in cloud"), 5.0)
        self.assertEqual(parse_experience_years("at least three years of experience"), 3.0)
        self.assertEqual(parse_experience_years("dix ans d'expérience"), 10.0)

    def test_parse_empty_or_unspecified(self) -> None:
        self.assertIsNone(parse_experience_years(None))
        self.assertIsNone(parse_experience_years(""))
        self.assertIsNone(parse_experience_years("Collaborate with engineering teams"))


class TestJobExperiencePrefilter(unittest.TestCase):

    def setUp(self) -> None:
        # Default prefilter (max_experience_years defaults to 1.0)
        self.prefilter = JobExperiencePrefilter(max_experience_years=1.0)

    def test_default_is_one_year(self) -> None:
        self.assertEqual(self.prefilter.max_experience_years, 1.0)

    def test_entry_level_and_one_year_pass(self) -> None:
        # 0 years (beginner) -> PASS
        decision_beg = self.prefilter.evaluate(experience_text="Débutant accepté")
        self.assertTrue(decision_beg.passed)
        self.assertEqual(decision_beg.required_years, 0.0)

        # 1 year -> PASS
        decision_1yr = self.prefilter.evaluate(experience_text="Expérience exigée de 1 An(s)")
        self.assertTrue(decision_1yr.passed)
        self.assertEqual(decision_1yr.required_years, 1.0)

        # 6 months -> PASS
        decision_6m = self.prefilter.evaluate(experience_text="Expérience exigée de 6 Mois")
        self.assertTrue(decision_6m.passed)
        self.assertEqual(decision_6m.required_years, 0.5)

    def test_senior_or_multi_year_rejected_by_default(self) -> None:
        # 2 years -> FAIL with default max 1.0 year
        decision_2yr = self.prefilter.evaluate(experience_text="Expérience exigée de 2 An(s)")
        self.assertFalse(decision_2yr.passed)
        self.assertEqual(decision_2yr.required_years, 2.0)
        self.assertIn("exceeds maximum allowed threshold of 1 year", decision_2yr.reason)

        # 5+ years -> FAIL
        decision_5yr = self.prefilter.evaluate(experience_text="5+ years of software engineering experience")
        self.assertFalse(decision_5yr.passed)
        self.assertEqual(decision_5yr.required_years, 5.0)

    def test_runtime_max_experience_override_in_evaluate(self) -> None:
        # Override to 3 years on a 2-year required posting -> PASS
        decision = self.prefilter.evaluate(
            experience_text="2 ans d'expérience",
            max_experience_years=3.0,
        )
        self.assertTrue(decision.passed)
        self.assertEqual(decision.required_years, 2.0)

        # Override to 0.5 years on a 1-year posting -> FAIL
        decision_strict = self.prefilter.evaluate(
            experience_text="1 an d'expérience",
            max_experience_years=0.5,
        )
        self.assertFalse(decision_strict.passed)
        self.assertEqual(decision_strict.required_years, 1.0)

    def test_unspecified_experience_passes_by_default(self) -> None:
        decision = self.prefilter.evaluate(experience_text=None)
        self.assertTrue(decision.passed)
        self.assertIn("No explicit experience requirement", decision.reason)

    def test_disabled_experience_filter(self) -> None:
        prefilter_disabled = JobExperiencePrefilter(max_experience_years=None)
        decision = prefilter_disabled.evaluate(experience_text="10 years of experience")
        self.assertTrue(decision.passed)

    def test_evaluate_job_model(self) -> None:
        junior_job = NormalizedJobPosting(
            company="Startup Inc",
            role="Junior Developer",
            experience_level="Débutant accepté",
            experience_years=0.0,
        )
        self.assertTrue(self.prefilter.evaluate_job(junior_job).passed)

        senior_job = NormalizedJobPosting(
            company="Tech Giant",
            role="Senior Architect",
            experience_level="5+ years of experience",
            experience_years=5.0,
        )
        self.assertFalse(self.prefilter.evaluate_job(senior_job).passed)

        # Overriding max_experience_years to 5.0 allows senior_job
        self.assertTrue(self.prefilter.evaluate_job(senior_job, max_experience_years=5.0).passed)

    def test_filter_job_by_experience_helper_function(self) -> None:
        job_1yr = {"company": "Test", "role": "Junior Backend", "requirements": ["1 year experience with Python"]}
        res1 = filter_job_by_experience(job_1yr)
        self.assertTrue(res1.passed)

        job_3yr = {"company": "Test", "role": "Mid Backend", "requirements": ["3 years experience with Python"]}
        res3 = filter_job_by_experience(job_3yr)
        self.assertFalse(res3.passed)

        # Custom threshold 3.0 years
        res3_custom = filter_job_by_experience(job_3yr, max_experience_years=3.0)
        self.assertTrue(res3_custom.passed)


class TestPipelineExperiencePrefilterIntegration(unittest.TestCase):

    def test_pipeline_skips_llm_scoring_for_high_experience_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_base = Path(tmpdir) / "staging_job"

            mock_email_client = MagicMock(spec=BaseEmailClient)
            email_html = """
            <!DOCTYPE html><html><body>
            <div>
              <a href="https://www.linkedin.com/comm/jobs/view/99999999">Lead Cloud Architect</a>
              <div>Big Corp</div><div>Paris, France</div>
            </div>
            </body></html>
            """
            mock_msg = EmailMessage(
                uid="3001",
                message_id="msg-3001",
                sender="jobalerts-noreply@linkedin.com",
                recipient="candidate@example.com",
                subject="1 job alert",
                date_str="2026-09-04",
                body_html=email_html,
            )
            mock_email_client.fetch_messages.return_value = [mock_msg]

            # Scraped page returns 5+ years experience required
            mock_scraper = MagicMock(spec=BaseJobScraper)
            mock_scraper.scrape.return_value = ScrapedJobContent(
                source_url="https://www.linkedin.com/jobs/view/99999999",
                canonical_url="https://www.linkedin.com/jobs/view/99999999",
                title="Lead Cloud Architect",
                company="Big Corp",
                location="Paris, France",
                visible_text="Requirements:\n- 5+ years of cloud architecture experience\n- Python and Kubernetes.",
                meta_tags={"experience": "5+ years"},
                status_code=200,
            )

            destination = FileSystemStagingDestination(base_staging_dir=staging_base)

            pipeline = JobIngestionPipeline(
                email_client=mock_email_client,
                scraper=mock_scraper,
                max_experience_years=1.0,
                destinations=[destination],
                ledger_path=staging_base.parent / "processed_emails.json",
            )

            result = pipeline.run_ingestion(min_match_score=60)

            # Assertions: LLM scoring skipped, status SKIPPED with experience prefilter note
            self.assertEqual(result.total_jobs_scraped, 1)
            self.assertEqual(result.total_jobs_staged, 0)
            self.assertEqual(len(result.jobs), 1)
            self.assertEqual(result.jobs[0].status, "SKIPPED")
            self.assertIn("Experience prefilter:", result.jobs[0].notes)
            self.assertEqual(result.jobs[0].match_score, 0)


if __name__ == "__main__":
    unittest.main()
