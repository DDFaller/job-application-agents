from __future__ import annotations

import unittest

from job_application_agents.auto_apply.matcher import JobMatchScorer, MatchBreakdown


class TestJobMatchScorer(unittest.TestCase):
    def test_no_candidate_means_unassessed_not_sample_person(self) -> None:
        for candidate in (None, {}):
            result = JobMatchScorer.score_job({'technologies': ['Python']}, candidate=candidate)
            self.assertIsNone(result.total_score)
            self.assertEqual(result.rating, 'Not assessed')
            self.assertEqual(result.matched_skills, [])
            self.assertIsNone(MatchBreakdown.from_dict(result.to_dict()).total_score)

    def test_one_year_requirement_does_not_pass_without_experience(self) -> None:
        job = {'requirements': ['At least 1 year of development experience']}
        self.assertEqual(JobMatchScorer.score_job(job, {'years_experience': 0}).experience_score, 0)
        self.assertEqual(JobMatchScorer.score_job(job, {'years_experience': 0.5}).experience_score, 15)
        self.assertEqual(JobMatchScorer.score_job(job, {'years_experience': 1}).experience_score, 30)

    def test_keywords_are_not_substrings_and_missing_requirements_are_unknown(self) -> None:
        result = JobMatchScorer.score_job({'technologies': ['SQL'], 'role': 'Data Engineer', 'location': 'Australia'},
            {'skills': ['PostgreSQL'], 'target_roles': ['Software Engineer'], 'locations': ['US']})
        self.assertEqual((result.skills_score, result.role_score, result.location_score), (0, 0, 0))
        self.assertEqual(result.matched_skills, [])
        empty = JobMatchScorer.score_job({}, {'skills': ['Python']})
        self.assertEqual(empty.matched_skills, [])
        self.assertEqual((empty.evidence_coverage, empty.score_upper_bound), (0, 100))

    def test_company_and_salary_disclosure_do_not_add_fit_points(self) -> None:
        candidate = {'skills': ['Python']}
        result = JobMatchScorer.score_job({'company': 'Named', 'compensation': '1 EUR'}, candidate)
        self.assertEqual((result.company_fit_score, result.compensation_score), (0, 0))

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

        breakdown = JobMatchScorer.score_job(job_data, candidate={"skills": job_data["technologies"], "years_experience": 4, "target_roles": ["software engineer"], "locations": ["Paris"]})
        self.assertIsInstance(breakdown, MatchBreakdown)
        self.assertGreaterEqual(breakdown.total_score, 80)
        self.assertLessEqual(breakdown.total_score, 100)
        self.assertGreaterEqual(breakdown.skills_score, 20)
        self.assertEqual(breakdown.experience_score, 30)
        self.assertEqual(breakdown.role_score, 20)
        self.assertEqual(breakdown.location_score, 15)
        self.assertEqual(breakdown.company_fit_score, 0)
        self.assertEqual(breakdown.compensation_score, 0)
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
