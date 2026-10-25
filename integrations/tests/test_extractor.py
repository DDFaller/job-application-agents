"""Unit tests for JobPostingExtractor and compliance with validate_job.py."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from integrations.models import JobAlertItem, ScrapedJobContent
from integrations.scrapers.extractor import JobPostingExtractor

SAMPLE_FULL_JOB_TEXT = """# Senior AI Platform Engineer
**Company:** Mistral AI
**Location:** Paris, France (Hybrid)
**URL:** https://www.linkedin.com/jobs/view/4159823451

About the job
Mistral AI is looking for an exceptional Senior AI Platform Engineer to join our Core Infrastructure team in Paris.

Responsibilities:
- Build and operate large-scale Kubernetes clusters running PyTorch and Triton serving.
- Implement automated CI/CD pipelines using GitHub Actions and Docker containers.
- Collaborate with research scientists to deploy LLMs and generative AI foundation models.
- Optimize distributed storage with PostgreSQL, Redis, and BigQuery.

Requirements:
- 5+ years of software engineering experience with Python and Linux.
- Strong hands-on proficiency with Docker, Kubernetes, Terraform, and GCP or AWS.
- Solid understanding of distributed systems, networking, and high availability.
- Excellent communication skills in English.

Preferred Skills:
- Experience with Playwright or frontend monitoring tools.
- Familiarity with Datadog and OpenTelemetry instrumentation.
"""


class TestJobPostingExtractor(unittest.TestCase):

    def test_unstructured_posting_does_not_invent_missing_facts(self) -> None:
        scraped = ScrapedJobContent(
            source_url="https://example.test/jobs/1", canonical_url="https://example.test/jobs/1",
            title="Engineer", company="Example",
            visible_text="Our team builds Python services for customers. Contact us to learn more.",
        )
        posting, source = JobPostingExtractor().extract(scraped)
        self.assertEqual(posting.responsibilities, [])
        self.assertEqual(posting.requirements, [])
        self.assertIsNone(posting.location)
        self.assertIsNone(posting.employment_type)
        self.assertEqual(posting.extraction_status, "partial")
        self.assertIn("responsibilities", posting.missing_fields)
        for quotes in posting.field_evidence.values():
            for quote in quotes:
                self.assertIn(quote, source)

    def test_failed_retrieval_cannot_be_a_complete_posting(self) -> None:
        scraped = ScrapedJobContent(
            source_url="https://example.test/jobs/1", canonical_url="https://example.test/jobs/1",
            status_code=403, error_message="Access denied",
        )
        posting, _ = JobPostingExtractor().extract(scraped)
        self.assertEqual(posting.extraction_status, "blocked")
        self.assertTrue(posting.warnings)
        self.assertIsNone(posting.role)
        self.assertIsNone(posting.company)

    def test_email_tokens_are_absent_from_persistable_extraction(self) -> None:
        scraped = ScrapedJobContent(
            source_url="https://www.linkedin.com/jobs/view/123", canonical_url="https://www.linkedin.com/jobs/view/123",
            title="Engineer", company="Example", visible_text=SAMPLE_FULL_JOB_TEXT,
        )
        alert = JobAlertItem(title="Engineer", company="Example",
            raw_url="https://www.linkedin.com/comm/jobs/view/123?otpToken=synthetic-secret&midSig=synthetic-signature&trackingId=tracking",
            canonical_url="https://www.linkedin.com/jobs/view/123")
        posting, source = JobPostingExtractor().extract(scraped, alert)
        self.assertEqual(posting.source_url, alert.canonical_url)
        for value in (json.dumps(posting.to_dict()), source):
            self.assertNotIn("synthetic-secret", value)
            self.assertNotIn("synthetic-signature", value)
            self.assertNotIn("trackingId", value)

    def test_extraction_and_validation_compliance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir)

            scraped = ScrapedJobContent(
                source_url="https://www.linkedin.com/jobs/view/4159823451",
                canonical_url="https://www.linkedin.com/jobs/view/4159823451",
                title="Senior AI Platform Engineer",
                company="Mistral AI",
                location="Paris, France",
                visible_text=SAMPLE_FULL_JOB_TEXT,
                status_code=200,
                used_playwright=False,
            )

            alert_hint = JobAlertItem(
                title="Senior AI Platform Engineer",
                company="Mistral AI",
                location="Paris, France",
                raw_url="https://www.linkedin.com/jobs/view/4159823451",
                canonical_url="https://www.linkedin.com/jobs/view/4159823451",
                source="LinkedIn",
                job_id="4159823451",
            )

            extractor = JobPostingExtractor()
            job_posting, source_text = extractor.extract(scraped, alert_hint=alert_hint, output_dir=out_path)

            # Assert model properties
            self.assertEqual(job_posting.company, "Mistral AI")
            self.assertEqual(job_posting.role, "Senior AI Platform Engineer")
            self.assertEqual(job_posting.source_job_id, "4159823451")
            self.assertEqual(job_posting.work_model, "Hybrid")
            self.assertEqual(job_posting.seniority, "Senior")
            self.assertIn("Python", job_posting.technologies)
            self.assertIn("Kubernetes", job_posting.technologies)
            self.assertGreaterEqual(len(job_posting.responsibilities), 3)
            self.assertGreaterEqual(len(job_posting.requirements), 3)

            # Save job.json
            job_json_file = out_path / "job.json"
            job_json_file.write_text(json.dumps(job_posting.to_dict(), indent=2), encoding="utf-8")

            # Validate with project validator script
            validator_script = Path(__file__).resolve().parent.parent.parent / "skills" / "extract-job-opening" / "scripts" / "validate_job.py"
            self.assertTrue(validator_script.is_file(), f"Validator script not found at {validator_script}")

            proc = subprocess.run(
                [sys.executable, str(validator_script), "--job", str(job_json_file)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"validate_job.py failed with returncode {proc.returncode}:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
