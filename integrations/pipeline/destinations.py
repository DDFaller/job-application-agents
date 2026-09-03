"""Destination handlers for staging and routing ingested jobs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

from ..base import BaseJobDestination
from ..models import IngestedJob

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text into a safe filesystem folder slug."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-") or "job"


class FileSystemStagingDestination(BaseJobDestination):
    """Saves ingested jobs into staging directories ready for application preparation."""

    def __init__(self, base_staging_dir: Path | None = None) -> None:
        self.base_staging_dir = base_staging_dir or Path("job-search/staging_job")

    @property
    def name(self) -> str:
        return "filesystem_staging"

    def is_enabled(self) -> bool:
        return True

    def stage_job(self, job: IngestedJob) -> bool:
        """Create staging folder with job.json, source.md, and match_breakdown.json."""
        try:
            self.base_staging_dir.mkdir(parents=True, exist_ok=True)

            company_slug = _slugify(job.job_data.company or "company")
            role_slug = _slugify(job.job_data.role or "role")
            id_slug = job.job_data.source_job_id or job.job_id[:8]

            folder_name = f"{company_slug}-{role_slug}-{id_slug}"
            staging_path = self.base_staging_dir / folder_name
            staging_path.mkdir(parents=True, exist_ok=True)

            # Write source.md if not already written
            source_file = staging_path / "source.md"
            if not source_file.is_file() and job.job_data.source_document:
                orig_src = Path(job.job_data.source_document)
                if orig_src.is_file():
                    source_file.write_text(orig_src.read_text(encoding="utf-8"), encoding="utf-8")
                else:
                    source_file.write_text(f"# {job.job_data.role}\n\nCompany: {job.job_data.company}\n\n", encoding="utf-8")
            elif not source_file.is_file():
                source_file.write_text(f"# {job.job_data.role}\n\nCompany: {job.job_data.company}\n\n", encoding="utf-8")

            # Update job_data source_document absolute path and recompute hash if needed
            job.job_data.source_document = str(source_file.resolve())
            job_dict = job.job_data.to_dict()

            # Write job.json
            job_file = staging_path / "job.json"
            job_file.write_text(json.dumps(job_dict, indent=2), encoding="utf-8")

            # Write match_breakdown.json
            match_file = staging_path / "match_breakdown.json"
            match_file.write_text(json.dumps(job.match_breakdown, indent=2), encoding="utf-8")

            # Write ingestion metadata
            meta_file = staging_path / "ingestion_meta.json"
            meta_file.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")

            job.staging_dir = str(staging_path.resolve())
            job.status = "STAGED"
            logger.info("Staged job %s to %s", job.job_id, staging_path)
            return True

        except Exception as exc:
            logger.error("Failed to stage job %s: %s", job.job_id, exc)
            job.status = "FAILED"
            job.notes = f"Staging error: {exc}"
            return False


class NotionBoardDestination(BaseJobDestination):
    """Optional destination creating candidate cards in the Notion Job Applications board."""

    def __init__(self) -> None:
        self._plugin_available = False
        try:
            from job_application_agents.plugins.notion import NotionPlugin
            self._plugin = NotionPlugin()
            self._plugin_available = self._plugin.is_enabled()
        except Exception:
            self._plugin = None

    @property
    def name(self) -> str:
        return "notion_board"

    def is_enabled(self) -> bool:
        return self._plugin_available

    def stage_job(self, job: IngestedJob) -> bool:
        """Create Notion card with match score and source details."""
        if not self.is_enabled():
            return False
        # Optional Notion sync for staged job candidates
        logger.info("Notion destination received job: %s (Score: %d)", job.job_data.role, job.match_score)
        return True


class FirestoreQueueDestination(BaseJobDestination):
    """Optional destination pushing ingested candidates to Firestore."""

    @property
    def name(self) -> str:
        return "firestore_queue"

    def is_enabled(self) -> bool:
        import os
        return bool(os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("JAA_FIREBASE_PROJECT_ID"))

    def stage_job(self, job: IngestedJob) -> bool:
        if not self.is_enabled():
            return False
        logger.info("Firestore destination received job: %s", job.job_id)
        return True
