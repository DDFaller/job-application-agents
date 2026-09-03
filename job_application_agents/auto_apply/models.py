from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CandidateProfile:
    """Standardized candidate personal data for application autofill."""
    first_name: str
    last_name: str
    email: str
    phone: str
    location: str
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    work_authorization: str = "Authorized"
    requires_sponsorship: bool = False
    notice_period_weeks: int = 4
    salary_expectation: str | None = None
    custom_answers: dict[str, str] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidateProfile:
        return cls(
            first_name=str(data.get("first_name", "")),
            last_name=str(data.get("last_name", "")),
            email=str(data.get("email", "")),
            phone=str(data.get("phone", "")),
            location=str(data.get("location", "")),
            linkedin_url=str(data.get("linkedin_url", "")),
            github_url=str(data.get("github_url", "")),
            portfolio_url=str(data.get("portfolio_url", "")),
            work_authorization=str(data.get("work_authorization", "Authorized")),
            requires_sponsorship=bool(data.get("requires_sponsorship", False)),
            notice_period_weeks=int(data.get("notice_period_weeks", 4)),
            salary_expectation=data.get("salary_expectation"),
            custom_answers=dict(data.get("custom_answers", {})),
        )


@dataclass
class FormFillResult:
    """Outcome of attempting to fill out an application form."""
    driver_name: str
    success: bool
    fields_filled: list[str] = field(default_factory=list)
    missing_required_fields: list[str] = field(default_factory=list)
    resume_uploaded: bool = False
    letter_uploaded: bool = False
    preview_screenshot_path: str | None = None
    error_message: str | None = None


@dataclass
class SubmissionReceipt:
    """Proof of a supervised form run or application submission."""
    success: bool
    driver_name: str
    job_url: str
    applied_at: str
    submitted: bool = False
    confirmation_text: str | None = None
    screenshot_path: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "driver_name": self.driver_name,
            "job_url": self.job_url,
            "applied_at": self.applied_at,
            "submitted": self.submitted,
            "confirmation_text": self.confirmation_text,
            "screenshot_path": self.screenshot_path,
            "error_message": self.error_message,
        }
