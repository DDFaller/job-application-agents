import unittest
from pathlib import Path

from wttj_scraper.matching import evaluate_job, load_profile
from wttj_scraper.models import Job


PROFILE = load_profile(Path(__file__).parents[1] / "config" / "profile.json")


class MatchingTests(unittest.TestCase):
    def test_accepts_strong_administrative_job_in_paris(self):
        job = Job(
            source_url="https://example.test/1",
            title="Agent administratif polyvalent H/F",
            location="75012 Paris, France",
            postal_code="75012",
            contract_type="CDI",
            description=(
                "Accueil physique et téléphonique, gestion et suivi des dossiers administratifs, "
                "saisie et mise à jour de tableaux de suivi Excel, gestion du courrier, classement, "
                "archivage et organisation de rendez-vous. Une expérience similaire est demandée."
            ),
        )
        result = evaluate_job(job, PROFILE)
        self.assertTrue(result.compatible)
        self.assertGreaterEqual(result.score, 75)
        self.assertIn("MC-EXP-002", result.matched_evidence_ids)
        self.assertIn("MC-SKILL-010", result.matched_evidence_ids)

    def test_rejects_job_outside_allowed_departments(self):
        job = Job(
            source_url="https://example.test/2",
            title="Assistant administratif",
            location="Yutz, France",
            postal_code="57970",
            contract_type="CDI",
            description="Accueil, saisie, dossiers administratifs, Excel, classement et courrier.",
        )
        result = evaluate_job(job, PROFILE)
        self.assertFalse(result.compatible)
        self.assertTrue(any("Departamento 57" in reason for reason in result.hard_rejections))

    def test_rejects_stage_even_with_matching_missions(self):
        job = Job(
            source_url="https://example.test/3",
            title="Stage - Assistant administratif",
            location="Paris",
            postal_code="75001",
            contract_type="STAGE",
            description="Accueil, dossiers administratifs, saisie, Excel et archivage.",
        )
        result = evaluate_job(job, PROFILE)
        self.assertFalse(result.compatible)
        self.assertTrue(any("Estágio" in reason for reason in result.hard_rejections))

    def test_rejects_unproven_hard_requirement(self):
        job = Job(
            source_url="https://example.test/4",
            title="Assistant administratif",
            location="Paris",
            postal_code="75001",
            contract_type="CDI",
            description="Accueil, dossiers, saisie et Excel. Master et permis B exigés.",
        )
        result = evaluate_job(job, PROFILE)
        self.assertFalse(result.compatible)
        self.assertTrue(any("Master" in reason for reason in result.hard_rejections))
        self.assertTrue(any("Permis B" in reason for reason in result.hard_rejections))


if __name__ == "__main__":
    unittest.main()
