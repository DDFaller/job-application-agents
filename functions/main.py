"""Firebase Functions adapters for automatic Firestore/Notion sync.

The core handlers remain importable without the Firebase Functions SDK so the
repository's unit tests can run locally.
"""

from __future__ import annotations

import json
import os
from typing import Any

from job_application_agents.plugins.notion.client import NotionClient
from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
from job_application_agents.sync.firestore import FirestoreUserSyncRepository

from .handlers import (
    handle_firestore_application_write,
    handle_notion_webhook,
    reconcile_notion,
)


def _repositories() -> tuple[FirestoreUserSyncRepository, FirestoreNotionJobRepository]:
    project_id = os.environ.get("JAA_FIREBASE_PROJECT_ID") or os.environ.get("GCLOUD_PROJECT")
    if not project_id:
        raise RuntimeError("JAA_FIREBASE_PROJECT_ID or GCLOUD_PROJECT is required")
    sync_repo = FirestoreUserSyncRepository(project_id=project_id)
    return sync_repo, FirestoreNotionJobRepository(project_id=project_id, client=sync_repo.client)


def _notion_client() -> NotionClient:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN is not configured")
    return NotionClient(token=token, notion_version=os.environ.get("NOTION_API_VERSION", "2022-06-28"))


try:
    from firebase_functions import firestore_fn, https_fn, scheduler_fn

    @firestore_fn.on_document_written(document="users/{userId}/applications/{applicationId}")
    def on_application_written(event: Any) -> None:
        before = event.data.before.to_dict() if event.data and event.data.before else None
        after = event.data.after.to_dict() if event.data and event.data.after else None
        sync_repo, notion_repo = _repositories()
        handle_firestore_application_write(
            user_id=event.params["userId"],
            application_id=event.params["applicationId"],
            before=before,
            after=after,
            sync_repository=sync_repo,
            notion_repository=notion_repo,
        )

    # Keep the bootstrap endpoint deployable before NOTION_TOKEN is configured.
    # Verification requests are handled without calling the Notion API; the
    # full sync deployment can add the API secret after the subscription exists.
    @https_fn.on_request(secrets=["NOTION_TOKEN"])
    def notion_webhook(request: Any) -> Any:
        raw_body = request.get_data(cache=True, as_text=False)
        payload = request.get_json(silent=True) or {}
        verification = payload.get("verification_token")
        if verification:
            sync_repo, notion_repo = _repositories()
            result = handle_notion_webhook(
                raw_body=raw_body,
                signature=None,
                verification_token=None,
                payload=payload,
                notion_client=None,
                sync_repository=sync_repo,
                notion_repository=notion_repo,
            )
            return https_fn.Response(json.dumps(result), status=200, mimetype="application/json")
        try:
            sync_repo, notion_repo = _repositories()
            result = handle_notion_webhook(
                raw_body=raw_body,
                signature=request.headers.get("X-Notion-Signature"),
                verification_token=os.environ.get("NOTION_WEBHOOK_VERIFICATION_TOKEN", ""),
                payload=payload,
                notion_client=_notion_client(),
                sync_repository=sync_repo,
                notion_repository=notion_repo,
            )
            return https_fn.Response(json.dumps(result), status=200, mimetype="application/json")
        except PermissionError as exc:
            return https_fn.Response(json.dumps({"error": str(exc)}), status=401, mimetype="application/json")
        except Exception as exc:
            return https_fn.Response(json.dumps({"error": str(exc)}), status=500, mimetype="application/json")

    @scheduler_fn.on_schedule(schedule="every 60 minutes", secrets=["NOTION_TOKEN"])
    def reconcile_notion_sync(event: Any) -> None:
        del event
        sync_repo, notion_repo = _repositories()
        reconcile_notion(
            notion_client=_notion_client(),
            sync_repository=sync_repo,
            notion_repository=notion_repo,
        )

    @scheduler_fn.on_schedule(schedule="every 1 minutes", secrets=["NOTION_TOKEN"])
    def drain_notion_sync_queue(event: Any) -> None:
        """Process a bounded batch so cloud deployment is self-sufficient."""
        del event
        from job_application_agents.plugins.notion import NotionPlugin
        from job_application_agents.plugins.notion.worker import NotionWorker

        sync_repo, notion_repo = _repositories()
        notion_client = _notion_client()
        worker = NotionWorker(
            repository=notion_repo,
            sync_repository=sync_repo,
            plugin=NotionPlugin(token=notion_client.token, client=notion_client),
            worker_id="firebase-notion-scheduler",
        )
        for _ in range(20):
            job = notion_repo.claim(worker.worker_id)
            if not job:
                break
            worker.process(job)

except ImportError:
    # The SDK is installed by Firebase's deployment environment. Keeping this
    # fallback allows imports and pure handler tests in the project venv.
    on_application_written = None
    notion_webhook = None
    reconcile_notion_sync = None
    drain_notion_sync_queue = None
