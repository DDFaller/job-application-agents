"""Unit tests for the read-only Gmail API transport."""

from __future__ import annotations

import base64
from email.message import EmailMessage as PyEmailMessage
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.email.factory import FallbackEmailClient, create_email_client
from integrations.email.gmail_api_client import (
    GMAIL_READONLY_SCOPE,
    GmailApiClient,
)
from integrations.config import IntegrationsConfig
from integrations.models import EmailAccountConfig, EmailMessage


class _Request:
    def __init__(self, value: dict) -> None:
        self.value = value

    def execute(self) -> dict:
        return self.value


class _MessagesResource:
    def __init__(self, raw_messages: dict[str, str]) -> None:
        self.raw_messages = raw_messages
        self.list_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.modify_calls: list[dict] = []

    def list(self, **kwargs: object) -> _Request:
        self.list_calls.append(kwargs)
        return _Request({"messages": [{"id": message_id} for message_id in self.raw_messages]})

    def get(self, **kwargs: object) -> _Request:
        self.get_calls.append(kwargs)
        message_id = str(kwargs["id"])
        return _Request({"raw": self.raw_messages[message_id]})

    def modify(self, **kwargs: object) -> _Request:
        self.modify_calls.append(kwargs)
        return _Request({})


class _UsersResource:
    def __init__(self, messages: _MessagesResource) -> None:
        self._messages = messages

    def messages(self) -> _MessagesResource:
        return self._messages

    def getProfile(self, **kwargs: object) -> _Request:
        return _Request({"emailAddress": "candidate@example.com"})


class _FakeGmailService:
    def __init__(self, raw_messages: dict[str, str]) -> None:
        self.messages = _MessagesResource(raw_messages)
        self._users = _UsersResource(self.messages)

    def users(self) -> _UsersResource:
        return self._users


def _raw_linkedin_message() -> str:
    message = PyEmailMessage()
    message["Subject"] = "Jobs you may be interested in"
    message["From"] = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
    message["To"] = "candidate@example.com"
    message["Date"] = "Tue, 1 Sep 2026 09:00:00 +0200"
    message["Message-ID"] = "<gmail-api-test@example.com>"
    message.set_content(
        "AI Platform Engineer at Example Corp\n"
        "https://www.linkedin.com/jobs/view/123456789\n"
    )
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")


class TestGmailApiClient(unittest.TestCase):
    def test_fetch_decodes_raw_mime_and_uses_read_only_gmail_queries(self) -> None:
        service = _FakeGmailService({"message-1": _raw_linkedin_message()})
        client = GmailApiClient(
            EmailAccountConfig(folder="INBOX", auth_mode="gmail_api"), service=service
        )

        messages = client.fetch_messages(criteria="ALL", limit=3, search_all=True)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].uid, "message-1")
        self.assertEqual(messages[0].sender, "jobalerts-noreply@linkedin.com")
        self.assertIn("linkedin.com/jobs/view/123456789", messages[0].body_plain)
        self.assertEqual(service.messages.get_calls[0]["format"], "raw")
        self.assertEqual(service.messages.modify_calls, [])
        self.assertEqual(service.messages.list_calls[0]["q"], "in:anywhere in:inbox")

    def test_sender_filters_narrow_api_search_without_becoming_provider_filter(self) -> None:
        service = _FakeGmailService({"message-1": _raw_linkedin_message()})
        client = GmailApiClient(EmailAccountConfig(folder="INBOX"), service=service)

        client.fetch_messages(
            sender_filters=["jobalerts-noreply@linkedin.com"],
            criteria="UNSEEN",
            limit=2,
            search_all=False,
        )

        self.assertEqual(
            service.messages.list_calls[0]["q"],
            "is:unread in:inbox from:jobalerts-noreply@linkedin.com",
        )

    def test_mark_as_read_never_mutates_mailbox(self) -> None:
        service = _FakeGmailService({})
        client = GmailApiClient(EmailAccountConfig(), service=service)

        self.assertFalse(client.mark_as_read(["message-1"]))
        self.assertEqual(service.messages.modify_calls, [])

    def test_query_criteria_and_since_window(self) -> None:
        self.assertEqual(
            GmailApiClient._query_for_criteria("UNSEEN", "INBOX", 7),
            "is:unread in:inbox newer_than:7d",
        )
        self.assertEqual(
            GmailApiClient._query_for_criteria("ALL", "STARRED", None),
            "in:anywhere label:STARRED",
        )
        with self.assertRaises(ValueError):
            GmailApiClient._query_for_criteria("ALL", "INBOX", -1)

    def test_factory_selects_gmail_api_transport(self) -> None:
        client = create_email_client(EmailAccountConfig(auth_mode="gmail_api"))
        self.assertIsInstance(client, FallbackEmailClient)
        self.assertIsInstance(client.primary, GmailApiClient)

    def test_factory_fallback_uses_imap_when_api_is_unavailable(self) -> None:
        primary = GmailApiClient(EmailAccountConfig())
        fallback = _FakeImapClient()
        client = FallbackEmailClient(primary, fallback)  # type: ignore[arg-type]

        with patch.object(primary, "connect", return_value=False), patch.object(
            fallback, "connect", return_value=True
        ):
            self.assertTrue(client.connect())
        self.assertIs(client._active, fallback)

    def test_config_loader_accepts_oauth_environment_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {
                    "GMAIL_AUTH_MODE": "gmail_api",
                    "GMAIL_CLIENT_SECRETS_PATH": "~/oauth/client.json",
                    "GMAIL_OAUTH_TOKEN_PATH": "~/oauth/token.json",
                },
            ):
                config = IntegrationsConfig(Path(directory) / "missing.json").get_email_config()

        self.assertEqual(config.auth_mode, "gmail_api")
        self.assertEqual(config.client_secrets_path, "~/oauth/client.json")
        self.assertEqual(config.oauth_token_path, "~/oauth/token.json")
    def test_save_credentials_uses_private_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "nested" / "gmail-token.json"
            client = GmailApiClient(
                EmailAccountConfig(oauth_token_path=str(token_path)), service=None
            )

            class Credentials:
                def to_json(self) -> str:
                    return json.dumps({"refresh_token": "redacted-test-token"})

            client._save_credentials(Credentials())

            self.assertEqual(json.loads(token_path.read_text()), {"refresh_token": "redacted-test-token"})
            self.assertEqual(token_path.stat().st_mode & 0o777, 0o600)

    def test_test_connection_reports_ready_and_scope(self) -> None:
        client = GmailApiClient(EmailAccountConfig(), service=_FakeGmailService({}))

        result = client.test_connection()

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["scope"], GMAIL_READONLY_SCOPE)
        self.assertEqual(result["email_address"], "candidate@example.com")

    def test_connect_does_not_start_browser_authorization(self) -> None:
        client = GmailApiClient(EmailAccountConfig())
        with patch.object(client, "_credentials", side_effect=RuntimeError("no cached token")) as credentials:
            self.assertFalse(client.connect())
        credentials.assert_called_once_with(interactive=False)


class _FakeImapClient:
    is_connected = False

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def test_connection(self) -> dict[str, object]:
        return {"status": "READY", "connected": True}

    def fetch_messages(self, **kwargs: object) -> list[EmailMessage]:
        return []

    def mark_as_read(self, uids: list[str]) -> bool:
        return True


if __name__ == "__main__":
    unittest.main()
