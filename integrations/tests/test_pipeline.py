"""Unit tests for the end-to-end JobIngestionPipeline."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from integrations.base import BaseEmailClient, BaseJobScraper
from integrations.models import EmailAccountConfig, EmailMessage, IngestedJob, JobAlertItem, NormalizedJobPosting, ScrapedJobContent
from integrations.pipeline.destinations import FileSystemStagingDestination
from integrations.pipeline.orchestrator import JobIngestionPipeline


SAMPLE_EMAIL_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div>
    <h2>New Job Alert for Software Engineer</h2>
    <div>
      <a href="https://www.linkedin.com/comm/jobs/view/4422257733/?trk=eml-job_alerts">
        Senior AI Platform Engineer
      </a>
      <div>Gorgias</div>
      <div>Paris, France (Hybrid)</div>
    </div>
    <hr>
    <div>
      <a href="https://www.linkedin.com/comm/jobs/view/9999999999/?trk=eml-job_alerts">
        Entry-Level Marketing Assistant
      </a>
      <div>Retail Co</div>
      <div>Lyon, France (On-site)</div>
    </div>
  </div>
</body>
</html>
"""

SAMPLE_GORGIAS_PAGE = """# Senior AI Platform Engineer
**Company:** Gorgias
**Location:** Paris, France (Hybrid)
**URL:** https://www.linkedin.com/jobs/view/4422257733

About Gorgias:
Gorgias is the leading AI-powered customer service platform for ecommerce.

What you will do:
- Design and build high-scale Kubernetes infrastructure and model serving pipelines.
- Develop backend services with Python, FastAPI, Docker, and PostgreSQL.
- Implement robust CI/CD workflows and monitoring with Datadog and OpenTelemetry.

What you bring:
- 4+ years of software engineering experience with Python and Linux.
- Hands-on mastery of Docker, Kubernetes, Terraform, and GCP.
- Passion for generative AI, LLM systems, and automated agent workflows.
"""

SAMPLE_MARKETING_PAGE = """# Entry-Level Marketing Assistant
**Company:** Retail Co
**Location:** Lyon, France (On-site)
**URL:** https://www.linkedin.com/jobs/view/9999999999

Responsibilities:
- Create social media flyers and brochures.
- Assist marketing team with event management.

Requirements:
- Degree in Marketing or Communications.
- Experience with Photoshop and Illustrator.
"""


