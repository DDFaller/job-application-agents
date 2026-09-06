"""Tests for Emploi Territorial scraper and extraction."""

from pathlib import Path
import unittest

from integrations.scrapers.emploi_territorial import (
    EmploiTerritorialScraper,
    extract_territorial_deadline,
    extract_territorial_publication_date,
    parse_territorial_listing,
)


class TestEmploiTerritorialScraper(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"
        with open(self.fixtures_dir / "territorial.html", "r", encoding="utf-8") as f:
            self.html = f.read()

    def test_parse_territorial_listing(self):
        jobs = parse_territorial_listing(self.html)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["reference"], "o075260824000001")
        self.assertEqual(jobs[0]["source_portal"], "emploi-territorial")

    def test_extract_territorial_dates(self):
        sample_html = """
        <div class="row px-3">Publiée le <span class="pl-1 set-color-green">04/09/2026</span></div>
        <p>Date limite de candidature : 30/09/2026</p>
        """
        posted = extract_territorial_publication_date(sample_html)
        self.assertEqual(posted, "2026-09-04")
        deadline = extract_territorial_deadline(sample_html)
        self.assertEqual(deadline, "2026-09-30")


if __name__ == "__main__":
    unittest.main()
