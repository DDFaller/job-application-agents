"""Unit tests for job scrapers and hybrid Playwright fallback."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from integrations.models import ScrapedJobContent
from integrations.scrapers.base import is_bot_blocked
from integrations.scrapers.http_scraper import HttpJobScraper
from integrations.scrapers.hybrid_scraper import HybridJobScraper
from integrations.scrapers.playwright_scraper import PlaywrightJobScraper


SAMPLE_JOB_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Staff AI Platform Engineer - Mistral AI | Jobs</title>
  <meta property="og:title" content="Staff AI Platform Engineer">
  <meta property="og:site_name" content="Mistral AI">
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Staff AI Platform Engineer",
    "hiringOrganization": {
      "@type": "Organization",
      "name": "Mistral AI"
    },
    "jobLocation": {
      "@type": "Place",
      "address": {
        "addressLocality": "Paris",
        "addressCountry": "France"
      }
    }
  }
  </script>
</head>
<body>
  <div class="job-description">
    <h1>Staff AI Platform Engineer</h1>
    <p>Mistral AI is looking for a Staff AI Platform Engineer in Paris.</p>
    <h2>What you will do:</h2>
    <ul>
      <li>Architect scalable distributed inference clusters for open foundation models.</li>
      <li>Deploy and optimize high-throughput model serving pipelines with PyTorch and Triton.</li>
      <li>Collaborate with research scientists to deploy state-of-the-art LLMs into production.</li>
    </ul>
    <h2>What you bring:</h2>
    <ul>
      <li>5+ years of experience with Python, Kubernetes, Docker, and Linux systems.</li>
      <li>Deep knowledge of cloud infrastructure on GCP or AWS and GPU orchestration.</li>
      <li>Familiarity with distributed training and inference optimization.</li>
    </ul>
  </div>
</body>
</html>
"""

SAMPLE_BLOCKED_HTML = """
<!DOCTYPE html>
<html>
<head><title>Access Denied - Security Check</title></head>
<body>
  <h2>Please verify you are a human</h2>
  <div id="cf-browser-verification">Cloudflare bot detection challenge</div>
</body>
</html>
"""


class TestJobScrapers(unittest.TestCase):

    def test_is_bot_blocked_detection(self) -> None:
        self.assertTrue(is_bot_blocked(403, "Forbidden"))
        self.assertTrue(is_bot_blocked(429, "Too Many Requests"))
        self.assertTrue(is_bot_blocked(999, "Request Denied"))
        self.assertTrue(is_bot_blocked(200, SAMPLE_BLOCKED_HTML))
        self.assertFalse(is_bot_blocked(200, SAMPLE_JOB_PAGE_HTML))

    def test_http_scraper_extracts_json_ld_and_meta(self) -> None:
        scraper = HttpJobScraper()
        meta = scraper._extract_meta_tags(SAMPLE_JOB_PAGE_HTML)
        self.assertEqual(meta.get("og:title"), "Staff AI Platform Engineer")
        self.assertEqual(meta.get("og:site_name"), "Mistral AI")

        json_ld = scraper._extract_json_ld(SAMPLE_JOB_PAGE_HTML)
        self.assertEqual(len(json_ld), 1)
        self.assertEqual(json_ld[0]["title"], "Staff AI Platform Engineer")

        title, company, location = scraper._extract_core_fields(json_ld, meta, SAMPLE_JOB_PAGE_HTML)
        self.assertEqual(title, "Staff AI Platform Engineer")
        self.assertEqual(company, "Mistral AI")
        self.assertEqual(location, "Paris, France")

    def test_hybrid_scraper_uses_http_when_clean(self) -> None:
        mock_http = MagicMock(spec=HttpJobScraper)
        mock_pw = MagicMock(spec=PlaywrightJobScraper)

        mock_http.scrape.return_value = ScrapedJobContent(
            source_url="https://example.com/job/1",
            canonical_url="https://example.com/job/1",
            title="Software Engineer",
            company="Acme Corp",
            visible_text="Comprehensive job description text with all engineering details over 250 characters long to ensure it meets the minimum threshold requirement for clean text extraction.",
            status_code=200,
            used_playwright=False,
        )

        hybrid = HybridJobScraper(http_scraper=mock_http, playwright_scraper=mock_pw)
        res = hybrid.scrape("https://example.com/job/1")

        self.assertTrue(res.is_success)
        self.assertFalse(res.used_playwright)
        mock_http.scrape.assert_called_once()
        mock_pw.scrape.assert_not_called()

    def test_hybrid_scraper_triggers_playwright_on_bot_block(self) -> None:
        mock_http = MagicMock(spec=HttpJobScraper)
        mock_pw = MagicMock(spec=PlaywrightJobScraper)

        # HTTP returns 403 / bot block error
        mock_http.scrape.return_value = ScrapedJobContent(
            source_url="https://linkedin.com/jobs/view/999",
            canonical_url="https://linkedin.com/jobs/view/999",
            status_code=403,
            used_playwright=False,
            error_message="HTTP direct request blocked or challenged (Status: 403)",
        )

        # Playwright succeeds
        mock_pw.scrape.return_value = ScrapedJobContent(
            source_url="https://linkedin.com/jobs/view/999",
            canonical_url="https://linkedin.com/jobs/view/999",
            title="Senior Platform Engineer",
            company="Mistral AI",
            location="Paris, France",
            visible_text="Full rendered job description extracted via Playwright headless browser with all requirements and responsibilities.",
            status_code=200,
            used_playwright=True,
        )

        hybrid = HybridJobScraper(http_scraper=mock_http, playwright_scraper=mock_pw)
        res = hybrid.scrape("https://linkedin.com/jobs/view/999")

        self.assertTrue(res.is_success)
        self.assertTrue(res.used_playwright)
        mock_http.scrape.assert_called_once()
        mock_pw.scrape.assert_called_once()


if __name__ == "__main__":
    unittest.main()