class TestJobIngestionPipeline(unittest.TestCase):

    def test_denied_posting_is_not_scored_or_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = MagicMock(spec=BaseJobScraper)
            scraper.scrape.return_value = ScrapedJobContent(
                source_url="https://example.test/job/1", canonical_url="https://example.test/job/1",
                status_code=403, error_message="Access denied",
            )
            destination = MagicMock()
            pipeline = JobIngestionPipeline(
                email_client=MagicMock(spec=BaseEmailClient), scraper=scraper,
                destinations=[destination], ledger_path=Path(tmpdir)/"ledger.json",
            )
            with patch("integrations.pipeline.orchestrator.JobMatchScorer.score_job") as score:
                result = pipeline._process_single_job_alert(
                    JobAlertItem(title="Engineer", company="Example", canonical_url="https://example.test/job/1"),
                    min_score=0, dry_run=False,
                )
            self.assertEqual(result.status, "FAILED")
            score.assert_not_called()
            destination.stage_job.assert_not_called()

    def test_staging_rejects_changed_source_instead_of_replacing_its_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            posting = NormalizedJobPosting(company="Example", role="Engineer", source_sha256="0"*64)
            job = IngestedJob(job_id="1", job_data=posting, source_text="Changed evidence")
            self.assertFalse(FileSystemStagingDestination(Path(tmpdir)).stage_job(job))
            self.assertEqual(job.status, "FAILED")
            self.assertEqual(posting.source_sha256, "0"*64)
            self.assertFalse(list(Path(tmpdir).rglob("job.json")))

    def test_end_to_end_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_base = Path(tmpdir) / "staging_job"

            # 1. Mock Email Client
            mock_email_client = MagicMock(spec=BaseEmailClient)
            mock_msg = EmailMessage(
                uid="1001",
                message_id="msg-1001",
                sender="jobalerts-noreply@linkedin.com",
                recipient="candidate@example.com",
                subject="2 new jobs matching your profile",
                date_str="2026-08-26",
                body_html=SAMPLE_EMAIL_HTML,
            )
            mock_email_client.fetch_messages.return_value = [mock_msg]

            # 2. Mock Scraper
            mock_scraper = MagicMock(spec=BaseJobScraper)

            def mock_scrape_side_effect(url: str, timeout_seconds: int = 30) -> ScrapedJobContent:
                if "4422257733" in url:
                    return ScrapedJobContent(
                        source_url=url,
                        canonical_url="https://www.linkedin.com/jobs/view/4422257733",
                        title="Senior AI Platform Engineer",
                        company="Gorgias",
                        location="Paris, France",
                        visible_text=SAMPLE_GORGIAS_PAGE,
                        status_code=200,
                        used_playwright=False,
                    )
                else:
                    return ScrapedJobContent(
                        source_url=url,
                        canonical_url="https://www.linkedin.com/jobs/view/9999999999",
                        title="Entry-Level Marketing Assistant",
                        company="Retail Co",
                        location="Lyon, France",
                        visible_text=SAMPLE_MARKETING_PAGE,
                        status_code=200,
                        used_playwright=False,
                    )

            mock_scraper.scrape.side_effect = mock_scrape_side_effect

            # 3. Setup Pipeline
            destination = FileSystemStagingDestination(base_staging_dir=staging_base)
            pipeline = JobIngestionPipeline(
                email_client=mock_email_client,
                scraper=mock_scraper,
                max_experience_years=None,
                destinations=[destination],
                ledger_path=staging_base.parent / "processed_emails.json",
            )

            # 4. Run Ingestion with minimum match score 85
            result = pipeline.run_ingestion(
                limit=10,
                target_senders=["jobalerts-noreply@linkedin.com"],
                min_match_score=85,
                dry_run=False,
            )

            # Assertions
            self.assertEqual(result.total_emails_scanned, 1)
            self.assertEqual(result.total_jobs_found, 2)
            self.assertEqual(result.total_jobs_scraped, 2)
            self.assertEqual(result.total_jobs_staged, 2)  # Unassessed jobs survive the threshold.
            self.assertEqual(result.total_unassessed, 2)
            self.assertEqual(result.total_high_matches + result.total_medium_matches + result.total_low_matches, 0)

            # Inspect staged directory
            staged_dirs = list(staging_base.glob("*"))
            self.assertEqual(len(staged_dirs), 2)
            staged_folder = next(p for p in staged_dirs if json.loads((p / "job.json").read_text())["company"] == "Gorgias")

            job_json = staged_folder / "job.json"
            source_md = staged_folder / "source.md"
            match_json = staged_folder / "match_breakdown.json"

            self.assertTrue(job_json.is_file())
            self.assertTrue(source_md.is_file())
            self.assertTrue(match_json.is_file())

            job_data = json.loads(job_json.read_text(encoding="utf-8"))
            self.assertEqual(job_data["company"], "Gorgias")
            self.assertEqual(job_data["role"], "Senior AI Platform Engineer")
            self.assertEqual(job_data["source_job_id"], "4422257733")
            source = source_md.read_text(encoding="utf-8")
            self.assertIn("Design and build high-scale Kubernetes infrastructure", source)
            self.assertEqual(job_data["source_sha256"], hashlib.sha256(source_md.read_bytes()).hexdigest())
            for quotes in job_data["field_evidence"].values():
                for quote in quotes:
                    self.assertIn(quote, source)

            match_data = json.loads(match_json.read_text(encoding="utf-8"))
            self.assertIsNone(match_data["total_score"])
            self.assertFalse(match_data["assessed"])

    def test_dry_run_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_base = Path(tmpdir) / "staging_job"

            mock_email_client = MagicMock(spec=BaseEmailClient)
            mock_msg = EmailMessage(
                uid="1002",
                message_id="msg-1002",
                sender="jobalerts-noreply@linkedin.com",
                recipient="candidate@example.com",
                subject="1 job alert",
                date_str="2026-08-26",
                body_html=SAMPLE_EMAIL_HTML,
            )
            mock_email_client.fetch_messages.return_value = [mock_msg]

            mock_scraper = MagicMock(spec=BaseJobScraper)
            mock_scraper.scrape.return_value = ScrapedJobContent(
                source_url="https://www.linkedin.com/jobs/view/4422257733",
                canonical_url="https://www.linkedin.com/jobs/view/4422257733",
                title="Senior AI Platform Engineer",
                company="Gorgias",
                location="Paris, France",
                visible_text=SAMPLE_GORGIAS_PAGE,
                status_code=200,
            )

            destination = FileSystemStagingDestination(base_staging_dir=staging_base)
            pipeline = JobIngestionPipeline(
                email_client=mock_email_client,
                scraper=mock_scraper,
                destinations=[destination],
                ledger_path=staging_base.parent / "processed_emails.json",
            )

            result = pipeline.run_ingestion(dry_run=True)

            self.assertEqual(result.total_jobs_staged, 0)
            self.assertFalse(staging_base.exists() and list(staging_base.glob("*")))

    def test_targeted_ids_bypass_mailbox_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            staging_base = Path(tmpdir) / "staging_job"

            mock_msg = EmailMessage(
                uid="gmail-1",
                message_id="msg-gmail-1",
                sender="jobalerts-noreply@linkedin.com",
                recipient="candidate@example.com",
                subject="1 job alert",
                date_str="2026-08-26",
                body_html=SAMPLE_EMAIL_HTML,
            )
            mock_email_client = MagicMock(spec=BaseEmailClient)
            mock_email_client.fetch_message.side_effect = lambda gid: (
                mock_msg if gid == "gmail-1" else None
            )

            mock_scraper = MagicMock(spec=BaseJobScraper)
            mock_scraper.scrape.return_value = ScrapedJobContent(
                source_url="https://www.linkedin.com/jobs/view/4422257733",
                canonical_url="https://www.linkedin.com/jobs/view/4422257733",
                title="Senior AI Platform Engineer",
                company="Gorgias",
                location="Paris, France",
                visible_text=SAMPLE_GORGIAS_PAGE,
                status_code=200,
            )

            destination = FileSystemStagingDestination(base_staging_dir=staging_base)
            pipeline = JobIngestionPipeline(
                email_client=mock_email_client,
                scraper=mock_scraper,
                max_experience_years=None,
                destinations=[destination],
                ledger_path=staging_base.parent / "processed_emails.json",
            )

            result = pipeline.run_ingestion(
                only_gmail_ids=["gmail-1", "missing-id"], min_match_score=0
            )

            mock_email_client.fetch_messages.assert_not_called()
            self.assertEqual(result.total_emails_scanned, 1)
            self.assertEqual(result.total_jobs_staged, 2)

            # Redelivery of the same push is a ledger hit, not reprocessing.
            redelivery = pipeline.run_ingestion(only_gmail_ids=["gmail-1"])
            self.assertEqual(redelivery.total_emails_skipped_already_checked, 1)
            self.assertEqual(redelivery.total_jobs_staged, 0)


if __name__ == "__main__":
    unittest.main()
