from __future__ import annotations

import io
import os
from dataclasses import replace
from typing import Any
import zipfile

from job_application_agents.plugins.base import DocumentSinkPlugin, SinkResult, registry
from job_application_agents.config import load_storage_config

from .client import NotionClient
from .firestore import FirestoreNotionJobRepository
from .models import NotionCardPayload, NotionFileRef, NotionSyncJob

DEFAULT_DATABASE_ID = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"


class NotionPlugin(DocumentSinkPlugin):
    """Notion tracking and document hosting plugin."""

    def __init__(
        self,
        token: str | None = None,
        database_id: str | None = None,
        client: NotionClient | None = None,
    ):
        self._token = token
        configured_database_id = None
        if database_id is None and not os.environ.get("NOTION_DATABASE_ID"):
            configured_database_id = load_storage_config().notion_database_id
        self._database_id = (
            database_id
            or os.environ.get("NOTION_DATABASE_ID")
            or configured_database_id
            or DEFAULT_DATABASE_ID
        )
        self._client = client

    @property
    def name(self) -> str:
        return "notion"

    def get_token(self) -> str | None:
        return self._token or os.environ.get("NOTION_TOKEN")

    def is_enabled(self) -> bool:
        return bool(self.get_token())

    def _get_client(self) -> NotionClient:
        if self._client:
            return self._client
        token = self.get_token()
        if not token:
            raise RuntimeError("Notion token is not configured (set NOTION_TOKEN)")
        self._client = NotionClient(token=token)
        return self._client

    def _create_source_zip(self, sources: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, content in sorted(sources.items()):
                zf.writestr(filename, content)
        return buf.getvalue()

    @staticmethod
    def _property_value(page: dict[str, Any], name: str) -> Any:
        properties = page.get("properties", {}) if isinstance(page, dict) else {}
        prop = properties.get(name, {}) if isinstance(properties, dict) else {}
        if not isinstance(prop, dict):
            return None
        kind = prop.get("type")
        value = prop.get(kind) if kind else None
        if kind == "select":
            return (value or {}).get("name") if isinstance(value, dict) else None
        if kind == "date":
            return (value or {}).get("start") if isinstance(value, dict) else None
        if kind in {"rich_text", "title"}:
            items = value if isinstance(value, list) else []
            return "".join(str(item.get("plain_text", "")) for item in items if isinstance(item, dict)) or None
        return value

    def on_application_saved(
        self,
        user_id: str,
        application_id: str,
        application_data: dict[str, Any],
        version_data: dict[str, Any],
        files: dict[str, bytes] | None = None,
        database_id: str | None = None,
    ) -> SinkResult:
        if not self.is_enabled():
            return SinkResult(plugin_name=self.name, status="SKIPPED", details={"reason": "NOTION_TOKEN not set"})

        target_database_id = (
            database_id
            or application_data.get("notion_database_id")
            or self._database_id
            or DEFAULT_DATABASE_ID
        )

        client = self._get_client()
        # Older boards predate the stable Application ID property. Updating the
        # schema once makes webhook-to-Firestore identity resolution reliable.
        client.ensure_database_properties(target_database_id)
        version = version_data.get("version", "v001")
        file_map = files or {}

        # 1. Upload files
        uploaded_docs: dict[str, dict[str, Any]] = {}
        resume_file_id: str | None = None
        letter_file_id: str | None = None
        zip_file_id: str | None = None

        if "resume.pdf" in file_map:
            pdf_bytes = file_map["resume.pdf"]
            resume_file_id = client.upload_file("resume.pdf", "application/pdf", pdf_bytes)
            uploaded_docs["resume.pdf"] = {
                "filename": "resume.pdf",
                "content_type": "application/pdf",
                "file_id": resume_file_id,
                "bytes": len(pdf_bytes),
                "sink": "notion",
            }

        if "motivation-letter.pdf" in file_map:
            letter_bytes = file_map["motivation-letter.pdf"]
            letter_file_id = client.upload_file("motivation-letter.pdf", "application/pdf", letter_bytes)
            uploaded_docs["motivation-letter.pdf"] = {
                "filename": "motivation-letter.pdf",
                "content_type": "application/pdf",
                "file_id": letter_file_id,
                "bytes": len(letter_bytes),
                "sink": "notion",
            }

        # Source ZIP
        sources = version_data.get("sources", {})
        if sources:
            zip_bytes = self._create_source_zip(sources)
            zip_filename = f"{application_id}-{version}-sources.zip"
            zip_file_id = client.upload_file(zip_filename, "application/zip", zip_bytes)
            uploaded_docs[zip_filename] = {
                "filename": zip_filename,
                "content_type": "application/zip",
                "file_id": zip_file_id,
                "bytes": len(zip_bytes),
                "sink": "notion",
            }
        else:
            zip_filename = "sources.zip"

        # Screenshot
        screenshot_file_id: str | None = None
        for s_name in ("screenshot.png", "submission-success.png", "submission-confirmation.png", "apply-preview.png", "pre-submit.png"):
            if s_name in file_map:
                s_bytes = file_map[s_name]
                screenshot_file_id = client.upload_file(s_name, "image/png", s_bytes)
                uploaded_docs[s_name] = {
                    "filename": s_name,
                    "content_type": "image/png",
                    "file_id": screenshot_file_id,
                    "bytes": len(s_bytes),
                    "sink": "notion",
                }
                break

        # 2. Build Card Payload
        job = application_data.get("job", {})
        match = version_data.get("match", {}) or application_data.get("match", {})

        # Match Score & Breakdown
        match_score = version_data.get("match_score") or application_data.get("match_score")
        match_breakdown = version_data.get("match_breakdown") or application_data.get("match_breakdown")
        if match_score is None and job:
            from job_application_agents.auto_apply.matcher import JobMatchScorer
            scorer_result = JobMatchScorer.score_job(job)
            match_score = scorer_result.total_score
            match_breakdown = scorer_result.to_dict()

        payload = NotionCardPayload(
            application_title=application_data.get("title") or f"{job.get('company', application_id)} - {job.get('role', 'Application')}",
            company=job.get("company") or application_id,
            role=job.get("role") or "Candidate",
            status=application_data.get("status", "TO_APPLY"),
            location=job.get("location", ""),
            work_model=job.get("work_model", "Unspecified"),
            source=job.get("source", "Other ATS"),
            job_url=job.get("url") or job.get("job_url"),
            source_job_id=job.get("job_id") or job.get("source_job_id") or application_id,
            current_version=version,
            generated_at=version_data.get("created_at") or application_data.get("updated_at"),
            applied_at=application_data.get("applied_at"),
            next_action_at=application_data.get("next_action_at"),
            local_bundle_path=application_data.get("local_path"),
            match_summary=match.get("summary") or match.get("rationale"),
            match_score=match_score,
            match_breakdown=match_breakdown,
            notes=application_data.get("notes"),
            job_summary_text=job.get("summary", ""),
            requirements_text="\n".join(job.get("requirements", [])) if isinstance(job.get("requirements"), list) else str(job.get("requirements", "")),
            match_analysis_text=match.get("analysis") or match.get("rationale") or "",
            gaps_text="\n".join(match.get("gaps", [])) if isinstance(match.get("gaps"), list) else str(match.get("gaps", "")),
            application_id=application_id,
        )


        # 3. Create or Update Card
        page_id = application_data.get("notion_page_id")
        existing_page: dict[str, Any] | None = None
        if not page_id and payload.job_url:
            existing_page = client.find_card_by_job_url(target_database_id, payload.job_url)
            if existing_page:
                page_id = existing_page.get("id")

        if page_id:
            # Notion is the human workflow authority. Refreshing local PDFs or
            # editable sources must never reset a status/date/note that a user
            # changed on the page. Direct lifecycle operations use the client
            # explicitly and are therefore still able to change those fields.
            existing_page = existing_page or client.retrieve_page(str(page_id))
            preserved = {
                field: self._property_value(existing_page, notion_name)
                for field, notion_name in (
                    ("status", "Status"),
                    ("applied_at", "Applied At"),
                    ("next_action_at", "Next Action At"),
                    ("notes", "Notes"),
                )
            }
            payload = replace(
                payload,
                **{key: value for key, value in preserved.items() if value is not None},
            )
            client.update_card_properties(page_id, payload)
            client.update_card_documents(
                page_id=page_id,
                version=version,
                resume_file_id=resume_file_id,
                letter_file_id=letter_file_id,
                zip_file_id=zip_file_id,
                zip_filename=zip_filename,
                screenshot_file_id=screenshot_file_id,
            )
            page_url = f"https://notion.so/{page_id.replace('-', '')}"
        else:
            page = client.create_card(
                database_id=target_database_id,
                payload=payload,
                resume_file_id=resume_file_id,
                letter_file_id=letter_file_id,
                zip_file_id=zip_file_id,
                zip_filename=zip_filename,
                screenshot_file_id=screenshot_file_id,
            )
            page_id = page.get("id")
            page_url = page.get("url") or (f"https://notion.so/{page_id.replace('-', '')}" if page_id else None)



        return SinkResult(
            plugin_name=self.name,
            status="OK",
            details={
                "notion_page_id": page_id,
                "notion_page_url": page_url,
                "documents": uploaded_docs,
            },
        )

    def on_application_deleted(
        self,
        user_id: str,
        application_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SinkResult:
        if not self.is_enabled():
            return SinkResult(plugin_name=self.name, status="SKIPPED")
        page_id = (metadata or {}).get("notion_page_id")
        if not page_id:
            return SinkResult(plugin_name=self.name, status="SKIPPED", details={"reason": "no notion_page_id"})
        client = self._get_client()
        client.archive_card(page_id)
        return SinkResult(plugin_name=self.name, status="OK", details={"archived_page_id": page_id})


# Auto-register Notion plugin in global registry
registry.register(NotionPlugin())

__all__ = [
    "DEFAULT_DATABASE_ID",
    "FirestoreNotionJobRepository",
    "NotionCardPayload",
    "NotionClient",
    "NotionFileRef",
    "NotionPlugin",
    "NotionSyncJob",
]
