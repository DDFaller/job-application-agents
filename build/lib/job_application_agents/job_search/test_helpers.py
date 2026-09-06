from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from job_application_agents.job_search.outcomes import followup_due, validate_transition
from job_application_agents.job_search.ranking import load_json_jobs, rank_jobs
from job_application_agents.job_search.reports import build_report, render_html_report


class TestJobSearchHelpers(unittest.TestCase):
    def test_ranking_deduplicates_and_sorts(self):
        jobs = [
            {"company": "A", "role": "Software Engineer", "canonical_url": "https://a/job", "technologies": ["Python"]},
            {"company": "A", "role": "Software Engineer", "canonical_url": "https://a/job/", "technologies": ["Python"]},
            {"company": "B", "role": "Data Engineer", "canonical_url": "https://b/job", "technologies": ["Kubernetes"]},
        ]
        ranked = rank_jobs(jobs, top=5)
        self.assertEqual(len(ranked), 2)
        self.assertGreaterEqual(ranked[0]["score"], ranked[1]["score"])
        self.assertTrue(ranked[0]["triage_only"])

    def test_ranking_can_exclude_tracked_key(self):
        job = {"company": "A", "role": "Engineer", "canonical_url": "https://a/job"}
        self.assertEqual(rank_jobs([job], tracked_keys={"url:https://a/job"}), [])

    def test_followup_uses_calendar_age_and_rejects_future(self):
        self.assertTrue(followup_due("2026-08-01", 14, today=date(2026, 8, 31)))
        self.assertFalse(followup_due("2026-09-01", 0, today=date(2026, 8, 31)))

    def test_transition_and_report(self):
        self.assertEqual(validate_transition("APPLIED", "INTERVIEW")[0], True)
        self.assertEqual(validate_transition("APPLIED", "BOGUS")[0], False)
        report = build_report([
            {"company": "A", "role": "X", "status": "APPLIED"},
            {"company": "B", "role": "Y", "status": "INTERVIEW"},
        ])
        self.assertEqual(report["interview_records"], 1)
        self.assertEqual(report["submitted_records"], 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = render_html_report(report, Path(tmp) / "report.html")
            self.assertIn("Job application report", path.read_text(encoding="utf-8"))

    def test_load_json_jobs_ignores_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "good").mkdir()
            (root / "good" / "job.json").write_text(json.dumps({"role": "X"}), encoding="utf-8")
            (root / "bad").mkdir()
            (root / "bad" / "job.json").write_text("not json", encoding="utf-8")
            self.assertEqual(len(load_json_jobs(root)), 1)


if __name__ == "__main__":
    unittest.main()
