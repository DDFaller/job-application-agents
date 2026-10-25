from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

from integrations.models import JobAlertItem, ScrapedJobContent
from integrations.scrapers.extractor import JobPostingExtractor


ROOT = Path(__file__).resolve().parents[2]


class TestRedirectURLPreservation(unittest.TestCase):
    def test_extractor_preserves_linkedin_source_and_resolved_application_url(self) -> None:
        linkedin_url = (
            "https://www.linkedin.com/jobs/view/4460010933/?refId=tracking-ref"
            "&trackingId=tracking-id"
        )
        ashby_url = (
            "https://jobs.ashbyhq.com/Pelico/30abd535-7d96-4558-9dd2-cef57270c2d4/"
            "application?src=LinkedIn"
        )
        scraped = ScrapedJobContent(
            source_url="https://www.linkedin.com/jobs/view/4460010933",
            canonical_url=ashby_url,
            title="Software Engineer",
            company="Pelico",
            location="Paris, France",
            visible_text=(
                "Responsibilities:\n- Build reliable software systems.\n\n"
                "Requirements:\n- Experience with Python and distributed systems."
            ),
        )
        alert = JobAlertItem(
            title="Software Engineer",
            company="Pelico",
            raw_url=linkedin_url,
            canonical_url="https://www.linkedin.com/jobs/view/4460010933",
            source="LinkedIn",
            job_id="4460010933",
        )

        with tempfile.TemporaryDirectory() as tmp:
            posting, source_text = JobPostingExtractor().extract(
                scraped, alert_hint=alert, output_dir=Path(tmp)
            )
            self.assertEqual(posting.source_url, alert.canonical_url)
            self.assertEqual(posting.canonical_url, ashby_url)
            self.assertEqual(posting.application_url, ashby_url)
            self.assertIn(f"**Source URL:** {alert.canonical_url}", source_text)
            self.assertNotIn("tracking-id", source_text)
            self.assertIn(f"**Application URL:** {ashby_url}", source_text)

            job_path = Path(tmp) / "job.json"
            job_path.write_text(json.dumps(posting.to_dict()), encoding="utf-8")
            self.assertEqual(json.loads(job_path.read_text())["application_url"], ashby_url)

    def test_legacy_schema_v2_job_without_application_url_remains_valid(self) -> None:
        # The validator accepts existing schema-v2 artifacts while requiring
        # application_url on newly generated artifacts from the template.
        validator_path = ROOT / "skills/extract-job-opening/scripts/validate_job.py"
        spec = importlib.util.spec_from_file_location("job_validator", validator_path)
        validator = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(validator)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.md"
            source.write_text("# Engineer\n", encoding="utf-8")
            job = {
                "schema_version": 2,
                "extraction_status": "complete",
                "source": "LinkedIn",
                "source_url": "https://www.linkedin.com/jobs/view/123456789",
                "canonical_url": "https://www.linkedin.com/jobs/view/123456789",
                "source_job_id": "123456789",
                "company": "Acme",
                "role": "Engineer",
                "location": "Paris",
                "work_model": "Unspecified",
                "employment_type": None,
                "seniority": None,
                "language": "en",
                "posted_at": None,
                "closes_at": None,
                "responsibilities": ["Build systems"],
                "requirements": [],
                "preferred_skills": [],
                "technologies": [],
                "application_instructions": [],
                "source_document": str(source),
                "source_sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
                "field_evidence": {
                    "source_job_id": ["Job ID"],
                    "company": ["Acme"],
                    "role": ["Engineer"],
                    "location": ["Paris"],
                    "language": ["en"],
                    "responsibilities.0": ["Build systems"],
                },
                "missing_fields": [],
                "warnings": [],
                "extracted_at": "2026-09-04T00:00:00+00:00",
            }
            template = json.loads((ROOT / "skills/extract-job-opening/references/job-template.json").read_text())
            errors, _ = validator.validate(job, template, Path(tmp) / "job.json")
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
