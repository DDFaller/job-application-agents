"""Unit tests for JobDatePrefilter and pipeline zero-token date gating."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from integrations.base import BaseEmailClient, BaseJobScraper
from integrations.models import EmailMessage, NormalizedJobPosting, ScrapedJobContent
from integrations.pipeline.date_prefilter import (
    DateFilterDecision,
    JobDatePrefilter,
    filter_job_by_date,
    parse_date_to_date_obj,
)
from integrations.pipeline.destinations import FileSystemStagingDestination
from integrations.pipeline.orchestrator import JobIngestionPipeline


class TestDateParser(unittest.TestCase):

    def test_parse_date_formats(self) -> None:
        self.assertEqual(parse_date_to_date_obj("2026-09-02"), date(2026, 9, 2))
        self.assertEqual(parse_date_to_date_obj("2026-09-02T14:30:00Z"), date(2026, 9, 2))
        self.assertEqual(parse_date_to_date_obj("02/09/2026"), date(2026, 9, 2))
        self.assertEqual(parse_date_to_date_obj("02-09-2026"), date(2026, 9, 2))
        self.assertEqual(parse_date_to_date_obj(date(2026, 9, 2)), date(2026, 9, 2))
        self.assertEqual(parse_date_to_date_obj(datetime(2026, 9, 2, 10, 0, 0)), date(2026, 9, 2))
        self.assertIsNone(parse_date_to_date_obj(None))
        self.assertIsNone(parse_date_to_date_obj(""))
        self.assertIsNone(parse_date_to_date_obj("invalid-date"))


class TestJobDatePrefilter(unittest.TestCase):

    def setUp(self) -> None:
        # Freeze reference date to 2026-09-04 for deterministic tests
        self.ref_date = date(2026, 9, 4)
        # Default prefilter (max_posting_age_days defaults to 7)
        self.prefilter = JobDatePrefilter(
            reference_date=self.ref_date,
        )

    def test_default_is_seven_days(self) -> None:
        self.assertEqual(self.prefilter.max_posting_age_days, 7)

    def test_fresh_job_passes_within_7_days(self) -> None:
        # Posted 2 days ago (2026-09-02) -> should PASS
        decision = self.prefilter.evaluate(posted_at="2026-09-02")
        self.assertTrue(decision.passed)
        self.assertEqual(decision.age_days, 2)

    def test_job_older_than_7_days_rejected_by_default(self) -> None:
        # Posted 10 days ago (2026-08-25) -> should FAIL with default 7 days limit
        decision = self.prefilter.evaluate(posted_at="2026-08-25")
        self.assertFalse(decision.passed)
        self.assertEqual(decision.age_days, 10)
        self.assertIn("exceeding max age of 7 days", decision.reason)

    def test_runtime_max_posting_age_override_in_evaluate(self) -> None:
        # Override to 14 days on an 8-day old posting
        decision = self.prefilter.evaluate(posted_at="2026-08-27", max_posting_age_days=14)
        self.assertTrue(decision.passed)
        self.assertEqual(decision.age_days, 8)

        # Override to 1 day on a 2-day old posting
        decision_strict = self.prefilter.evaluate(posted_at="2026-09-02", max_posting_age_days=1)
        self.assertFalse(decision_strict.passed)
        self.assertEqual(decision_strict.age_days, 2)
        self.assertIn("exceeding max age of 1 days", decision_strict.reason)

    def test_expired_deadline_rejected(self) -> None:
        # Deadline was 4 days ago
        decision = self.prefilter.evaluate(posted_at="2026-09-01", closes_at="2026-08-31")
        self.assertFalse(decision.passed)
        self.assertIn("Application deadline expired", decision.reason)

    def test_future_deadline_passes(self) -> None:
        # Deadline in 6 days
        decision = self.prefilter.evaluate(posted_at="2026-09-01", closes_at="2026-09-10")
        self.assertTrue(decision.passed)
        self.assertEqual(decision.days_until_deadline, 6)

    def test_future_posting_anomaly_rejected(self) -> None:
        # Posted 10 days in the future
        decision = self.prefilter.evaluate(posted_at="2026-09-14")
        self.assertFalse(decision.passed)
        self.assertIn("Anomalous future post date", decision.reason)

    def test_disabled_max_age(self) -> None:
        prefilter_no_age = JobDatePrefilter(
            max_posting_age_days=None,
            reject_expired_deadlines=True,
            reference_date=self.ref_date,
        )
        decision = prefilter_no_age.evaluate(posted_at="2025-01-01")
        self.assertTrue(decision.passed)

    def test_disabled_deadline_check(self) -> None:
        prefilter_no_deadline = JobDatePrefilter(
            max_posting_age_days=7,
            reject_expired_deadlines=False,
            reference_date=self.ref_date,
        )
        decision = prefilter_no_deadline.evaluate(posted_at="2026-09-01", closes_at="2026-08-01")
        self.assertTrue(decision.passed)

    def test_evaluate_job_model_with_custom_param(self) -> None:
        fresh_posting = NormalizedJobPosting(
            company="Test Corp",
            role="Backend Engineer",
            posted_at="2026-09-02",
            closes_at="2026-09-30",
        )
        decision = self.prefilter.evaluate_job(fresh_posting)
        self.assertTrue(decision.passed)

        older_posting = NormalizedJobPosting(
            company="Test Corp",
            role="Backend Engineer",
            posted_at="2026-08-20",
        )
        # Default 7 days rejects it
        decision_stale = self.prefilter.evaluate_job(older_posting)
        self.assertFalse(decision_stale.passed)

        # Passing max_posting_age_days=30 allows it
        decision_allowed = self.prefilter.evaluate_job(older_posting, max_posting_age_days=30)
        self.assertTrue(decision_allowed.passed)

    def test_filter_job_by_date_helper_function(self) -> None:
        # Test convenience function with default 7 days
        job_dict_fresh = {
            "company": "Test Corp",
            "role": "Data Scientist",
            "posted_at": "2026-09-03",
        }
        res_fresh = filter_job_by_date(job_dict_fresh, reference_date=self.ref_date)
        self.assertTrue(res_fresh.passed)
        self.assertEqual(res_fresh.age_days, 1)

        job_dict_older = {
            "company": "Test Corp",
            "role": "Data Scientist",
            "posted_at": "2026-08-25",
        }
        # 10 days old with default 7 days -> FAIL
        res_older_def = filter_job_by_date(job_dict_older, reference_date=self.ref_date)
        self.assertFalse(res_older_def.passed)

        # 10 days old with custom 15 days -> PASS
        res_older_custom = filter_job_by_date(
            job_dict_older,
            max_posting_age_days=15,
            reference_date=self.ref_date,
        )
        self.assertTrue(res_older_custom.passed)


class TestPipelineDatePrefilterIntegration(unittest.TestCase):

    def test_pipeline_skips_llm_scoring_for_stale_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_base = Path(tmpdir) / "staging_job"

            mock_email_client = MagicMock(spec=BaseEmailClient)
            email_html = """
            <!DOCTYPE html><html><body>
            <div>
              <a href="https://www.linkedin.com/comm/jobs/view/12345678">Senior Python Engineer</a>
              <div>Old Corp</div><div>Paris, France</div>
            </div>
            </body></html>
            """
            mock_msg = EmailMessage(
                uid="2001",
                message_id="msg-2001",
                sender="jobalerts-noreply@linkedin.com",
                recipient="candidate@example.com",
                subject="1 job alert",
                date_str="2026-09-04",
                body_html=email_html,
            )
            mock_email_client.fetch_messages.return_value = [mock_msg]

            # Scraped page returns an old post date: 2026-05-01 (over 120 days ago)
            mock_scraper = MagicMock(spec=BaseJobScraper)
            mock_scraper.scrape.return_value = ScrapedJobContent(
                source_url="https://www.linkedin.com/jobs/view/12345678",
                canonical_url="https://www.linkedin.com/jobs/view/12345678",
                title="Senior Python Engineer",
                company="Old Corp",
                location="Paris, France",
                visible_text="Date de publication : 01/05/2026\n\nSoftware Engineer details...",
                meta_tags={"posted_at": "2026-05-01"},
                status_code=200,
            )

            destination = FileSystemStagingDestination(base_staging_dir=staging_base)
            prefilter = JobDatePrefilter(max_posting_age_days=7, reference_date=date(2026, 9, 4))

            pipeline = JobIngestionPipeline(
                email_client=mock_email_client,
                scraper=mock_scraper,
                date_prefilter=prefilter,
                destinations=[destination],
                ledger_path=staging_base.parent / "processed_emails.json",
            )

            result = pipeline.run_ingestion(min_match_score=60)

            # Assertions: Staged count is 0, job status is SKIPPED with date prefilter reason
            self.assertEqual(result.total_jobs_scraped, 1)
            self.assertEqual(result.total_jobs_staged, 0)
            self.assertEqual(len(result.jobs), 1)
            self.assertEqual(result.jobs[0].status, "SKIPPED")
            self.assertIn("Date prefilter:", result.jobs[0].notes)
            self.assertEqual(result.jobs[0].match_score, 0)  # LLM scoring was completely skipped!

    def test_pipeline_run_ingestion_with_custom_max_age(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_base = Path(tmpdir) / "staging_job"

            mock_email_client = MagicMock(spec=BaseEmailClient)
            email_html = """
            <!DOCTYPE html><html><body>
            <div>
              <a href="https://www.linkedin.com/comm/jobs/view/12345678">Senior Python Engineer</a>
              <div>Recent Corp</div><div>Paris, France</div>
            </div>
            </body></html>
            """
            mock_msg = EmailMessage(
                uid="2002",
                message_id="msg-2002",
                sender="jobalerts-noreply@linkedin.com",
                recipient="candidate@example.com",
                subject="1 job alert",
                date_str="2026-09-04",
                body_html=email_html,
            )
            mock_email_client.fetch_messages.return_value = [mock_msg]

            # Job posted 5 days ago (2026-08-30)
            mock_scraper = MagicMock(spec=BaseJobScraper)
            mock_scraper.scrape.return_value = ScrapedJobContent(
                source_url="https://www.linkedin.com/jobs/view/12345678",
                canonical_url="https://www.linkedin.com/jobs/view/12345678",
                title="Senior Python Engineer",
                company="Recent Corp",
                location="Paris, France",
                visible_text="Date de publication : 30/08/2026\n\nSoftware Engineer details...",
                meta_tags={"posted_at": "2026-08-30"},
                status_code=200,
            )

            destination = FileSystemStagingDestination(base_staging_dir=staging_base)
            prefilter = JobDatePrefilter(max_posting_age_days=7, reference_date=date(2026, 9, 4))

            pipeline = JobIngestionPipeline(
                email_client=mock_email_client,
                scraper=mock_scraper,
                date_prefilter=prefilter,
                destinations=[destination],
                ledger_path=staging_base.parent / "processed_emails.json",
            )

            # Pass custom strict max_posting_age_days=3 at runtime -> should skip 5-day old job
            result = pipeline.run_ingestion(min_match_score=60, max_posting_age_days=3)
            self.assertEqual(result.total_jobs_scraped, 1)
            self.assertEqual(result.jobs[0].status, "SKIPPED")
            self.assertIn("exceeding max age of 3 days", result.jobs[0].notes)


if __name__ == "__main__":
    unittest.main()

