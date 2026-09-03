from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UserContext:
    user_id: str
    email: str | None = None
    display_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sync_version": 1,
        }


@dataclass(frozen=True)
class CurriculumSyncSnapshot:
    version: str
    updated_at: str
    markdown_sources: list[str]
    source_hashes: dict[str, str]
    sources: dict[str, str]  # filename -> file content string
    manifest: dict[str, Any]
    photo: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "version": self.version,
            "updated_at": self.updated_at,
            "markdown_sources": list(self.markdown_sources),
            "source_hashes": dict(self.source_hashes),
            "sources": dict(self.sources),
            "manifest": self.manifest,
            "photo": self.photo,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurriculumSyncSnapshot:
        return cls(
            version=str(data.get("version", "unversioned")),
            updated_at=str(data.get("updated_at", "")),
            markdown_sources=list(data.get("markdown_sources", [])),
            source_hashes=dict(data.get("source_hashes", {})),
            sources=dict(data.get("sources", {})),
            manifest=dict(data.get("manifest", {})),
            photo=data.get("photo"),
        )


@dataclass(frozen=True)
class CurriculumVersionSnapshot:
    version: str
    created_at: str
    source_hashes: dict[str, str]
    sources: dict[str, str]
    manifest: dict[str, Any]
    review_sha256: str | None = None
    additions_review: dict[str, Any] | None = None
    review_inputs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "version": self.version,
            "created_at": self.created_at,
            "source_hashes": self.source_hashes,
            "sources": self.sources,
            "manifest": self.manifest,
            "review_sha256": self.review_sha256,
            "additions_review": self.additions_review,
            "review_inputs": self.review_inputs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurriculumVersionSnapshot:
        return cls(
            version=str(data.get("version", "")),
            created_at=str(data.get("created_at", "")),
            source_hashes=dict(data.get("source_hashes", {})),
            sources=dict(data.get("sources", {})),
            manifest=dict(data.get("manifest", {})),
            review_sha256=data.get("review_sha256"),
            additions_review=data.get("additions_review"),
            review_inputs=list(data.get("review_inputs", [])),
        )


@dataclass(frozen=True)
class CandidateEvidenceSnapshot:
    schema_version: int
    fingerprint: str
    generated_at: str
    candidate: dict[str, Any]
    source_manifest_digest: str | None = None
    receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint,
            "generated_at": self.generated_at,
            "candidate": self.candidate,
            "source_manifest_digest": self.source_manifest_digest,
            "receipt": self.receipt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidateEvidenceSnapshot:
        return cls(
            schema_version=int(data.get("schema_version", 3)),
            fingerprint=str(data.get("fingerprint", "")),
            generated_at=str(data.get("generated_at", "")),
            candidate=dict(data.get("candidate", {})),
            source_manifest_digest=data.get("source_manifest_digest"),
            receipt=data.get("receipt"),
        )


@dataclass(frozen=True)
class ProfileSyncSnapshot:
    version: str
    updated_at: str
    catalog: dict[str, Any]
    catalog_sha256: str
    source_manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "version": self.version,
            "updated_at": self.updated_at,
            "catalog": self.catalog,
            "catalog_sha256": self.catalog_sha256,
            "source_manifest": self.source_manifest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileSyncSnapshot:
        return cls(
            version=str(data.get("version", "p001")),
            updated_at=str(data.get("updated_at", "")),
            catalog=dict(data.get("catalog", {})),
            catalog_sha256=str(data.get("catalog_sha256", "")),
            source_manifest=dict(data.get("source_manifest", {})),
        )


@dataclass(frozen=True)
class ProfileVersionSnapshot:
    version: str
    created_at: str
    catalog: dict[str, Any]
    catalog_sha256: str
    review: dict[str, Any] | None = None
    review_sha256: str | None = None
    source_manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "version": self.version,
            "created_at": self.created_at,
            "catalog": self.catalog,
            "catalog_sha256": self.catalog_sha256,
            "review": self.review,
            "review_sha256": self.review_sha256,
            "source_manifest": self.source_manifest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileVersionSnapshot:
        return cls(
            version=str(data.get("version", "")),
            created_at=str(data.get("created_at", "")),
            catalog=dict(data.get("catalog", {})),
            catalog_sha256=str(data.get("catalog_sha256", "")),
            review=data.get("review"),
            review_sha256=data.get("review_sha256"),
            source_manifest=dict(data.get("source_manifest", {})),
        )


