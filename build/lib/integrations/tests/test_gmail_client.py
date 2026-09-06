"""Unit tests for GmailClient and MIME decoding."""

from __future__ import annotations

import email
from email.message import EmailMessage as PyEmailMessage
import unittest
from unittest.mock import MagicMock, patch

from integrations.email.gmail_client import (
    GmailClient,
    _decode_mime_header,
    _extract_email_address,
)
from integrations.models import EmailAccountConfig


class TestGmailClient(unittest.TestCase):

    def test_extract_email_address(self) -> None:
        self.assertEqual(
            _extract_email_address("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"),
            "jobalerts-noreply@linkedin.com",
        )
        self.assertEqual(
            _extract_email_address("alert@indeed.com"),
            "alert@indeed.com",
        )
        self.assertEqual(
            _extract_email_address('"Alex Example" <alex@example.com>'),
            "alex@example.com",
        )

    def test_decode_mime_header(self) -> None:
        # Standard ASCII
        self.assertEqual(_decode_mime_header("Simple Subject"), "Simple Subject")
        # Empty
        self.assertEqual(_decode_mime_header(None), "")
        # UTF-8 Q-encoded
        self.assertEqual(
            _decode_mime_header("=?UTF-8?Q?10_nouvelles_offres_d=27emploi?="),
            "10 nouvelles offres d'emploi",
        )

    def test_parse_mime_message(self) -> None:
        client = GmailClient(EmailAccountConfig())

        # Construct standard MIME multipart email
        msg = PyEmailMessage()
        msg["Subject"] = "Top 5 Job Matches for AI Platform Engineer"
        msg["From"] = "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"
        msg["To"] = "candidate@example.com"
        msg["Date"] = "Wed, 26 Aug 2026 08:30:00 +0200"
        msg["Message-ID"] = "<unique-12345@linkedin.com>"

        msg.set_content("Plain text body with job link https://www.linkedin.com/jobs/view/123")
        msg.add_alternative("<html><body><p>HTML job link <a href='https://www.linkedin.com/jobs/view/123'>AI Engineer</a></p></body></html>", subtype="html")

        parsed = client._parse_mime_message("55", msg)

        self.assertEqual(parsed.uid, "55")
        self.assertEqual(parsed.sender, "jobalerts-noreply@linkedin.com")
        self.assertEqual(parsed.subject, "Top 5 Job Matches for AI Platform Engineer")
        self.assertIn("HTML job link", parsed.body_html)
        self.assertIn("Plain text body", parsed.body_plain)
        self.assertIsNotNone(parsed.date_timestamp)

    def test_test_connection_missing_credentials(self) -> None:
        client = GmailClient(EmailAccountConfig(email_address="", app_password=""))
        res = client.test_connection()
        self.assertEqual(res["status"], "CONFIG_ERROR")
        self.assertFalse(res["connected"])

    @patch("imaplib.IMAP4_SSL")
    def test_test_connection_success(self, mock_imap_cls: MagicMock) -> None:
        mock_imap_instance = MagicMock()
        mock_imap_cls.return_value = mock_imap_instance
        mock_imap_instance.login.return_value = ("OK", [b"Logged in"])
        mock_imap_instance.select.return_value = ("OK", [b"42"])
        mock_imap_instance.search.return_value = ("OK", [b"1 2 3"])

        client = GmailClient(
            EmailAccountConfig(
                email_address="user@gmail.com",
                app_password="secretpassword123",
                target_senders=["jobalerts-noreply@linkedin.com"],
            )
        )

        res = client.test_connection()
        self.assertEqual(res["status"], "READY")
        self.assertTrue(res["connected"])
        self.assertEqual(res["total_messages"], 42)


if __name__ == "__main__":
    unittest.main()
