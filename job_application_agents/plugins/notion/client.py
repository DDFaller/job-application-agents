from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .models import NotionCardPayload

DEFAULT_NOTION_VERSION = "2022-06-28"
DEFAULT_BASE_URL = "https://api.notion.com/v1"
STATUS_OPTIONS = [
    {"name": "TO_APPLY", "color": "blue"},
    {"name": "APPLIED", "color": "yellow"},
    {"name": "REAPPLY", "color": "orange"},
    {"name": "INTERVIEW", "color": "purple"},
    {"name": "FINAL_INTERVIEW", "color": "purple"},
    {"name": "OFFER", "color": "green"},
    {"name": "HIRED", "color": "green"},
    {"name": "REJECTED", "color": "red"},
    {"name": "WITHDRAWN", "color": "gray"},
    {"name": "OFFER_DECLINED", "color": "gray"},
    {"name": "HUMAN_REVIEW", "color": "yellow"},
    {"name": "SUBMISSION_UNCERTAIN", "color": "orange"},
    {"name": "DROPPED", "color": "red"},
]


class NotionAPIError(RuntimeError):
    """Exception raised for errors returned by the Notion API."""
    pass


class NotionClient:
    """Client for interacting with the Notion REST API and file upload endpoints."""

    def __init__(
        self,
        token: str,
        notion_version: str = DEFAULT_NOTION_VERSION,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
    ):
        if not token:
            raise ValueError("Notion token is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.token = token.strip()
        self.notion_version = notion_version
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        # A foreground queue normally synchronizes several applications with
        # one client. Keep the board index and schema warm for that run.
        self._database_cache: dict[str, list[dict[str, Any]]] = {}
        self._prepared_databases: set[str] = set()

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.notion_version,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        req_headers = headers or self._headers()
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise NotionAPIError(f"Notion API error ({exc.code} {exc.reason}): {error_body}") from exc


    # =========================================================================
    # File Upload Protocol (2-Step)
    # =========================================================================

    def create_file_upload(self, filename: str, content_type: str) -> tuple[str, str]:
        """Step 1: Initialize a file upload and obtain the upload URL and ID."""
        data = self._request("POST", "file_uploads", data={})
        file_id = data.get("id")
        upload_url = data.get("upload_url")
        if not file_id or not upload_url:
            raise RuntimeError(f"invalid file upload initiation response: {data}")
        return str(file_id), str(upload_url)

    def upload_file_bytes(
        self,
        upload_url: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
    ) -> bool:
        """Step 2: Stream multipart file bytes to the upload URL."""
        boundary = "----jaa-notion-boundary-76f01432"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
        payload = prefix + file_bytes + suffix

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.notion_version,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        request = urllib.request.Request(upload_url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.status in (200, 201, 204)
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Notion file byte upload failed ({exc.code}): {err}") from exc

    def upload_file(self, filename: str, content_type: str, file_bytes: bytes) -> str:
        """Convenience method executing the full 2-step upload protocol."""
        file_id, upload_url = self.create_file_upload(filename, content_type)
        self.upload_file_bytes(upload_url, filename, content_type, file_bytes)
        return file_id

    # =========================================================================
    # Card & Page Management
    # =========================================================================

    def _safe_rich_text(self, content: str, max_len: int = 2000) -> list[dict[str, Any]]:
        if not content:
            return []
        return [{"text": {"content": content[:max_len]}}]

    def _split_text_to_paragraphs(self, text: str, max_chunk: int = 1900) -> list[dict[str, Any]]:
        if not text:
            return [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "None"}}]}}]

        blocks: list[dict[str, Any]] = []
        lines = text.split("\n\n")
        for para in lines:
            para = para.strip()
            if not para:
                continue
            while len(para) > max_chunk:
                chunk = para[:max_chunk]
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
                para = para[max_chunk:]
            if para:
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": para}}]}})

        if not blocks:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "None"}}]}})
        return blocks

    def _build_properties(
        self, payload: NotionCardPayload, *, include_empty_editable: bool = False
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {
            "Application": {"title": [{"text": {"content": (payload.application_title or "Untitled Application")[:2000]}}]},
            "Status": {"select": {"name": payload.status}},
        }
        if payload.company:
            properties["Company"] = {"rich_text": self._safe_rich_text(payload.company)}
        if payload.role:
            properties["Role"] = {"rich_text": self._safe_rich_text(payload.role)}
        if payload.location:
            properties["Location"] = {"rich_text": self._safe_rich_text(payload.location)}
        if payload.work_model:
            properties["Work Model"] = {"select": {"name": payload.work_model}}
        if payload.source:
            properties["Source"] = {"select": {"name": payload.source}}
        if payload.job_url:
            properties["Job URL"] = {"url": payload.job_url[:2000]}
        if payload.source_job_id:
            properties["Source Job ID"] = {"rich_text": self._safe_rich_text(payload.source_job_id)}
        if payload.application_id:
            properties["Application ID"] = {"rich_text": self._safe_rich_text(payload.application_id)}
        if payload.current_version:
            properties["Current Version"] = {"rich_text": self._safe_rich_text(payload.current_version)}
        if payload.generated_at:
            properties["Generated At"] = {"date": {"start": payload.generated_at}}
        if payload.applied_at or include_empty_editable:
            properties["Applied At"] = {"date": {"start": payload.applied_at}} if payload.applied_at else {"date": None}
        if payload.next_action_at or include_empty_editable:
            properties["Next Action At"] = {"date": {"start": payload.next_action_at}} if payload.next_action_at else {"date": None}
        if payload.local_bundle_path:
            properties["Local Bundle Path"] = {"rich_text": self._safe_rich_text(payload.local_bundle_path)}
        if payload.match_summary:
            properties["Match Summary"] = {"rich_text": self._safe_rich_text(payload.match_summary)}
        if payload.match_score is not None:
            properties["Match Score"] = {"number": payload.match_score}
        if payload.notes or include_empty_editable:
            properties["Notes"] = {"rich_text": self._safe_rich_text(payload.notes or "")}
        return properties

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve the latest page state for webhook processing."""
        return self._request("GET", f"pages/{page_id}")

    def query_database(self, database_id: str) -> list[dict[str, Any]]:
        """Return all pages in a database, following Notion pagination."""
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            response = self._request("POST", f"databases/{database_id}/query", data=body)
            results.extend(response.get("results", []))
            if not response.get("has_more"):
                return results
            cursor = response.get("next_cursor")
            if not cursor:
                return results

    def warm_database(self, database_id: str) -> list[dict[str, Any]]:
        """Return a per-client board snapshot, fetching it only once."""
        if database_id not in self._database_cache:
            self._database_cache[database_id] = self.query_database(database_id)
        return self._database_cache[database_id]

    def invalidate_database_cache(self, database_id: str) -> None:
        self._database_cache.pop(database_id, None)


    def _build_document_blocks(
        self,
        version: str,
        resume_file_id: str | None,
        letter_file_id: str | None,
        zip_file_id: str | None,
        zip_filename: str = "sources.zip",
        screenshot_file_id: str | None = None,
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        if resume_file_id:
            blocks.extend([
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"Current resume — {version}"}}]},
                },
                {
                    "object": "block",
                    "type": "pdf",
                    "pdf": {"type": "file_upload", "file_upload": {"id": resume_file_id}},
                },
            ])
        if letter_file_id:
            blocks.extend([
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"Current motivation letter — {version}"}}]},
                },
                {
                    "object": "block",
                    "type": "pdf",
                    "pdf": {"type": "file_upload", "file_upload": {"id": letter_file_id}},
                },
            ])
        if zip_file_id:
            safe_zip_name = zip_filename if len(zip_filename) <= 80 else (zip_filename[:76] + ".zip")
            blocks.extend([
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"Editable LaTeX sources — {version}"}}]},
                },
                {
                    "object": "block",
                    "type": "file",
                    "file": {"type": "file_upload", "file_upload": {"id": zip_file_id}, "name": safe_zip_name},
                },
            ])
        if screenshot_file_id:
            blocks.extend([
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"Submission Proof Screenshot — {version}"}}]},
                },
                {
                    "object": "block",
                    "type": "image",
                    "image": {"type": "file_upload", "file_upload": {"id": screenshot_file_id}},
                },
            ])
        return blocks




    def _build_page_children(
        self,
        payload: NotionCardPayload,
        resume_file_id: str | None,
        letter_file_id: str | None,
        zip_file_id: str | None,
        zip_filename: str = "sources.zip",
        screenshot_file_id: str | None = None,
    ) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Job Summary"}}]},
            },
        ]
        children.extend(self._split_text_to_paragraphs(payload.job_summary_text or "Job details recorded in bundle."))

        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Requirements"}}]},
        })
        children.extend(self._split_text_to_paragraphs(payload.requirements_text or "See job posting details."))

        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Match Analysis"}}]},
        })
        if payload.match_score is not None:
            bd = payload.match_breakdown or {}
            score_summary = (
                f"🎯 Overall Match Score: {payload.match_score} / 100\n"
                f"• 🛠️ Skills Match: {bd.get('skills_score', 'N/A')} / 30\n"
                f"• ⏳ Experience Match: {bd.get('experience_score', 'N/A')} / 25\n"
                f"• 💼 Role Match: {bd.get('role_score', 'N/A')} / 20\n"
                f"• 📍 Location Match: {bd.get('location_score', 'N/A')} / 15\n"
                f"• 🏢 Company Fit: {bd.get('company_fit_score', 'N/A')} / 5\n"
                f"• 💰 Compensation: {bd.get('compensation_score', 'N/A')} / 5"
            )
            children.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": score_summary}}],
                    "icon": {"type": "emoji", "emoji": "🎯"},
                },
            })
        children.extend(self._split_text_to_paragraphs(payload.match_analysis_text or "Match analysis generated."))


        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Gaps"}}]},
        })
        children.extend(self._split_text_to_paragraphs(payload.gaps_text or "No critical gaps identified."))

        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Current Documents"}}]},
        })
        children.extend(
            self._build_document_blocks(
                version=payload.current_version,
                resume_file_id=resume_file_id,
                letter_file_id=letter_file_id,
                zip_file_id=zip_file_id,
                zip_filename=zip_filename,
                screenshot_file_id=screenshot_file_id,
            )
        )
        return children

    def ensure_database_properties(self, database_id: str) -> bool:
        """Add synchronization schema properties to the target database."""
        if database_id in self._prepared_databases:
            return True
        try:
            self._request(
                "PATCH",
                f"databases/{database_id}",
                data={
                    "properties": {
                        "Match Score": {"number": {"format": "number"}},
                        "Application ID": {"rich_text": {}},
                        "Status": {"select": {"options": STATUS_OPTIONS}},
                    }
                },
            )
            self._prepared_databases.add(database_id)
            return True
        except Exception:
            return False

    def create_card(
        self,
        database_id: str,
        payload: NotionCardPayload,
        resume_file_id: str | None = None,
        letter_file_id: str | None = None,
        zip_file_id: str | None = None,
        zip_filename: str = "sources.zip",
        screenshot_file_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new page in the target database with properties and content blocks."""
        props = self._build_properties(payload)
        body = {
            "parent": {"database_id": database_id},
            "properties": props,
            "children": self._build_page_children(
                payload=payload,
                resume_file_id=resume_file_id,
                letter_file_id=letter_file_id,
                zip_file_id=zip_file_id,
                zip_filename=zip_filename,
                screenshot_file_id=screenshot_file_id,
            ),
        }
        try:
            page = self._request("POST", "pages", data=body)
            self._database_cache.setdefault(database_id, []).append(page)
            return page
        except NotionAPIError as exc:
            err_str = str(exc)
            if "Match Score is not a property" in err_str and "Match Score" in props:
                self.ensure_database_properties(database_id)
                try:
                    return self._request("POST", "pages", data=body)
                except NotionAPIError:
                    props.pop("Match Score", None)
                    body["properties"] = props
                    return self._request("POST", "pages", data=body)
            if "Application is not a property" in err_str and "Application" in props:
                props["Name"] = props.pop("Application")
                body["properties"] = props
                return self._request("POST", "pages", data=body)
            raise

    def update_card_documents(
        self,
        page_id: str,
        version: str,
        resume_file_id: str | None = None,
        letter_file_id: str | None = None,
        zip_file_id: str | None = None,
        zip_filename: str = "sources.zip",
        screenshot_file_id: str | None = None,
    ) -> bool:
        """Replace the Current Documents section blocks on an existing page."""
        # 1. Fetch current blocks
        blocks_data = self._request("GET", f"blocks/{page_id}/children")
        results = blocks_data.get("results", [])

        # 2. Locate heading_2 with text "Current Documents"
        heading_index = -1
        for i, block in enumerate(results):
            if block.get("type") == "heading_2":
                rich_text = block.get("heading_2", {}).get("rich_text", [])
                if rich_text and rich_text[0].get("plain_text") == "Current Documents":
                    heading_index = i
                    break

        if heading_index != -1:
            # Delete blocks after heading
            for block in results[heading_index + 1 :]:
                self._request("DELETE", f"blocks/{block['id']}")
        else:
            # Append heading if missing
            self._request(
                "PATCH",
                f"blocks/{page_id}/children",
                data={
                    "children": [
                        {
                            "object": "block",
                            "type": "heading_2",
                            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Current Documents"}}]},
                        }
                    ]
                },
            )

        # 3. Append new document blocks
        new_blocks = self._build_document_blocks(
            version=version,
            resume_file_id=resume_file_id,
            letter_file_id=letter_file_id,
            zip_file_id=zip_file_id,
            zip_filename=zip_filename,
            screenshot_file_id=screenshot_file_id,
        )
        if new_blocks:
            self._request("PATCH", f"blocks/{page_id}/children", data={"children": new_blocks})
        return True


    def update_card_properties(self, page_id: str, payload: NotionCardPayload) -> dict[str, Any]:
        """Update database properties of an existing page."""
        props = self._build_properties(payload, include_empty_editable=True)
        try:
            return self._request("PATCH", f"pages/{page_id}", data={"properties": props})
        except NotionAPIError as exc:
            err_str = str(exc)
            if "Match Score is not a property" in err_str and "Match Score" in props:
                props.pop("Match Score", None)
                try:
                    return self._request("PATCH", f"pages/{page_id}", data={"properties": props})
                except NotionAPIError:
                    pass
            if "Application is not a property" in err_str and "Application" in props:
                props["Name"] = props.pop("Application")
                return self._request("PATCH", f"pages/{page_id}", data={"properties": props})
            raise



    def archive_card(self, page_id: str) -> bool:
        """Archive (delete) a card page in Notion."""
        res = self._request("PATCH", f"pages/{page_id}", data={"archived": True})
        return bool(res.get("archived", False))

    def find_card_by_job_url(self, database_id: str, job_url: str) -> dict[str, Any] | None:
        """Find an existing card in the database by Job URL."""
        if not job_url:
            return None
        for page in self.warm_database(database_id):
            properties = page.get("properties", {})
            value = properties.get("Job URL", {})
            url_value = value.get("url") if isinstance(value, dict) else None
            if url_value == job_url:
                return page
        return None

    def add_comment(self, page_id: str, comment_text: str) -> dict[str, Any]:
        """Post a comment to a Notion page."""
        clean_page_id = page_id.replace("-", "")
        body = {
            "parent": {"page_id": clean_page_id},
            "rich_text": [{"text": {"content": comment_text}}],
        }
        return self._request("POST", "comments", data=body)
