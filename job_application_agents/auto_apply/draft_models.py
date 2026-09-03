from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any


class FieldSource(str, Enum):
    PROFILE = "profile"      # Known candidate profile facts (identity.md)
    RESUME = "resume"        # Derived from XeLaTeX resume / evidence
    AI = "ai"                # AI-grounded generated answer
    USER = "user"            # Manually supplied/edited by candidate


class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    FILE = "file"


class ApplicationState(str, Enum):
    NEW = "NEW"
    PREFILLING = "PREFILLING"
    REVIEW_READY = "REVIEW_READY"
    USER_EDITING = "USER_EDITING"
    SYNCING_EDITS = "SYNCING_EDITS"
    READY_TO_APPROVE = "READY_TO_APPROVE"
    APPROVED = "APPROVED"
    SUBMITTING = "SUBMITTING"
    VERIFYING = "VERIFYING"
    SUBMITTED_CONFIRMED = "SUBMITTED_CONFIRMED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


@dataclass
class ApplicationField:
    """Represents a single interactive question or input field in the application draft."""
    id: str
    label: str
    type: FieldType
    value: Any
    options: list[str] = field(default_factory=list)
    required: bool = False
    source: FieldSource = FieldSource.PROFILE
    validation_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "type": self.type.value if isinstance(self.type, FieldType) else str(self.type),
            "value": self.value,
            "source": self.source.value if isinstance(self.source, FieldSource) else str(self.source),
            "required": self.required,
        }
        if self.options:
            d["options"] = self.options
        if self.validation_error:
            d["validation_error"] = self.validation_error
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplicationField:
        f_type = data.get("type", "text")
        try:
            field_type = FieldType(f_type)
        except ValueError:
            field_type = FieldType.TEXT

        f_source = data.get("source", "profile")
        try:
            field_source = FieldSource(f_source)
        except ValueError:
            field_source = FieldSource.PROFILE

        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            type=field_type,
            value=data.get("value", ""),
            options=list(data.get("options", [])),
            required=bool(data.get("required", False)),
            source=field_source,
            validation_error=data.get("validation_error"),
        )


@dataclass
class ApplicationDraft:
    """Structured, revision-tracked snapshot of an application ready for review."""
    application_id: str
    company: str
    job_title: str
    target_url: str
    revision: int
    fields: list[ApplicationField]
    resume_path: str
    letter_path: str | None = None
    preview_screenshot_path: str | None = None
    match_score: int | None = None
    match_breakdown: dict[str, Any] | None = None
    validation_errors: list[str] = field(default_factory=list)
    state: ApplicationState = ApplicationState.REVIEW_READY
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def draft_hash(self) -> str:
        """Deterministic SHA-256 hash of all field values, options, and attached file paths."""
        canonical_repr = {
            "application_id": self.application_id,
            "target_url": self.target_url,
            "revision": self.revision,
            "fields": [
                {
                    "id": f.id,
                    "label": f.label,
                    "value": f.value,
                    "source": f.source.value if isinstance(f.source, FieldSource) else str(f.source),
                }
                for f in sorted(self.fields, key=lambda x: x.id or x.label)
            ],
            "resume_path": self.resume_path,
            "letter_path": self.letter_path,
        }
        serialized = json.dumps(canonical_repr, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "company": self.company,
            "job_title": self.job_title,
            "target_url": self.target_url,
            "revision": self.revision,
            "draft_hash": self.draft_hash,
            "state": self.state.value if isinstance(self.state, ApplicationState) else str(self.state),
            "match_score": self.match_score,
            "match_breakdown": self.match_breakdown,
            "created_at": self.created_at,
            "resume_path": self.resume_path,
            "letter_path": self.letter_path,
            "preview_screenshot_path": self.preview_screenshot_path,
            "validation_errors": self.validation_errors,
            "fields": [f.to_dict() for f in self.fields],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplicationDraft:
        st = data.get("state", "REVIEW_READY")
        try:
            state_enum = ApplicationState(st)
        except ValueError:
            state_enum = ApplicationState.REVIEW_READY

        return cls(
            application_id=str(data.get("application_id", "")),
            company=str(data.get("company", "")),
            job_title=str(data.get("job_title", "")),
            target_url=str(data.get("target_url", "")),
            revision=int(data.get("revision", 1)),
            fields=[ApplicationField.from_dict(f) for f in data.get("fields", [])],
            resume_path=str(data.get("resume_path", "")),
            letter_path=data.get("letter_path"),
            preview_screenshot_path=data.get("preview_screenshot_path"),
            match_score=data.get("match_score"),
            match_breakdown=data.get("match_breakdown"),
            validation_errors=list(data.get("validation_errors", [])),
            state=state_enum,
            created_at=str(data.get("created_at", datetime.now(timezone.utc).isoformat())),
        )



@dataclass
class ApprovalToken:
    """Cryptographic authorization token binding a submission to an exact draft revision and hash."""
    application_id: str
    revision: int
    draft_hash: str
    approved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approved_by: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "revision": self.revision,
            "draft_hash": self.draft_hash,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
        }


@dataclass
class VerificationScore:
    """Multi-signal scoring matrix for application submission confirmation."""
    redirect_detected: bool = False           # +35 pts: URL changed to /thank-you or /confirmation
    success_text_found: bool = False          # +40 pts: Explicit "Application submitted" / "Thank you"
    confirmation_id: str | None = None        # +50 pts: Reference/Confirmation ID detected
    submit_button_gone: bool = False          # +15 pts: Submit button disappeared
    network_success: bool = False             # +10 pts: HTTP 200 submit POST recorded

    @property
    def total_score(self) -> int:
        score = 0
        if self.redirect_detected:
            score += 35
        if self.success_text_found:
            score += 40
        if self.confirmation_id:
            score += 50
        if self.submit_button_gone:
            score += 15
        if self.network_success:
            score += 10
        return score

    @property
    def verdict(self) -> ApplicationState:
        if self.total_score >= 50:
            return ApplicationState.SUBMITTED_CONFIRMED
        elif self.total_score >= 15:
            return ApplicationState.SUBMISSION_UNCERTAIN
        return ApplicationState.FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "verdict": self.verdict.value,
            "signals": {
                "redirect_detected": self.redirect_detected,
                "success_text_found": self.success_text_found,
                "confirmation_id": self.confirmation_id,
                "submit_button_gone": self.submit_button_gone,
                "network_success": self.network_success,
            },
        }


@dataclass
class AutomationIncident:
    """Represents a structured automation failure, barrier, or validation issue for telemetry & human review."""
    incident_id: str
    application_id: str
    company: str
    job_title: str
    category: str   # AUTH_WALL, CAPTCHA, VACANCY_EXPIRED, VALIDATION_ERROR, NAVIGATION_ERROR, UNEXPECTED_ERROR
    severity: str   # WARNING, ERROR, CRITICAL
    diagnostic_summary: str
    portal_url: str
    step_reached: int = 1
    proof_screenshot: str | None = None
    error_detail: str | None = None
    notion_card_id: str | None = None
    status: str = "OPEN"
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "application_id": self.application_id,
            "company": self.company,
            "job_title": self.job_title,
            "category": self.category,
            "severity": self.severity,
            "diagnostic_summary": self.diagnostic_summary,
            "portal_url": self.portal_url,
            "step_reached": self.step_reached,
            "proof_screenshot": self.proof_screenshot,
            "error_detail": self.error_detail,
            "notion_card_id": self.notion_card_id,
            "status": self.status,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
        }
