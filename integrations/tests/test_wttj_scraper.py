"""Tests for Welcome to the Jungle scraper and extraction."""

import json
from pathlib import Path
import unittest

from integrations.scrapers.welcometothejungle import (
    WttjJob,
    WttjScraper,
    clean_text,
    find_job_posting,
    fold,
    job_from_page_data,
    paginated_url,
    strip_html,
)


class TestWttjScraper(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"
        with open(self.fixtures_dir / "wttj-job.html", "r", encoding="utf-8") as f:
            self.html = f.read()

    def test_text_utils(self):
        self.assertEqual(clean_text("  Bonjour &amp; bienvenue &nbsp; "), "Bonjour & bienvenue")
        self.assertEqual(strip_html("<p>Hello <b>World</b>!</p>"), "Hello World!")
        self.assertEqual(fold("Élève ingénieur à Paris-75"), "eleve ingenieur a paris 75")

    def test_paginated_url(self):
        self.assertEqual(
            paginated_url("https://www.welcometothejungle.com/fr/jobs?page=1&query=dev", 3),
            "https://www.welcometothejungle.com/fr/jobs?page=3&query=dev",
        )

    def test_extract_job_from_json_ld_and_html(self):
        scraper = WttjScraper()
        wttj_job = scraper.extract_job_from_html(self.html, source_url="https://www.welcometothejungle.com/fr/companies/acme/jobs/agent-admin")

        self.assertEqual(wttj_job.title, "Agent administratif H/F")
        self.assertEqual(wttj_job.company, "Acme Corp")
        self.assertEqual(wttj_job.location, "12 rue de la Paix, 75002, Paris, FR")
        self.assertEqual(wttj_job.postal_code, "75002")
        self.assertEqual(wttj_job.contract_type, "CDI")
        self.assertEqual(wttj_job.salary, "28000 - 32000 EUR YEAR")
        self.assertIn("Saisie et suivi des dossiers", wttj_job.description)

        # Test conversion to ScrapedJobContent
        scraped = wttj_job.to_scraped_job_content(raw_html=self.html)
        self.assertTrue(scraped.is_success)
        self.assertEqual(scraped.title, "Agent administratif H/F")
        self.assertEqual(scraped.meta_tags["contract_type"], "CDI")

        # Test conversion to NormalizedJobPosting
        norm = wttj_job.to_normalized_job_posting()
        self.assertEqual(norm.schema_version, 2)
        self.assertEqual(norm.source, "WelcomeToTheJungle")
        self.assertEqual(norm.role, "Agent administratif H/F")
        self.assertEqual(norm.company, "Acme Corp")
        self.assertEqual(norm.extraction_status, "complete")

    def test_extract_experience_from_html_and_json_ld(self):
        html_with_exp = """
        <!doctype html>
        <html><body>
          <h1>Développeur Python</h1>
          <div class="sc-brzPDJ kVqhOm">Expérience : </div>&gt; 5 ans
        </body></html>
        """
        scraper = WttjScraper()
        wttj_job = scraper.extract_job_from_html(html_with_exp, source_url="https://www.welcometothejungle.com/fr/jobs/dev")
        self.assertEqual(wttj_job.experience, "> 5 ans")

        norm = wttj_job.to_normalized_job_posting()
        self.assertEqual(norm.experience_level, "> 5 ans")
        self.assertEqual(norm.experience_years, 5.0)

        # Test JSON-LD experience
        html_with_jld = """
        <!doctype html>
        <html><head>
          <script type="application/ld+json">
          {
            "@type": "JobPosting",
            "title": "Data Engineer",
            "experienceRequirements": {
              "@type": "OccupationalExperienceRequirements",
              "monthsOfExperience": 12
            }
          }
          </script>
        </head><body>Data Engineer</body></html>
        """
        job_jld = scraper.extract_job_from_html(html_with_jld, source_url="https://www.welcometothejungle.com/fr/jobs/data")
        self.assertEqual(job_jld.experience, "12 mois")
        norm_jld = job_jld.to_normalized_job_posting()
        self.assertEqual(norm_jld.experience_years, 1.0)


if __name__ == "__main__":
    unittest.main()
