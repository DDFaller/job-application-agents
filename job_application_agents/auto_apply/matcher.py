from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import math
from typing import Any


@dataclass
class MatchBreakdown:
    skills_score: int  # 0–35
    experience_score: int  # 0–30
    role_score: int  # 0–20
    location_score: int  # 0–15
    company_fit_score: int  # 0–5
    compensation_score: int  # 0–5
    total_score: int | None = 0  # None means not assessed
    rating: str = "Medium Match"  # High Match (>=80), Medium Match (60-79), Low Match (<60)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    analysis: str = ""
    assessed: bool = True
    evidence_coverage: int = 0
    score_upper_bound: int = 100
    rubric_version: str = "structured-triage-v2"
    weights: dict[str, int] = field(default_factory=lambda: {
        "skills_score": 35, "experience_score": 30, "role_score": 20,
        "location_score": 15, "company_fit_score": 0, "compensation_score": 0,
    })

    def __post_init__(self) -> None:
        if not self.assessed:
            self.total_score = None
            self.rating = "Not assessed"
            return
        self.total_score = (
            self.skills_score
            + self.experience_score
            + self.role_score
            + self.location_score
            + self.company_fit_score
            + self.compensation_score
        )
        if self.total_score >= 80:
            self.rating = "High Match"
        elif self.total_score >= 60:
            self.rating = "Medium Match"
        else:
            self.rating = "Low Match"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MatchBreakdown:
        return cls(
            skills_score=int(data.get("skills_score", 0)),
            experience_score=int(data.get("experience_score", 0)),
            role_score=int(data.get("role_score", 0)),
            location_score=int(data.get("location_score", 0)),
            company_fit_score=int(data.get("company_fit_score", 0)),
            compensation_score=int(data.get("compensation_score", 0)),
            matched_skills=list(data.get("matched_skills", [])),
            missing_skills=list(data.get("missing_skills", [])),
            analysis=str(data.get("analysis", "")),
            assessed=data.get("assessed", True),
            evidence_coverage=int(data.get("evidence_coverage", 0)),
            score_upper_bound=int(data.get("score_upper_bound", 100)),
            rubric_version=str(data.get("rubric_version", "legacy")),
            weights=dict(data.get("weights") or {"skills_score": 30, "experience_score": 25,
                "role_score": 20, "location_score": 15, "company_fit_score": 5, "compensation_score": 5}),
        )


class JobMatchScorer:
    """Conservative shortlist triage from supplied facts; never submission authority."""

    @classmethod
    def score_job(
        cls,
        job_data: dict[str, Any],
        candidate: dict[str, Any] | None = None,
    ) -> MatchBreakdown:
        if not candidate:
            return MatchBreakdown(0, 0, 0, 0, 0, 0, assessed=False,
                analysis="Not assessed: supply verified candidate facts. No sample profile was used.")
        cand = candidate
        cand_skills = {cls._skill(s) for s in cand.get("skills", []) if isinstance(s, str) and s.strip()}
        requirements = job_data.get("requirements") or []
        technologies = job_data.get("technologies") or []
        target = list(dict.fromkeys(cls._skill(t) for t in
            technologies + cls._extract_tech_keywords(requirements) if isinstance(t, str) and t.strip()))
        matched = [s for s in target if s in cand_skills]
        missing = [s for s in target if s not in cand_skills]
        skills_known = bool(target) and bool(cand.get("skills"))
        skills_score = math.floor(35 * len(matched) / len(target)) if skills_known else 0

        req_years = cls._extract_years_required(requirements)
        years = cand.get("years_experience")
        years_known = type(years) in {int, float} and math.isfinite(years) and years >= 0
        experience_known = req_years is not None and years_known
        experience_score = math.floor(30 * min(1, years / req_years)) if experience_known and req_years > 0 else (30 if experience_known else 0)

        role = str(job_data.get("role") or job_data.get("job_title") or "").lower()
        target_roles = [str(r).lower().strip() for r in cand.get("target_roles", []) if str(r).strip()]
        role_known = bool(role and target_roles)
        role_score = 20 if role_known and any(cls._phrase(r, role) for r in target_roles) else 0

        location = str(job_data.get("location") or "").lower()
        locations = [str(loc).lower().strip() for loc in cand.get("locations", []) if str(loc).strip()]
        location_known = bool(location and locations)
        location_score = 15 if location_known and any(cls._phrase(loc, location) for loc in locations) else 0
        # Company names and disclosed salaries are not evidence of personal fit.
        coverage = 35 * skills_known + 30 * experience_known + 20 * role_known + 15 * location_known
        score = skills_score + experience_score + role_score + location_score
        return MatchBreakdown(
            skills_score, experience_score, role_score, location_score, 0, 0,
            matched_skills=[s.capitalize() for s in matched],
            missing_skills=[s.capitalize() for s in missing],
            evidence_coverage=coverage, score_upper_bound=min(100, score + 100 - coverage),
            analysis=(f"Structured shortlist triage: {score}/100; evidence coverage {coverage}%. "
                f"Skills {skills_score}/35; experience {experience_score}/30; role {role_score}/20; "
                f"location preference {location_score}/15. "
                "Missing skills mean not documented in supplied facts. Location matching does not "
                "establish work authorization. Use the evidence-bound fit report for application decisions."),
        )

    @staticmethod
    def _phrase(needle: str, haystack: str) -> bool:
        return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack) is not None

    @staticmethod
    def _skill(value: str) -> str:
        value = value.lower().strip()
        return {"nodejs": "node.js", "node js": "node.js", "postgres": "postgresql",
                "k8s": "kubernetes", "js": "javascript", "ts": "typescript"}.get(value, value)

    @staticmethod
    def _extract_tech_keywords(texts: list[str]) -> list[str]:
        common_tech = [
            "python", "react", "typescript", "node.js", "kubernetes", "docker",
            "terraform", "gcp", "aws", "kafka", "postgresql", "redis", "langchain",
            "bigquery", "datadog", "ci/cd", "graphql", "sql"
        ]
        found = []
        combined = " ".join(texts).lower()
        for tech in common_tech:
            if JobMatchScorer._phrase(tech, combined):
                found.append(tech)
        return found

    @staticmethod
    def _extract_years_required(requirements: list[str]) -> float | None:
        combined = " ".join(requirements).lower()
        match = re.search(r"(\d+(?:\.\d+)?)\+?\s*(?:(?:to|[-–])\s*\d+(?:\.\d+)?\s*)?(?:years?|ans?|années?)\b", combined)
        if match:
            return float(match.group(1))
        return None
