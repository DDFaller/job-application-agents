from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any

from job_application_agents.sync.firestore import FirestoreUserSyncRepository

from . import DEFAULT_DATABASE_ID, NotionPlugin
from .client import NotionClient
from .firestore import FirestoreNotionJobRepository
from .models import NotionSyncJob


class NotionWorker:
    """Asynchronous worker executing queued Notion sync operations."""

    def __init__(
        self,
        repository: FirestoreNotionJobRepository,
        sync_repository: FirestoreUserSyncRepository | None = None,
        plugin: NotionPlugin | None = None,
        worker_id: str | None = None,
    ):
        self.repository = repository
        self.sync_repository = sync_repository or FirestoreUserSyncRepository(repository.project_id)
        self.plugin = plugin or NotionPlugin()
        self.worker_id = worker_id or f"notion-worker-{socket.gethostname()}-{os.getpid()}"
        self.current_job: str | None = None
        self.stopping = threading.Event()

    def heartbeat_loop(self) -> None:
        while not self.stopping.wait(30):
            try:
                if self.current_job:
                    self.repository.heartbeat(self.current_job, self.worker_id)
            except Exception:
                pass

    def process(self, job: NotionSyncJob) -> None:
        self.current_job = job.id
        try:
            if job.action == "DELETE":
                res = self.plugin.on_application_deleted(
                    user_id=job.user_id,
                    application_id=job.application_id,
                    metadata=job.payload,
                )
                if res.status == "ERROR":
                    raise RuntimeError(res.error_message or "failed to archive Notion card")
                self.repository.succeed(job.id, self.worker_id, res.details)
                return

            # Action == CREATE_OR_UPDATE
            # Fetch application and version from sync repository if payload is minimal
            app_snap = self.sync_repository.fetch_application(job.user_id, job.application_id)
            app_data = app_snap.to_dict() if app_snap else job.payload

            version_id = job.payload.get("current_version") or (app_snap.current_version if app_snap else "v001")
            version_snap = self.sync_repository.fetch_application_version(job.user_id, job.application_id, version_id)
            version_data = version_snap.to_dict() if version_snap else {"version": version_id}

            # If local files are referenced, load PDF bytes
            file_map: dict[str, bytes] = {}
            local_path = app_data.get("local_path")
            if local_path and os.path.isdir(local_path):
                r_pdf = Path(local_path) / "resume.pdf"
                m_pdf = Path(local_path) / "motivation-letter.pdf"
                if r_pdf.is_file():
                    file_map["resume.pdf"] = r_pdf.read_bytes()
                if m_pdf.is_file():
                    file_map["motivation-letter.pdf"] = m_pdf.read_bytes()

                # Check for Playwright screenshots
                for s_name in ("submission-success.png", "submission-confirmation.png", "apply-preview.png", "pre-submit.png"):
                    s_file = Path(local_path) / s_name
                    if s_file.is_file():
                        file_map[s_name] = s_file.read_bytes()
                        break


            # Check user-specific Notion database config
            user_notion_config = None
            if hasattr(self.sync_repository, "get_user_notion_config"):
                user_notion_config = self.sync_repository.get_user_notion_config(job.user_id)

            target_db_id = (
                (user_notion_config.get("database_id") if user_notion_config else None)
                or job.payload.get("notion_database_id")
            )

            # Execute plugin save
            res = self.plugin.on_application_saved(
                user_id=job.user_id,
                application_id=job.application_id,
                application_data=app_data,
                version_data=version_data,
                files=file_map,
                database_id=target_db_id,
            )

            if res.status == "ERROR":
                raise RuntimeError(res.error_message or "Notion sync error")

            # Update Firestore application document with Notion page and document URLs
            page_id = res.details.get("notion_page_id")
            page_url = res.details.get("notion_page_url")
            docs = res.details.get("documents", {})

            if page_id or page_url or docs:
                app_update: dict[str, Any] = {}
                if page_id:
                    app_update["notion_page_id"] = page_id
                if page_url:
                    app_update["notion_page_url"] = page_url
                if docs:
                    app_update["documents"] = docs
                current_sync = dict(app_data.get("sync") or {})
                app_update["sync"] = {
                    **current_sync,
                    "last_source": "firestore",
                    "last_success_at": datetime.now(timezone.utc).isoformat(),
                    "conflict": None,
                }
                self.sync_repository.update_application_fields(job.user_id, job.application_id, app_update)

            # Post comment to Notion page if comment payload exists
            comment_text = job.payload.get("comment") or app_data.get("comment") or app_data.get("review_comment")
            if page_id and comment_text:
                try:
                    self.plugin._get_client().add_comment(page_id, comment_text)
                    print(f"✅ Posted review comment to Notion card {page_id}!")
                except Exception as ce:
                    print(f"Warning: could not post comment to Notion card: {ce}")

            self.repository.succeed(job.id, self.worker_id, res.details)

        except Exception as exc:
            self.repository.fail(job.id, self.worker_id, str(exc), retryable=True)
        finally:
            self.current_job = None

    def run(self, once: bool = False) -> int:
        heartbeat = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat.start()
        last_expiry_check = 0.0

        while not self.stopping.is_set():
            now = time.monotonic()
            if now - last_expiry_check >= 60:
                self.repository.requeue_expired()
                last_expiry_check = now

            job = self.repository.claim(self.worker_id)
            if job:
                self.process(job)
                if once:
                    break
            elif once:
                break
            else:
                self.stopping.wait(5)

        self.stopping.set()
        heartbeat.join(timeout=2)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued Notion sync jobs")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--project-id", default=os.environ.get("JAA_FIREBASE_PROJECT_ID", "demo-job-application-agents"))
    parser.add_argument("--database-id", default=os.environ.get("NOTION_DATABASE_ID", DEFAULT_DATABASE_ID))
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("Error: NOTION_TOKEN environment variable is required")
        return 1

    repo = FirestoreNotionJobRepository(project_id=args.project_id)
    plugin = NotionPlugin(token=token, database_id=args.database_id)
    worker = NotionWorker(repository=repo, plugin=plugin)
    print(f"Starting NotionWorker ({worker.worker_id})...")
    return worker.run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
