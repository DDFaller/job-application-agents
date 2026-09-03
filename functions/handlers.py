"""Runtime-neutral handlers used by Firebase Functions and tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from job_application_agents.plugins.notion.client import NotionClient
from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
from job_application_agents.sync.firestore import FirestoreUserSyncRepository
from job_application_agents.sync.notion_webhook import (
    SUPPORTED_EVENTS,
    extract_page_values,
    process_notion_page,
    should_enqueue_firestore_change,
    verify_signature,
    verification_response,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def handle_firestore_application_write(
    *,
    user_id: str,
    application_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    sync_repository: FirestoreUserSyncRepository,
    notion_repository: FirestoreNotionJobRepository,
) -> dict[str, Any]:
    """Mark a Firestore change and enqueue one current-state projection."""
    if after is None:
        page_id = (before or {}).get("notion_page_id")
        if not page_id:
            return {"status": "NOOP", "reason": "no_notion_page"}
        job = notion_repository.enqueue(
            user_id=user_id,
            application_id=application_id,
            action="DELETE",
            payload={"application_id": application_id, "notion_page_id": page_id, "reason": "firestore_delete"},
            idempotency_key=f"delete:{user_id}:{application_id}",
        )
        return {"status": "QUEUED", "action": "DELETE", "job_id": job.id}

    if not should_enqueue_firestore_change(before, after):
        return {"status": "NOOP", "reason": "metadata_only"}

    current_sync = dict(after.get("sync") or {})
    sync_repository.update_application_fields(user_id, application_id, {
        "sync": {
            **current_sync,
            "last_source": "firestore",
            "firestore_changed_at": _now_iso(),
            "conflict": None,
        }
    })
    job = notion_repository.enqueue_application(
        user_id=user_id,
        application_id=application_id,
        current_version=str(after.get("current_version", "v001")),
        reason="firestore_change",
    )
    return {"status": "QUEUED", "action": "CREATE_OR_UPDATE", "job_id": job.id}


def handle_notion_webhook(
    *,
    raw_body: bytes,
    signature: str | None,
    verification_token: str | None,
    payload: dict[str, Any],
    notion_client: NotionClient | None,
    sync_repository: FirestoreUserSyncRepository,
    notion_repository: FirestoreNotionJobRepository,
) -> dict[str, Any]:
    """Validate and process one Notion webhook delivery."""
    verification = verification_response(payload)
    if verification:
        # Verification requests are intentionally not signature-checked; the
        # token is supplied by Notion to activate the subscription. Persist it
        # server-side because it does not exist until this request arrives.
        sync_repository.save_notion_webhook_verification_token(
            str(verification["verification_token"])
        )
        return {"status": "VERIFICATION", **verification}

    active_token = verification_token or sync_repository.get_notion_webhook_verification_token()
    if not verify_signature(raw_body, signature, active_token or ""):
        raise PermissionError("invalid Notion webhook signature")

    event_id = str(payload.get("id") or "")
    event_type = str(payload.get("type") or "")
    page_id = str((payload.get("entity") or {}).get("id") or "")
    if not event_id or not page_id:
        return {"status": "IGNORED", "reason": "missing_event_or_page_id"}
    if event_type not in SUPPORTED_EVENTS:
        return {"status": "IGNORED", "reason": "unsupported_event", "type": event_type}
    if notion_repository.webhook_event_exists(event_id):
        return {"status": "DUPLICATE", "event_id": event_id}

    if event_type == "page.deleted":
        match = notion_repository.find_application_for_notion_page(page_id)
        if not match:
            return {"status": "IGNORED", "reason": "application_not_found", "page_id": page_id}
        user_id, application_id = match
        sync_repository.update_application_fields(user_id, application_id, {
            "notion_page_id": None,
            "notion_page_url": None,
            "sync": {"last_source": "notion", "last_event_id": event_id, "conflict": {"reason": "page_deleted"}},
        })
        job = notion_repository.enqueue_application(user_id, application_id, reason="notion_page_deleted")
        result = {"status": "QUEUED", "reason": "page_deleted", "job_id": job.id}
        notion_repository.record_webhook_event(event_id, {"type": event_type, "page_id": page_id})
        return result

    if notion_client is None:
        raise RuntimeError("NOTION_TOKEN is required for non-verification webhook events")
    page = notion_client.retrieve_page(page_id)
    result = process_notion_page(
        page=page,
        event=payload,
        sync_repository=sync_repository,
        notion_repository=notion_repository,
        enqueue=lambda user_id, application_id, reason: notion_repository.enqueue_application(
            user_id, application_id, reason=reason
        ),
    )
    notion_repository.record_webhook_event(event_id, {"type": event_type, "page_id": page_id})
    return result


def reconcile_notion(
    *,
    notion_client: NotionClient,
    sync_repository: FirestoreUserSyncRepository,
    notion_repository: FirestoreNotionJobRepository,
) -> dict[str, int]:
    """Repair missing/stale Notion projections for every configured user."""
    queued = 0
    missing = 0
    checked = 0
    for user_doc in sync_repository.client.collection("users").stream():
        user_id = user_doc.id
        user_data = user_doc.to_dict() or {}
        config = user_data.get("notion_config") or {}
        database_id = config.get("database_id")
        if not config.get("enabled", True) or not database_id:
            continue
        pages = notion_client.query_database(database_id)
        page_map: dict[str, dict[str, Any]] = {}
        page_id_map: dict[str, dict[str, Any]] = {}
        for page in pages:
            if page.get("id"):
                page_id_map[str(page["id"])] = page
            values = extract_page_values(page)
            app_id = values.get("application_id")
            if app_id:
                page_map[str(app_id)] = page

        for app in sync_repository.list_applications(user_id, include_versions=False):
            checked += 1
            app_data = app.to_dict()
            page = page_map.get(app.application_id) or page_id_map.get(str(app.notion_page_id or ""))
            if not page:
                if app.notion_page_id:
                    missing += 1
                    sync_repository.update_application_fields(user_id, app.application_id, {
                        "notion_page_id": None,
                        "notion_page_url": None,
                    })
                notion_repository.enqueue_application(user_id, app.application_id, app.current_version, "reconcile_missing")
                queued += 1
                continue

            values = extract_page_values(page)
            drift = any(
                field in values and values[field] != app_data.get(field)
                for field in ("status", "applied_at", "next_action_at", "notes")
            )
            if not values.get("application_id") or drift or app.notion_page_id != page.get("id"):
                notion_repository.enqueue_application(user_id, app.application_id, app.current_version, "reconcile_drift")
                queued += 1
    return {"checked": checked, "queued": queued, "missing": missing}
