"""Pure application synchronization logic for Notion webhook events.

The HTTP/Firebase adapter lives in ``functions/main.py``. Keeping the mapping
and conflict rules here makes them testable without network or Firebase.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from typing import Any, Callable

from job_application_agents.job_search.outcomes import KNOWN_STATUSES, normalize_status, validate_transition


ALLOWED_NOTION_FIELDS = {
    "Status": "status",
    "Applied At": "applied_at",
    "Next Action At": "next_action_at",
    "Notes": "notes",
}
SYNC_ONLY_FIELDS = {
    "sync",
    "notion_page_id",
    "notion_page_url",
    "documents",
    "updated_at",
}
SUPPORTED_EVENTS = {"page.created", "page.properties_updated", "page.content_updated", "page.deleted"}


def verify_signature(raw_body: bytes, signature: str | None, verification_token: str) -> bool:
    if not signature or not verification_token:
        return False
    digest = hmac.new(verification_token.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)


def _property_text(value: dict[str, Any]) -> str:
    fragments = value.get("title") or value.get("rich_text") or []
    return "".join(
        str(item.get("plain_text") or item.get("text", {}).get("content") or "")
        for item in fragments
    ).strip()


def read_notion_property(value: dict[str, Any] | None) -> Any:
    """Convert a Notion property response into a scalar application value."""
    if not value:
        return None
    property_type = value.get("type")
    if property_type in {"title", "rich_text"}:
        return _property_text(value)
    if property_type in {"select", "status"}:
        return (value.get(property_type) or {}).get("name")
    if property_type == "date":
        return (value.get("date") or {}).get("start")
    if property_type == "url":
        return value.get("url")
    if property_type == "number":
        return value.get("number")
    return None


def extract_page_values(page: dict[str, Any]) -> dict[str, Any]:
    properties = page.get("properties") or {}
    values: dict[str, Any] = {
        "page_id": page.get("id"),
        "last_edited_time": page.get("last_edited_time"),
        "database_id": (page.get("parent") or {}).get("database_id"),
    }
    for notion_name, firestore_name in ALLOWED_NOTION_FIELDS.items():
        if notion_name in properties:
            values[firestore_name] = read_notion_property(properties[notion_name])

    app_id = read_notion_property(properties.get("Application ID"))
    if app_id:
        values["application_id"] = app_id
    return values


def application_id_from_page(page: dict[str, Any]) -> str | None:
    values = extract_page_values(page)
    if values.get("application_id"):
        return str(values["application_id"])
    # Compatibility with cards created before the stable Application ID column.
    source_id = read_notion_property((page.get("properties") or {}).get("Source Job ID"))
    return str(source_id) if source_id else None


def firestore_projection(data: dict[str, Any]) -> dict[str, Any]:
    """Return fields whose changes should cause a Notion projection."""
    return {key: value for key, value in data.items() if key not in SYNC_ONLY_FIELDS}


def should_enqueue_firestore_change(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    if not after:
        return False
    return firestore_projection(before or {}) != firestore_projection(after)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def process_notion_page(
    *,
    page: dict[str, Any],
    event: dict[str, Any],
    sync_repository: Any,
    notion_repository: Any,
    enqueue: Callable[[str, str, str], Any],
) -> dict[str, Any]:
    """Apply an allowed Notion edit or restore Firestore's canonical values."""
    values = extract_page_values(page)
    page_id = str(values.get("page_id") or "")
    application_id = application_id_from_page(page)
    match = notion_repository.find_application_for_notion_page(page_id, application_id)
    if not match:
        return {"status": "IGNORED", "reason": "application_not_found", "page_id": page_id}

    user_id, resolved_app_id = match
    app = sync_repository.fetch_application(user_id, resolved_app_id, include_versions=False)
    if not app:
        return {"status": "IGNORED", "reason": "application_not_found", "page_id": page_id}
    current = app.to_dict()
    event_time = _parse_time(event.get("timestamp")) or datetime.now(timezone.utc)
    sync_meta = dict(current.get("sync") or {})
    firestore_time = _parse_time(sync_meta.get("firestore_changed_at"))

    # Firestore changed after this Notion event was generated: preserve the
    # canonical value and request a projection repair.
    if firestore_time and firestore_time > event_time:
        conflict = {
            "source": "notion",
            "event_id": event.get("id"),
            "event_time": event_time.isoformat(),
            "reason": "firestore_newer",
        }
        sync_repository.update_application_fields(user_id, resolved_app_id, {
            "sync": {**sync_meta, "last_source": "notion", "last_event_id": event.get("id"), "conflict": conflict},
        })
        enqueue(user_id, resolved_app_id, "conflict_repair")
        return {"status": "CONFLICT", "reason": "firestore_newer", "application_id": resolved_app_id}

    updates: dict[str, Any] = {}
    for field in ("status", "applied_at", "next_action_at", "notes"):
        if field not in values:
            continue
        value = values[field]
        if field == "status":
            value = normalize_status(value)
            if value not in KNOWN_STATUSES:
                return {"status": "REJECTED", "reason": "unknown_status", "value": value}
            valid, reason = validate_transition(current.get("status", "TO_APPLY"), value)
            if not valid:
                enqueue(user_id, resolved_app_id, "invalid_notion_transition")
                return {"status": "REJECTED", "reason": reason, "application_id": resolved_app_id}
        if value != current.get(field):
            updates[field] = value

    new_sync = {
        **sync_meta,
        "last_source": "notion",
        "last_event_id": event.get("id"),
        "notion_last_edited_time": values.get("last_edited_time") or event.get("timestamp"),
        "last_success_at": datetime.now(timezone.utc).isoformat(),
        "conflict": None,
    }
    if updates:
        updates["sync"] = new_sync
        sync_repository.update_application_fields(user_id, resolved_app_id, updates)
        # Firestore remains canonical; this makes the projection explicit and
        # also repairs cards whose event arrived with a stale page snapshot.
        enqueue(user_id, resolved_app_id, "notion_allowed_fields")
        return {"status": "UPDATED", "application_id": resolved_app_id, "fields": sorted(updates)}

    sync_repository.update_application_fields(user_id, resolved_app_id, {"sync": new_sync})
    return {"status": "NOOP", "application_id": resolved_app_id}


def verification_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    token = payload.get("verification_token")
    return {"verification_token": token} if token else None