@dataclass(frozen=True)
class ApplicationVersionSnapshot:
    version: str
    generated_at: str
    manifest: dict[str, Any]
    bundle: dict[str, Any]
    job: dict[str, Any]
    sources: dict[str, str]  # resume.tex, letter.tex, preamble.tex, motivation-letter.md, match-analysis.md
    quality_gate: dict[str, Any]
    semantic_review: dict[str, Any]
    document_text_sha256: dict[str, str]
    document_revision: int
    source_provenance: str
    artifacts: dict[str, Any]
    manual_revisions: list[dict[str, Any]] = field(default_factory=list)
    local_path: str | None = None
    notion_page_id: str | None = None
    notion_page_url: str | None = None
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "manifest": self.manifest,
            "bundle": self.bundle,
            "job": self.job,
            "sources": self.sources,
            "quality_gate": self.quality_gate,
            "semantic_review": self.semantic_review,
            "document_text_sha256": self.document_text_sha256,
            "document_revision": self.document_revision,
            "source_provenance": self.source_provenance,
            "artifacts": self.artifacts,
            "manual_revisions": self.manual_revisions,
            "local_path": self.local_path,
            "notion_page_id": self.notion_page_id,
            "notion_page_url": self.notion_page_url,
            "documents": dict(self.documents),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApplicationVersionSnapshot:
        return cls(
            version=str(data.get("version", "")),
            generated_at=str(data.get("generated_at", "")),
            manifest=dict(data.get("manifest", {})),
            bundle=dict(data.get("bundle", {})),
            job=dict(data.get("job", {})),
            sources=dict(data.get("sources", {})),
            quality_gate=dict(data.get("quality_gate", {})),
            semantic_review=dict(data.get("semantic_review", {})),
            document_text_sha256=dict(data.get("document_text_sha256", {})),
            document_revision=int(data.get("document_revision", 0)),
            source_provenance=str(data.get("source_provenance", "agent_generated")),
            artifacts=dict(data.get("artifacts", {})),
            manual_revisions=list(data.get("manual_revisions", [])),
            local_path=data.get("local_path"),
            notion_page_id=data.get("notion_page_id"),
            notion_page_url=data.get("notion_page_url"),
            documents=dict(data.get("documents", {})),
        )


@dataclass(frozen=True)
class ApplicationSyncSnapshot:
    application_id: str
    company: str
    company_slug: str
    role: str
    role_slug: str
    job_id_or_hash: str
    status: str
    current_version: str
    canonical_url: str | None = None
    local_path: str | None = None
    notion_page_id: str | None = None
    notion_page_url: str | None = None
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    match_summary: str | None = None
    selected_profile: str | None = None
    gaps: list[str] = field(default_factory=list)
    generated_at: str | None = None
    updated_at: str | None = None
    applied_at: str | None = None
    next_action_at: str | None = None
    notes: str | None = None
    versions: dict[str, ApplicationVersionSnapshot] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "company": self.company,
            "company_slug": self.company_slug,
            "role": self.role,
            "role_slug": self.role_slug,
            "job_id_or_hash": self.job_id_or_hash,
            "canonical_url": self.canonical_url,
            "local_path": self.local_path,
            "status": self.status,
            "current_version": self.current_version,
            "notion_page_id": self.notion_page_id,
            "notion_page_url": self.notion_page_url,
            "documents": dict(self.documents),
            "match_summary": self.match_summary,
            "selected_profile": self.selected_profile,
            "gaps": list(self.gaps),
            "generated_at": self.generated_at,
            "updated_at": self.updated_at or datetime.now(timezone.utc).isoformat(),
            "applied_at": self.applied_at,
            "next_action_at": self.next_action_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], versions: dict[str, ApplicationVersionSnapshot] | None = None
    ) -> ApplicationSyncSnapshot:
        return cls(
            application_id=str(data.get("application_id", "")),
            company=str(data.get("company", "")),
            company_slug=str(data.get("company_slug", "")),
            role=str(data.get("role", "")),
            role_slug=str(data.get("role_slug", "")),
            job_id_or_hash=str(data.get("job_id_or_hash", "")),
            canonical_url=data.get("canonical_url"),
            local_path=data.get("local_path"),
            status=str(data.get("status", "TO_APPLY")),
            current_version=str(data.get("current_version", "v001")),
            notion_page_id=data.get("notion_page_id"),
            notion_page_url=data.get("notion_page_url"),
            documents=dict(data.get("documents", {})),
            match_summary=data.get("match_summary"),
            selected_profile=data.get("selected_profile"),
            gaps=list(data.get("gaps", [])),
            generated_at=data.get("generated_at"),
            updated_at=data.get("updated_at"),
            applied_at=data.get("applied_at"),
            next_action_at=data.get("next_action_at"),
            notes=data.get("notes"),
            versions=versions or {},
        )


@dataclass(frozen=True)
class SyncResult:
    pushed: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    status: str = "OK"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SyncStatusReport:
    user_id: str
    curriculum_synced: bool
    profiles_synced: bool
    local_apps_count: int
    remote_apps_count: int
    pending_push: list[str] = field(default_factory=list)
    pending_pull: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
