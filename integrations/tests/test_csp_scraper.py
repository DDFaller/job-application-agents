"""Tests for Choisir le Service Public scraper and extraction."""

from pathlib import Path
import unittest

from integrations.scrapers.choisir_le_service_public import (
    CspScraper,
    extract_csp_deadline,
    extract_csp_json_ld,
    extract_csp_publication_date,
    parse_csp_listing,
)


class TestCspScraper(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"
        with open(self.fixtures_dir / "csp.html", "r", encoding="utf-8") as f:
            self.html = f.read()

    def test_parse_csp_listing(self):
        jobs = parse_csp_listing(self.html)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["reference"], "2026-123")
        self.assertEqual(jobs[0]["source_portal"], "choisir-service-public")

    def test_extract_csp_json_ld(self):
        json_ld = extract_csp_json_ld(self.html)
        self.assertIsNotNone(json_ld)
        self.assertEqual(json_ld["title"], "Agent administratif")
        self.assertEqual(json_ld["hiringOrganization"]["name"], "Ministère de l'Intérieur")

    def test_extract_csp_deadline_and_dates(self):
        sample_html = """
        <div>
          <p>Date de publication : 15/08/2026</p>
          <p>Date limite de candidature : 30/08/2026</p>
        </div>
        """
        deadline = extract_csp_deadline(sample_html)
        self.assertEqual(deadline, "2026-08-30")
        posted = extract_csp_publication_date(sample_html)
        self.assertEqual(posted, "2026-08-15")


if __name__ == "__main__":
    unittest.main()
