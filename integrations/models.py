"""Data models for the job integrations subsystem."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any


@dataclass
class EmailAccountConfig:
    """Configuration for connecting to an email account (e.g. Gmail)."""

    email_address: str = ""
    app_password: str = ""
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    use_ssl: bool = True
    folder: str = "INBOX"
    target_senders: list[str] = field(
        default_factory=lambda: [
            "jobalerts-noreply@linkedin.com",
            "alert@indeed.com",
            "do-not-reply@indeed.com",
            "jobs-noreply@glassdoor.com",
            "notifications@otta.com",
            "no-reply@greenhouse.io",
            "jobs@lever.co",
        ]
    )
    search_criteria: str = "UNSEEN"  # or "ALL", or date-bounded
    max_messages: int = 25
    mark_as_read: bool = False
    auth_mode: str = "app_password"  # "app_password", "oauth2", "gmail_api"
    oauth_token_path: str | None = None
    client_secrets_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Redact secrets for safe logging
        if data.get("app_password"):
            data["app_password"] = "***REDACTED***"
        return data


@dataclass
class EmailMessage:
    """Represents a fetched email message."""

    uid: str
    message_id: str
    sender: str
    recipient: str
    subject: str
    date_str: str
    date_timestamp: datetime | None = None
    body_html: str = ""
    body_plain: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    folder: str = "INBOX"

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "message_id": self.message_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "subject": self.subject,
            "date_str": self.date_str,
            "date_timestamp": self.date_timestamp.isoformat() if self.date_timestamp else None,
            "body_plain_snippet": self.body_plain[:300] if self.body_plain else "",
            "has_html": bool(self.body_html),
        }


@dataclass
class JobAlertItem:
    """A single job opportunity parsed from an alert email."""

    title: str
    company: str
    location: str = ""
    raw_url: str = ""
    canonical_url: str = ""
    source: str = "LinkedIn"  # "LinkedIn", "Indeed", "Glassdoor", etc.
    job_id: str | None = None
    salary_text: str | None = None
    snippet: str = ""
    posted_date_text: str | None = None
    email_uid: str | None = None
    email_sender: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScrapedJobContent:
    """The raw and cleaned content fetched from a job posting URL."""

    source_url: str
    canonical_url: str
    title: str = ""
    company: str = ""
    location: str = ""
    raw_html: str = ""
    visible_text: str = ""
    meta_tags: dict[str, str] = field(default_factory=dict)
    json_ld: list[dict[str, Any]] = field(default_factory=list)
    status_code: int = 200
    used_playwright: bool = False
    fetch_duration_seconds: float = 0.0
    error_message: str | None = None
    screenshot_bytes: bytes | None = None

    @property
    def is_success(self) -> bool:
        return self.status_code == 200 and len(self.visible_text.strip()) > 50 and not self.error_message


@dataclass
class NormalizedJobPosting:
    """Standard normalized job posting conforming to the project's job schema (version 2)."""

    schema_version: int = 2
    extraction_status: str = "complete"  # "complete", "partial", "blocked"
    source: str | None = "LinkedIn"
    source_url: str | None = None
    canonical_url: str | None = None
    source_job_id: str | None = None
    company: str | None = None
    role: str | None = None
    location: str | None = None
    work_model: str = "Unspecified"  # "On-site", "Hybrid", "Remote", "Unspecified"
    employment_type: str | None = None  # "Full-time", "Contract", etc.
    seniority: str | None = None  # "Mid", "Senior", "Lead", etc.
    language: str | None = None
    posted_at: str | None = None  # "YYYY-MM-DD"
    closes_at: str | None = None  # "YYYY-MM-DD"
    responsibilities: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    application_instructions: list[str] = field(default_factory=list)
    source_document: str | None = None
    source_sha256: str | None = None
    field_evidence: dict[str, list[str]] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extracted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NormalizedJobPosting:
        return cls(
            schema_version=data.get("schema_version", 2),
            extraction_status=data.get("extraction_status", "complete"),
            source=data.get("source"),
            source_url=data.get("source_url"),
            canonical_url=data.get("canonical_url"),
            source_job_id=data.get("source_job_id"),
            company=data.get("company"),
            role=data.get("role"),
            location=data.get("location"),
            work_model=data.get("work_model", "Unspecified"),
            employment_type=data.get("employment_type"),
            seniority=data.get("seniority"),
            language=data.get("language"),
            posted_at=data.get("posted_at"),
            closes_at=data.get("closes_at"),
            responsibilities=list(data.get("responsibilities", [])),
            requirements=list(data.get("requirements", [])),
            preferred_skills=list(data.get("preferred_skills", [])),
            technologies=list(data.get("technologies", [])),
            application_instructions=list(data.get("application_instructions", [])),
            source_document=data.get("source_document"),
            source_sha256=data.get("source_sha256"),
            field_evidence=dict(data.get("field_evidence", {})),
            missing_fields=list(data.get("missing_fields", [])),
            warnings=list(data.get("warnings", [])),
            extracted_at=data.get("extracted_at"),
        )


