"""Unit tests for the Gmail push handler (phase 4)."""

from __future__ import annotations

import base64
import json
import unittest

from functions.handlers import handle_gmail_push, parse_gmail_push_envelope


def _envelope(history_id="777", email="candidate@example.com", delivery="pub-1"):
    data = base64.b64encode(
        json.dumps({"historyId": history_id, "emailAddress": email}).encode()
    ).decode()
    return {"message": {"data": data, "messageId": delivery}}


class _PushClient:
    def __init__(self, ids):
        self.ids = ids
        self.seen = []

    def list_history_ids(self, start_history_id):
        self.seen.append(start_history_id)
        return list(self.ids)


class _IngestResult:
    total_jobs_staged = 2
    total_emails_skipped_already_checked = 1


class GmailPushTests(unittest.TestCase):
    def test_parse_envelope(self) -> None:
        parsed = parse_gmail_push_envelope(_envelope())
        self.assertEqual(parsed["history_id"], "777")
        self.assertEqual(parsed["email_address"], "candidate@example.com")
        self.assertEqual(parsed["delivery_id"], "pub-1")

    def test_parse_rejects_malformed(self) -> None:
        with self.assertRaises(ValueError):
            parse_gmail_push_envelope({"message": {"data": "!!!"}})
        with self.assertRaises(ValueError):
            parse_gmail_push_envelope({"message": {}})

    def test_wrong_token_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            handle_gmail_push(
                envelope=_envelope(),
                verification_token="wrong",
                expected_token="right",
                gmail_client=_PushClient(["a"]),
                run_ingestion=lambda ids: _IngestResult(),
            )

    def test_ingests_only_notified_ids(self) -> None:
        client = _PushClient(["gmail-1"])
        ingested = []
        result = handle_gmail_push(
            envelope=_envelope(),
            verification_token="tok",
            expected_token="tok",
            gmail_client=client,
            run_ingestion=lambda ids: ingested.append(ids) or _IngestResult(),
        )
        self.assertEqual(result["status"], "INGESTED")
        self.assertEqual(result["gmail_ids"], ["gmail-1"])
        self.assertEqual(ingested, [["gmail-1"]])
        self.assertEqual(client.seen, ["777"])
        self.assertEqual(result["total_jobs_staged"], 2)

    def test_no_new_messages_is_noop(self) -> None:
        calls = []
        result = handle_gmail_push(
            envelope=_envelope(),
            verification_token="tok",
            expected_token="tok",
            gmail_client=_PushClient([]),
            run_ingestion=lambda ids: calls.append(ids),
        )
        self.assertEqual(result["status"], "NOOP")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
