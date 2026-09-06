from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock

from job_application_agents.sync.models import ApplicationSyncSnapshot
from job_application_agents.sync.notion_webhook import (
    extract_page_values,
    process_notion_page,
    should_enqueue_firestore_change,
    verify_signature,
)
from functions.handlers import handle_firestore_application_write, handle_notion_webhook


def page(**overrides):
    properties = {
        "Application ID": {"type": "rich_text", "rich_text": [{"plain_text": "app-1"}]},
        "Status": {"type": "select", "select": {"name": "INTERVIEW"}},
        "Applied At": {"type": "date", "date": {"start": "2026-08-25"}},
        "Next Action At": {"type": "date", "date": {"start": "2026-09-01"}},
        "Notes": {"type": "rich_text", "rich_text": [{"plain_text": "Call recruiter"}]},
        "Company": {"type": "rich_text", "rich_text": [{"plain_text": "Ignored edit"}]},
    }
    result = {
        "id": "page-1",
        "last_edited_time": "2026-08-31T10:00:00.000Z",
        "parent": {"database_id": "db-1"},
        "properties": properties,
    }
    result.update(overrides)
    return result


class NotionWebhookUnitTests(unittest.TestCase):
    def test_signature_uses_raw_body(self) -> None:
        body = b'{"id":"event-1"}'
        token = "verification-secret"
        signature = "sha256=" + hmac.new(token.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(body, signature, token))
        self.assertFalse(verify_signature(body + b" ", signature, token))

    def test_extract_page_values_only_maps_allowed_fields(self) -> None:
        values = extract_page_values(page())
        self.assertEqual(values["application_id"], "app-1")
        self.assertEqual(values["status"], "INTERVIEW")
        self.assertEqual(values["notes"], "Call recruiter")
        self.assertNotIn("company", values)

    def test_firestore_change_ignores_projection_metadata(self) -> None:
        before = {"status": "TO_APPLY", "sync": {"last_source": "firestore"}, "notion_page_id": "p1"}
        after = {"status": "TO_APPLY", "sync": {"last_source": "notion"}, "notion_page_id": "p2"}
        self.assertFalse(should_enqueue_firestore_change(before, after))
        self.assertTrue(should_enqueue_firestore_change(before, {"status": "APPLIED"}))

    def test_firestore_write_marks_source_and_queues_projection(self) -> None:
        sync_repo = MagicMock()
        notion_repo = MagicMock()
        notion_repo.enqueue_application.return_value = MagicMock(id="job-1")
        result = handle_firestore_application_write(
            user_id="user-1",
            application_id="app-1",
            before={"status": "TO_APPLY"},
            after={"status": "APPLIED", "current_version": "v002"},
            sync_repository=sync_repo,
            notion_repository=notion_repo,
        )
        self.assertEqual(result["status"], "QUEUED")
        self.assertEqual(result["job_id"], "job-1")
        self.assertEqual(sync_repo.update_application_fields.call_args.args[2]["sync"]["last_source"], "firestore")
        notion_repo.enqueue_application.assert_called_once_with(
            user_id="user-1", application_id="app-1", current_version="v002", reason="firestore_change"
        )

    def test_notion_verification_is_persisted(self) -> None:
        sync_repo = MagicMock()
        notion_repo = MagicMock()
        token = "notion-verification-token"

        result = handle_notion_webhook(
            raw_body=json.dumps({"verification_token": token}).encode(),
            signature=None,
            verification_token=None,
            payload={"verification_token": token},
            notion_client=None,
            sync_repository=sync_repo,
            notion_repository=notion_repo,
        )

        self.assertEqual(result, {"status": "VERIFICATION", "verification_token": token})
        sync_repo.save_notion_webhook_verification_token.assert_called_once_with(token)

    def test_notion_webhook_uses_persisted_token_when_secret_is_absent(self) -> None:
        sync_repo = MagicMock()
        sync_repo.get_notion_webhook_verification_token.return_value = "stored-token"
        notion_repo = MagicMock()
        notion_repo.webhook_event_exists.return_value = False
        notion_repo.find_application_for_notion_page.return_value = None
        payload = {"id": "event-1", "type": "page.properties_updated", "entity": {"id": "page-1"}}
        raw_body = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(b"stored-token", raw_body, hashlib.sha256).hexdigest()

        result = handle_notion_webhook(
            raw_body=raw_body,
            signature=signature,
            verification_token=None,
            payload=payload,
            notion_client=MagicMock(),
            sync_repository=sync_repo,
            notion_repository=notion_repo,
        )

        self.assertEqual(result["status"], "IGNORED")
        sync_repo.get_notion_webhook_verification_token.assert_called_once_with()

    def test_allowed_notion_edits_update_firestore_and_requeue_projection(self) -> None:
        sync_repo = MagicMock()
        notion_repo = MagicMock()
        sync_repo.fetch_application.return_value = ApplicationSyncSnapshot(
            application_id="app-1", company="Acme", company_slug="acme", role="Engineer",
            role_slug="engineer", job_id_or_hash="1", status="TO_APPLY", current_version="v001",
        )
        notion_repo.find_application_for_notion_page.return_value = ("user-1", "app-1")
        enqueue = MagicMock()
        result = process_notion_page(
            page=page(),
            event={"id": "event-1", "timestamp": "2026-08-31T10:01:00Z"},
            sync_repository=sync_repo,
            notion_repository=notion_repo,
            enqueue=enqueue,
        )
        self.assertEqual(result["status"], "UPDATED")
        updates = sync_repo.update_application_fields.call_args.args[2]
        self.assertEqual(updates["status"], "INTERVIEW")
        self.assertEqual(updates["notes"], "Call recruiter")
        self.assertNotIn("company", updates)
        enqueue.assert_called_once_with("user-1", "app-1", "notion_allowed_fields")

    def test_firestore_wins_when_newer(self) -> None:
        sync_repo = MagicMock()
        notion_repo = MagicMock()
        sync_repo.fetch_application.return_value = ApplicationSyncSnapshot(
            application_id="app-1", company="Acme", company_slug="acme", role="Engineer",
            role_slug="engineer", job_id_or_hash="1", status="APPLIED", current_version="v001",
        )
        notion_repo.find_application_for_notion_page.return_value = ("user-1", "app-1")
        app_data = sync_repo.fetch_application.return_value.to_dict()
        app_data["sync"] = {"firestore_changed_at": "2026-08-31T11:00:00Z"}
        sync_repo.fetch_application.return_value = MagicMock(to_dict=lambda: app_data)
        enqueue = MagicMock()
        result = process_notion_page(
            page=page(),
            event={"id": "event-2", "timestamp": "2026-08-31T10:01:00Z"},
            sync_repository=sync_repo,
            notion_repository=notion_repo,
            enqueue=enqueue,
        )
        self.assertEqual(result["status"], "CONFLICT")
        enqueue.assert_called_once_with("user-1", "app-1", "conflict_repair")


if __name__ == "__main__":
    unittest.main()