@dataclass
class IngestedJob:
    """Full lifecycle tracking record for an ingested job opportunity."""

    job_id: str
    job_data: NormalizedJobPosting
    match_score: int = 0
    match_rating: str = "Medium Match"  # "High Match", "Medium Match", "Low Match"
    match_breakdown: dict[str, Any] = field(default_factory=dict)
    staging_dir: str | None = None
    source_email_sender: str | None = None
    source_email_subject: str | None = None
    ingested_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: str = "STAGED"  # "STAGED", "MATCHED", "SKIPPED", "QUEUED", "APPLIED", "FAILED"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_data": self.job_data.to_dict(),
            "match_score": self.match_score,
            "match_rating": self.match_rating,
            "match_breakdown": self.match_breakdown,
            "staging_dir": self.staging_dir,
            "source_email_sender": self.source_email_sender,
            "source_email_subject": self.source_email_subject,
            "ingested_at": self.ingested_at,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class IngestionResult:
    """Aggregated outcome of an ingestion batch run."""

    total_emails_scanned: int = 0
    total_emails_fetched: int = 0
    total_emails_skipped_already_checked: int = 0
    total_emails_filtered_out: int = 0
    total_emails_matched: int = 0
    total_emails_parsed: int = 0
    total_emails_staged: int = 0
    total_emails_failed: int = 0
    total_emails_forcibly_rechecked: int = 0
    filter_summary: dict[str, int] = field(default_factory=dict)
    total_jobs_found: int = 0
    total_jobs_scraped: int = 0
    total_jobs_staged: int = 0
    total_high_matches: int = 0
    total_medium_matches: int = 0
    total_low_matches: int = 0
    jobs: list[IngestedJob] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def fetched(self) -> int:
        return self.total_emails_fetched

    @property
    def skipped_already_checked(self) -> int:
        return self.total_emails_skipped_already_checked

    @property
    def filtered_out(self) -> int:
        return self.total_emails_filtered_out

    @property
    def matched(self) -> int:
        return self.total_emails_matched

    @property
    def parsed(self) -> int:
        return self.total_emails_parsed

    @property
    def staged(self) -> int:
        return self.total_jobs_staged

    @property
    def staged_emails(self) -> int:
        return self.total_emails_staged

    @property
    def failed(self) -> int:
        return self.total_emails_failed

    @property
    def forcibly_rechecked(self) -> int:
        return self.total_emails_forcibly_rechecked

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_emails_scanned": self.total_emails_scanned,
            "total_emails_fetched": self.total_emails_fetched,
            "total_emails_skipped_already_checked": self.total_emails_skipped_already_checked,
            "total_emails_filtered_out": self.total_emails_filtered_out,
            "total_emails_matched": self.total_emails_matched,
            "total_emails_parsed": self.total_emails_parsed,
            "total_emails_staged": self.total_emails_staged,
            "total_emails_failed": self.total_emails_failed,
            "total_emails_forcibly_rechecked": self.total_emails_forcibly_rechecked,
            "filter_summary": dict(self.filter_summary),
            "total_jobs_found": self.total_jobs_found,
            "total_jobs_scraped": self.total_jobs_scraped,
            "total_jobs_staged": self.total_jobs_staged,
            "total_high_matches": self.total_high_matches,
            "total_medium_matches": self.total_medium_matches,
            "total_low_matches": self.total_low_matches,
            "jobs_count": len(self.jobs),
            "jobs": [j.to_dict() for j in self.jobs],
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 2),
        }
