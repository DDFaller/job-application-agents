from __future__ import annotations

import unittest

from job_application_agents.auto_apply.matcher import JobMatchScorer, MatchBreakdown


class TestJobMatchScorer(unittest.TestCase):
    def test_score_gorgias_ai_platform(self) -> None:
        job_data = {
            "company": "Gorgias",
            "role": "Software Engineer - Internal AI Platform",
            "location": "Paris",
            "work_model": "Hybrid",
            "requirements": [
                "3+ years as a full-stack engineer, and you've shipped user-facing products end to end.",
                "Strong full-stack engineering across front-end and back-end (React, Python).",
                "Comfortable owning cloud-native infrastructure — Kubernetes, Terraform, GCP.",
            ],
            "technologies": [
                "Python",
                "React",
                "Kubernetes",
                "Terraform",
                "GCP",
                "Kafka",
                "PostgreSQL",
                "LangChain",
            ],
            "compensation": "€82,592 – €91,286",
        }

        breakdown = JobMatchScorer.score_job(job_data)
        self.assertIsInstance(breakdown, MatchBreakdown)
        self.assertGreaterEqual(breakdown.total_score, 80)
        self.assertLessEqual(breakdown.total_score, 100)
        self.assertGreaterEqual(breakdown.skills_score, 20)
        self.assertEqual(breakdown.experience_score, 25)
        self.assertEqual(breakdown.role_score, 20)
        self.assertEqual(breakdown.location_score, 15)
        self.assertEqual(breakdown.company_fit_score, 5)
        self.assertEqual(breakdown.compensation_score, 5)
        self.assertEqual(breakdown.rating, "High Match")
        self.assertIn("Python", breakdown.matched_skills)
        self.assertIn("React", breakdown.matched_skills)
        self.assertIn("Kubernetes", breakdown.matched_skills)

    def test_score_serialization_round_trip(self) -> None:
        breakdown = MatchBreakdown(
            skills_score=26,
            experience_score=22,
            role_score=18,
            location_score=15,
            company_fit_score=4,
            compensation_score=4,
            matched_skills=["Python", "Docker"],
            missing_skills=["Ruby"],
            analysis="Strong fit.",
        )
        d = breakdown.to_dict()
        self.assertEqual(d["total_score"], 89)
        self.assertEqual(d["rating"], "High Match")

        restored = MatchBreakdown.from_dict(d)
        self.assertEqual(restored.total_score, 89)
        self.assertEqual(restored.rating, "High Match")
        self.assertEqual(restored.skills_score, 26)


if __name__ == "__main__":
    unittest.main()
