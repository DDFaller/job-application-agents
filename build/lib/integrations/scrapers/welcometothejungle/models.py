"""Data models for Welcome to the Jungle scraper and matcher."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any

from ...models import NormalizedJobPosting, ScrapedJobContent


from ...pipeline.experience_prefilter import parse_experience_years


DEFAULT_SEED_URLS = [
    "https://www.welcometothejungle.com/fr/pages/emploi-assistant-administratif",
    "https://www.welcometothejungle.com/fr/pages/emploi-assistant-administratif-paris-75000",
    "https://www.welcometothejungle.com/fr/pages/emploi-ile-de-france",
]


@dataclass(slots=True)
class WttjJob:
    source_url: str
    title: str
    company: str = ""
    location: str = ""
    postal_code: str = ""
    contract_type: str = ""
    remote: str = ""
    salary: str = ""
    experience: str = ""
    date_posted: str = ""
    valid_through: str = ""
    description: str = ""
    qualifications: str = ""
    source: str = "welcome-to-the-jungle"

    def searchable_text(self) -> str:
        return " ".join(
            value
            for value in (
                self.title,
                self.company,
                self.location,
                self.contract_type,
                self.experience,
                self.description,
                self.qualifications,
            )
            if value
        )

    def to_scraped_job_content(self, raw_html: str = "") -> ScrapedJobContent:
        visible = f"{self.title}\n{self.company}\n{self.location}\n\n{self.description}\n\n{self.qualifications}".strip()
        return ScrapedJobContent(
            source_url=self.source_url,
            canonical_url=self.source_url,
            title=self.title,
            company=self.company,
            location=self.location,
            raw_html=raw_html,
            visible_text=visible,
            meta_tags={
                "contract_type": self.contract_type,
                "remote": self.remote,
                "salary": self.salary,
                "experience": self.experience,
                "postal_code": self.postal_code,
                "date_posted": self.date_posted,
                "valid_through": self.valid_through,
            },
        )

    def to_normalized_job_posting(self) -> NormalizedJobPosting:
        visible = f"{self.title}\n{self.company}\n{self.location}\n\n{self.description}\n\n{self.qualifications}".strip()
        sha = hashlib.sha256(visible.encode("utf-8")).hexdigest()
        work_model = "Remote" if "fréquent" in self.remote.lower() or "total" in self.remote.lower() else ("Hybrid" if "occasionnel" in self.remote.lower() else "Unspecified")

        reqs = [q.strip() for q in self.qualifications.split("\n") if len(q.strip()) > 5]
        if not reqs and self.description:
            reqs = [d.strip() for d in self.description.split("\n") if len(d.strip()) > 10][:5]

        exp_years = parse_experience_years(self.experience) if self.experience else None

        return NormalizedJobPosting(
            schema_version=2,
            extraction_status="complete" if self.title and (self.description or self.qualifications) else "partial",
            source="WelcomeToTheJungle",
            source_url=self.source_url,
            canonical_url=self.source_url,
            application_url=self.source_url,
            company=self.company or None,
            role=self.title or None,
            location=self.location or None,
            work_model=work_model,
            employment_type=self.contract_type or None,
            experience_level=self.experience or None,
            experience_years=exp_years,
            posted_at=self.date_posted[:10] if self.date_posted else None,
            closes_at=self.valid_through[:10] if self.valid_through else None,
            responsibilities=[d.strip() for d in self.description.split("\n") if len(d.strip()) > 10][:8],
            requirements=reqs,
            source_document=visible,
            source_sha256=sha,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass(slots=True)
class WttjEvaluation:
    compatible: bool
    score: int
    score_breakdown: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    hard_rejections: list[str] = field(default_factory=list)
    department: str = ""


@dataclass(slots=True)
class WttjScrapeOptions:
    pages: int = 2
    max_jobs: int = 60
    delay_seconds: float = 1.5
    timeout_ms: int = 30_000
    headed: bool = False
    minimum_score: int | None = None
    seed_urls: list[str] = field(default_factory=lambda: list(DEFAULT_SEED_URLS))
