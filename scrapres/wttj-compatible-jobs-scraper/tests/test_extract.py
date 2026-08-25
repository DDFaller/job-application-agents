import json
import unittest

from wttj_scraper.extract import find_job_posting, job_from_page_data


class ExtractTests(unittest.TestCase):
    def test_finds_nested_job_posting_and_normalizes_it(self):
        payload = {
            "@graph": [
                {"@type": "WebPage"},
                {
                    "@type": "JobPosting",
                    "title": "Agent administratif H/F",
                    "description": "<p>Saisie et <strong>suivi des dossiers</strong>.</p>",
                    "employmentType": "FULL_TIME",
                    "hiringOrganization": {"name": "Exemple"},
                    "jobLocation": {
                        "address": {
                            "streetAddress": "1 rue Exemple",
                            "postalCode": "93160",
                            "addressLocality": "Noisy-le-Grand",
                            "addressCountry": "FR",
                        }
                    },
                },
            ]
        }
        raw = json.dumps(payload)

        self.assertEqual(find_job_posting([raw])["title"], "Agent administratif H/F")
        job = job_from_page_data("https://example.test/job", [raw], "")
        self.assertEqual(job.contract_type, "CDI")
        self.assertEqual(job.postal_code, "93160")
        self.assertEqual(job.company, "Exemple")
        self.assertEqual(job.description, "Saisie et suivi des dossiers .")

    def test_uses_visible_text_as_fallback(self):
        body = """Assistant administratif\nRésumé du poste\nCDD\nParis\nDescriptif du poste\nAccueil téléphonique et gestion des dossiers.\nProfil recherché\nRigueur.\nLe lieu de travail\n1 rue Test, 75002 Paris, France\nPostuler"""
        job = job_from_page_data("https://example.test/job", [], body, "Assistant administratif")
        self.assertEqual(job.contract_type, "CDD")
        self.assertEqual(job.postal_code, "75002")
        self.assertIn("Accueil téléphonique", job.description)


if __name__ == "__main__":
    unittest.main()

