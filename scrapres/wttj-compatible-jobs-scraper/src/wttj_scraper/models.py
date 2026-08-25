from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Job:
    source_url: str
    title: str
    company: str = ""
    location: str = ""
    postal_code: str = ""
    contract_type: str = ""
    remote: str = ""
    salary: str = ""
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
                self.description,
                self.qualifications,
            )
            if value
        )


@dataclass(slots=True)
class Evaluation:
    compatible: bool
    score: int
    match_reasons: list[str] = field(default_factory=list)
    matched_evidence_ids: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    hard_rejections: list[str] = field(default_factory=list)


def job_result(job: Job, evaluation: Evaluation) -> dict[str, Any]:
    result = asdict(job)
    result.update(
        {
            "compatibility_score": evaluation.score,
            "match_reasons": evaluation.match_reasons,
            "matched_evidence_ids": evaluation.matched_evidence_ids,
            "gaps": evaluation.gaps,
        }
    )
    return result

