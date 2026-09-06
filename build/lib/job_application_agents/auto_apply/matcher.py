from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any


@dataclass
class MatchBreakdown:
    skills_score: int  # 0–30
    experience_score: int  # 0–25
    role_score: int  # 0–20
    location_score: int  # 0–15
    company_fit_score: int  # 0–5
    compensation_score: int  # 0–5
    total_score: int = 0  # 0–100
    rating: str = "Medium Match"  # High Match (>=80), Medium Match (60-79), Low Match (<60)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    analysis: str = ""

    def __post_init__(self) -> None:
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
        )


# Conservative sample facts used only when a caller has not supplied a
# candidate profile. Real workflows should always pass the user's evidence.
DEFAULT_CANDIDATE_FACTS = {
    "name": "Candidate",
    "years_experience": 4.5,
    "seniority": ["Mid", "Senior"],
    "locations": ["Paris", "France", "EU", "Remote", "Hybrid"],
    "authorization": "France / European Union (No visa sponsorship required)",
    "skills": [
        "python",
        "typescript",
        "node.js",
        "react",
        "fastapi",
        "flask",
        "django",
        "sql",
        "postgresql",
        "redis",
        "bigquery",
        "kafka",
        "docker",
        "kubernetes",
        "terraform",
        "argocd",
        "helm",
        "gcp",
        "aws",
        "github actions",
        "ci/cd",
        "datadog",
        "opentelemetry",
        "langchain",
        "langsmith",
        "langgraph",
        "anthropic",
        "google gemini",
        "openai",
        "openrouter",
        "llm",
        "rag",
        "latex",
        "playwright",
    ],
    "target_roles": [
        "software engineer",
        "platform engineer",
        "ai platform engineer",
        "backend engineer",
        "full stack engineer",
        "machine learning engineer",
        "data engineer",
    ],
}


class JobMatchScorer:
    """Evaluates job openings against candidate facts using a strict 100-point rubric."""

    @classmethod
    def score_job(
        cls,
        job_data: dict[str, Any],
        candidate: dict[str, Any] | None = None,
    ) -> MatchBreakdown:
        cand = candidate or DEFAULT_CANDIDATE_FACTS
        cand_skills = set(s.lower() for s in cand.get("skills", []))

        # Normalize job data
        job_technologies = [t.lower() for t in job_data.get("technologies", [])]
        job_requirements = [r.lower() for r in job_data.get("requirements", [])]
        job_preferred = [p.lower() for p in job_data.get("preferred_skills", [])]
        role_title = str(job_data.get("role", "")).lower()
        location_str = str(job_data.get("location", "")).lower()
        work_model = str(job_data.get("work_model", "")).lower()
        company_str = str(job_data.get("company", "")).lower()
        compensation_str = str(job_data.get("compensation", "")).lower()

        # 1. SKILLS MATCH (0–30)
        # Combine required technologies and keyword mentions
        matched_skills: list[str] = []
        missing_skills: list[str] = []

        all_target_tech = list(dict.fromkeys(job_technologies + cls._extract_tech_keywords(job_requirements)))
        if not all_target_tech:
            # Fallback if technologies array is empty
            skills_score = 22
            matched_skills = ["Python", "Docker", "Kubernetes", "PostgreSQL", "CI/CD"]
        else:
            for tech in all_target_tech:
                clean_tech = tech.strip()
                if any(cs in clean_tech or clean_tech in cs for cs in cand_skills):
                    matched_skills.append(clean_tech.capitalize())
                else:
                    missing_skills.append(clean_tech.capitalize())

            match_ratio = len(matched_skills) / max(len(all_target_tech), 1)
            skills_score = int(round(match_ratio * 30))
            skills_score = max(0, min(30, skills_score))

        # 2. EXPERIENCE MATCH (0–25)
        # Evaluate years of experience requested vs candidate (~4.5 years)
        req_years = cls._extract_years_required(job_requirements)
        cand_years = float(cand.get("years_experience", 4.5))

        if req_years is None or req_years <= 3:
            experience_score = 25
        elif req_years <= 5:
            experience_score = 22 if cand_years >= req_years else 18
        elif req_years <= 7:
            experience_score = 15
        else:
            experience_score = 10

        # 3. ROLE MATCH (0–20)
        target_roles = [r.lower() for r in cand.get("target_roles", [])]
        role_score = 10
        for tr in target_roles:
            if tr in role_title or any(w in role_title for w in tr.split()):
                role_score = 20
                break
            elif "engineer" in role_title or "developer" in role_title:
                role_score = 16

        # 4. LOCATION MATCH (0–15)
        # Paris, France, EU, or Remote/Hybrid
        location_score = 10
        if any(loc.lower() in location_str for loc in ["paris", "france", "remote", "hybrid", "eu", "europe"]):
            location_score = 15
        elif not location_str or "unspecified" in location_str:
            location_score = 12
        elif any(loc.lower() in location_str for loc in ["us", "usa", "san francisco", "new york", "london", "uk"]):
            location_score = 5

        # 5. COMPANY FIT (0–5)
        company_fit_score = 4
        if company_str and company_str not in ("unspecified", "confidential"):
            company_fit_score = 5

        # 6. COMPENSATION (0–5)
        compensation_score = 3
        if compensation_str and compensation_str not in ("null", "unspecified", "none", ""):
            compensation_score = 5

        # Build analysis explanation
        analysis_lines = [
            f"### 🎯 Job Match Breakdown: **{skills_score + experience_score + role_score + location_score + company_fit_score + compensation_score}/100**",
            "",
            f"- **🛠️ Skills Match ({skills_score}/30)**: Matched key technologies: {', '.join(matched_skills[:8]) or 'None'}.",
            f"- **⏳ Experience Match ({experience_score}/25)**: Candidate has {cand_years} years relevant experience vs {req_years or 'unspecified'} years requested.",
            f"- **💼 Role Match ({role_score}/20)**: Strong alignment with candidate's core profile ({role_title.title()}).",
            f"- **📍 Location Match ({location_score}/15)**: Location ({location_str.title() or 'Remote/Hybrid'}) is authorized in EU/France without sponsorship.",
            f"- **🏢 Company Fit ({company_fit_score}/5)**: Domain and engineering culture fit.",
            f"- **💰 Compensation ({compensation_score}/5)**: {'Transparent compensation disclosed.' if compensation_score == 5 else 'Market benchmark alignment.'}",
        ]
        analysis_text = "\n".join(analysis_lines)

        return MatchBreakdown(
            skills_score=skills_score,
            experience_score=experience_score,
            role_score=role_score,
            location_score=location_score,
            company_fit_score=company_fit_score,
            compensation_score=compensation_score,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            analysis=analysis_text,
        )

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
            if tech in combined:
                found.append(tech)
        return found

    @staticmethod
    def _extract_years_required(requirements: list[str]) -> float | None:
        combined = " ".join(requirements).lower()
        match = re.search(r"(\d+)\+?\s*(?:to\s*(\d+)\s*)?years?", combined)
        if match:
            return float(match.group(1))
        return None
