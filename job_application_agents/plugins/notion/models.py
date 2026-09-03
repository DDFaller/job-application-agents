from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class NotionFileRef:
    filename: str
    content_type: str
    file_id: str
    sha256: str
    bytes: int
    notion_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotionFileRef:
        return cls(
            filename=str(data.get("filename", "")),
            content_type=str(data.get("content_type", "application/octet-stream")),
            file_id=str(data.get("file_id", "")),
            sha256=str(data.get("sha256", "")),
            bytes=int(data.get("bytes", 0)),
            notion_url=data.get("notion_url"),
        )


@dataclass(frozen=True)
class NotionCardPayload:
    application_title: str
    company: str
    role: str
    status: str = "TO_APPLY"
    location: str = ""
    work_model: str = "Unspecified"
    source: str = "Other ATS"
    job_url: str | None = None
    source_job_id: str = ""
    current_version: str = "v001"
    generated_at: str | None = None
    applied_at: str | None = None
    next_action_at: str | None = None
    local_bundle_path: str | None = None
    match_summary: str | None = None
    match_score: int | None = None
    match_breakdown: dict[str, Any] | None = None

    notes: str | None = None
    job_summary_text: str = ""
    requirements_text: str = ""
    match_analysis_text: str = ""
    gaps_text: str = ""
    application_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)



JOB_STATES = {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED"}


@dataclass(frozen=True)
class NotionSyncJob:
    id: str
    user_id: str
    application_id: str
    action: str  # "CREATE_OR_UPDATE", "DELETE"
    state: str = "QUEUED"
    payload: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    max_attempts: int = 3
    leased_by: str | None = None
    lease_expires_at: str | None = None
    result: dict[str, Any] | None = None
    error_detail: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("job id is required")
        if self.state not in JOB_STATES:
            raise ValueError(f"invalid job state: {self.state}")
        if self.action not in {"CREATE_OR_UPDATE", "DELETE"}:
            raise ValueError(f"invalid action: {self.action}")


    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "application_id": self.application_id,
            "action": self.action,
            "state": self.state,
            "payload": self.payload,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "leased_by": self.leased_by,
            "lease_expires_at": self.lease_expires_at,
            "result": self.result,
            "error_detail": self.error_detail,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotionSyncJob:
        return cls(
            id=str(data.get("id", str(uuid4()))),
            user_id=str(data.get("user_id", "")),
            application_id=str(data.get("application_id", "")),
            action=str(data.get("action", "CREATE_OR_UPDATE")),
            state=str(data.get("state", "QUEUED")),
            payload=dict(data.get("payload", {})),
            attempts=int(data.get("attempts", 0)),
            max_attempts=int(data.get("max_attempts", 3)),
            leased_by=data.get("leased_by"),
            lease_expires_at=data.get("lease_expires_at"),
            result=data.get("result"),
            error_detail=data.get("error_detail"),
            created_at=data.get("created_at"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )
