"""Tests for provider-first filtering and permanent email processing."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from integrations.base import BaseEmailClient
from integrations.email.processed_ledger import ProcessedEmailLedger
from integrations.email.gmail_client import GmailClient
from integrations.email.provider_filter import (
    ProviderSettingsError,
    filter_message,
    normalize_search_text,
    validate_provider_settings,
)
from integrations.models import EmailAccountConfig, EmailMessage
from integrations.pipeline.orchestrator import JobIngestionPipeline


def message(**kwargs: str) -> EmailMessage:
    values = {
        "uid": "1",
        "message_id": "<one@example.com>",
        "sender": "sender@example.com",
        "recipient": "candidate@example.com",
        "subject": "Subject",
        "date_str": "2026-08-31",
    }
    values.update(kwargs)
    return EmailMessage(**values)


class TestProviderFilter(unittest.TestCase):
    SETTINGS = {"LINKEDIN": ["linkedin", "linkedin job alerts"], "INDEED": ["indeed"]}

    def test_fields_and_multiple_provider_matches(self) -> None:
        result = filter_message(
            message(
                sender="alerts@example.com",
                subject="LinkedIn job-alerts",
                body_plain="A posting from Indeed",
                body_html="<p>LinkedIn jobs</p>",
            ),
            ["LINKEDIN", "INDEED"],
            self.SETTINGS,
        )
        self.assertEqual(result.matched_providers, ["LINKEDIN", "INDEED"])
        self.assertIn("linkedin", result.matched_aliases)
        self.assertIn("indeed", result.matched_aliases)
        self.assertTrue(any(match.field == "subject" for match in result.matches))
        self.assertTrue(any(match.field == "body_plain" for match in result.matches))

    def test_sender_only_and_html_only(self) -> None:
        sender_result = filter_message(message(sender="linkedin-alerts@example.com"), ["LINKEDIN"], self.SETTINGS)
        html_result = filter_message(message(body_html="<div>INDEED jobs</div>"), ["INDEED"], self.SETTINGS)
        self.assertTrue(sender_result.matched)
        self.assertTrue(html_result.matched)
        self.assertTrue(any(match.field == "body_html" for match in html_result.matches))

    def test_normalization_and_disabled_provider(self) -> None:
        self.assertEqual(normalize_search_text("  LinkedIn---Job\tAlerts! "), "linkedin job alerts")
        result = filter_message(message(subject="Indeed"), ["LINKEDIN"], self.SETTINGS)
        self.assertFalse(result.matched)

    def test_malformed_settings_fail(self) -> None:
        with self.assertRaises(ProviderSettingsError):
            validate_provider_settings(["UNKNOWN"], {"UNKNOWN": ["x"]})
        with self.assertRaises(ProviderSettingsError):
            validate_provider_settings(["LINKEDIN"], {"LINKEDIN": ["same", "same"]})
        with self.assertRaises(ProviderSettingsError):
            validate_provider_settings(["LINKEDIN"], {"LINKEDIN": []})


class TestProcessedEmailLedger(unittest.TestCase):
    def test_message_id_and_missing_id_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = ProcessedEmailLedger(Path(tmpdir) / "processed.json", folder="INBOX")
            with_id = message(message_id=" <ONE@example.com> ")
            without_id = message(message_id="", uid="22")
            ledger.record_message(with_id, filter_status="no_match", parse_status="filtered")
            ledger.record_message(without_id, filter_status="no_match", parse_status="filtered")
            self.assertTrue(ledger.contains(message(message_id="<one@example.com>")))
            self.assertTrue(ledger.contains(message(message_id="", uid="22")))
            self.assertEqual(len(ledger.records()), 2)

    def test_atomic_persistence_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "processed.json"
            ledger = ProcessedEmailLedger(path)
            ledger.record_message(message(), filter_status="matched", parse_status="staged")
            self.assertTrue(path.is_file())
            self.assertEqual(ledger.summary()["staged"], 1)
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])


class TestProviderFirstPipeline(unittest.TestCase):
    def test_no_match_is_not_parsed_and_is_skipped_on_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = MagicMock(spec=BaseEmailClient)
            msg = message(sender="newsletter@example.com", subject="Weekly newsletter")
            client.fetch_messages.return_value = [msg]
            pipeline = JobIngestionPipeline(email_client=client, ledger_path=Path(tmpdir) / "ledger.json")
            with patch("integrations.pipeline.orchestrator.parser_registry.parse_message") as parser:
                first = pipeline.run_ingestion()
                second = pipeline.run_ingestion()
                forced = pipeline.run_ingestion(force_recheck=True)
            parser.assert_not_called()
            self.assertEqual(first.total_emails_filtered_out, 1)
            self.assertEqual(second.total_emails_skipped_already_checked, 1)
            self.assertEqual(forced.total_emails_forcibly_rechecked, 1)

    def test_dry_run_does_not_consume_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = MagicMock(spec=BaseEmailClient)
            client.fetch_messages.return_value = [message(subject="not a provider message")]
            path = Path(tmpdir) / "ledger.json"
            pipeline = JobIngestionPipeline(email_client=client, ledger_path=path)
            pipeline.run_ingestion(dry_run=True)
            self.assertFalse(path.exists())

    def test_targeted_recheck_and_retry_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = MagicMock(spec=BaseEmailClient)
            msg = message(subject="LinkedIn alert")
            failed_msg = message(
                uid="2", message_id="<two@example.com>", subject="Indeed alert"
            )
            client.fetch_messages.return_value = [msg, failed_msg]
            path = Path(tmpdir) / "ledger.json"
            ledger = ProcessedEmailLedger(path)
            ledger.record_message(
                msg,
                matched_providers=["LINKEDIN"],
                matched_aliases=["linkedin"],
                filter_status="matched",
                parse_status="failed",
                error="temporary failure",
            )
            ledger.record_message(
                failed_msg,
                matched_providers=["INDEED"],
                matched_aliases=["indeed"],
                filter_status="matched",
                parse_status="failed",
                error="temporary failure",
            )
            pipeline = JobIngestionPipeline(email_client=client, ledger_path=path)
            with patch("integrations.pipeline.orchestrator.parser_registry.parse_message", return_value=[]):
                targeted = pipeline.run_ingestion(recheck_message_id="<one@example.com>")
                retried = pipeline.run_ingestion(retry_failed=True)
            self.assertEqual(targeted.total_emails_forcibly_rechecked, 1)
            self.assertEqual(retried.total_emails_forcibly_rechecked, 1)

    def test_mark_read_follows_durable_ledger_write(self) -> None:
        events: list[str] = []

        class RecordingLedger(ProcessedEmailLedger):
            def record_message(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                record = super().record_message(*args, **kwargs)
                events.append("ledger")
                return record

        with tempfile.TemporaryDirectory() as tmpdir:
            client = MagicMock(spec=BaseEmailClient)
            client.fetch_messages.return_value = [message(subject="ordinary note")]
            client.mark_as_read.side_effect = lambda uids: events.append("read") or True
            ledger = RecordingLedger(Path(tmpdir) / "ledger.json")
            pipeline = JobIngestionPipeline(email_client=client, ledger=ledger)
            pipeline.email_config.mark_as_read = True
            pipeline.run_ingestion()
            self.assertEqual(events, ["ledger", "read"])


class TestGmailSearchBehavior(unittest.TestCase):
    @patch("imaplib.IMAP4_SSL")
    def test_empty_unseen_search_has_no_recent_message_fallback(self, mock_imap_cls: MagicMock) -> None:
        imap = MagicMock()
        mock_imap_cls.return_value = imap
        imap.login.return_value = ("OK", [b"Logged in"])
        imap.select.return_value = ("OK", [b"0"])
        imap.search.return_value = ("OK", [b""])
        client = GmailClient(
            EmailAccountConfig(email_address="user@example.com", app_password="password")
        )
        self.assertEqual(
            client.fetch_messages(sender_filters=["alerts@example.com"], criteria="UNSEEN"), []
        )
        self.assertEqual(imap.search.call_count, 1)


if __name__ == "__main__":
    unittest.main()
