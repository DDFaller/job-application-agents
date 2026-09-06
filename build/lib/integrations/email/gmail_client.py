"""Gmail email client supporting IMAP4_SSL and query filtering."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import email
from email.header import decode_header
import email.utils
import imaplib
import logging
import re
import ssl
from typing import Any

from ..base import BaseEmailClient
from ..models import EmailAccountConfig, EmailMessage

logger = logging.getLogger(__name__)


def _decode_mime_header(header_value: str | None) -> str:
    """Safely decode MIME encoded header fields."""
    if not header_value:
        return ""
    decoded_parts: list[str] = []
    try:
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                enc = encoding or "utf-8"
                try:
                    decoded_parts.append(part.decode(enc, errors="replace"))
                except LookupError:
                    decoded_parts.append(part.decode("utf-8", errors="replace"))
            else:
                decoded_parts.append(str(part))
        return "".join(decoded_parts)
    except Exception:
        return str(header_value)


def _extract_email_address(from_header: str) -> str:
    """Extract bare email address from 'Name <email@domain.com>' format."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1).strip().lower()
    match_bare = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", from_header)
    if match_bare:
        return match_bare.group(0).strip().lower()
    return from_header.strip().lower()


class GmailClient(BaseEmailClient):
    """Client for connecting to Gmail via IMAP4_SSL and searching for job alerts."""

    def __init__(self, config: EmailAccountConfig) -> None:
        self.config = config
        self._imap: imaplib.IMAP4_SSL | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._imap is not None

    def connect(self) -> bool:
        """Establish SSL connection to Gmail IMAP server and authenticate."""
        if not self.config.email_address or not self.config.app_password:
            logger.warning("Gmail credentials missing (email_address or app_password).")
            return False

        try:
            ssl_context = ssl.create_default_context()
            self._imap = imaplib.IMAP4_SSL(
                host=self.config.imap_server,
                port=self.config.imap_port,
                ssl_context=ssl_context,
            )

            # Authenticate
            self._imap.login(self.config.email_address, self.config.app_password)
            self._connected = True
            logger.info("Successfully connected to Gmail IMAP (%s)", self.config.email_address)
            return True
        except Exception as exc:
            self._connected = False
            self._imap = None
            logger.error("Failed to connect to Gmail: %s", exc)
            return False

    def disconnect(self) -> None:
        """Gracefully logout and close the IMAP connection."""
        if self._imap:
            try:
                self._imap.close()
            except Exception:
                pass
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None
        self._connected = False

    def test_connection(self) -> dict[str, Any]:
        """Verify Gmail connection and report status."""
        if not self.config.email_address or not self.config.app_password:
            return {
                "status": "CONFIG_ERROR",
                "connected": False,
                "message": "Missing Gmail credentials (GMAIL_USER / GMAIL_APP_PASSWORD).",
                "email_address": self.config.email_address,
                "server": f"{self.config.imap_server}:{self.config.imap_port}",
            }

        try:
            ok = self.connect()
            if not ok or not self._imap:
                return {
                    "status": "AUTH_FAILED",
                    "connected": False,
                    "message": "Authentication failed. Ensure an App Password is used if 2FA is active.",
                    "email_address": self.config.email_address,
                    "server": f"{self.config.imap_server}:{self.config.imap_port}",
                }

            # Select target folder
            status, count_data = self._imap.select(self.config.folder, readonly=True)
            if status != "OK":
                return {
                    "status": "FOLDER_ERROR",
                    "connected": True,
                    "message": f"Could not select folder '{self.config.folder}'",
                }

            total_msgs = int(count_data[0].decode()) if count_data and count_data[0] else 0

            # Test search query for target senders
            found_alerts = 0
            for sender in self.config.target_senders[:3]:
                res, data = self._imap.search(None, f'(FROM "{sender}")')
                if res == "OK" and data and data[0]:
                    found_alerts += len(data[0].split())

            return {
                "status": "READY",
                "connected": True,
                "email_address": self.config.email_address,
                "folder": self.config.folder,
                "total_messages": total_msgs,
                "sample_target_sender_messages": found_alerts,
                "configured_target_senders": self.config.target_senders,
                "message": "Gmail connection verified successfully.",
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "connected": False,
                "message": f"Connection error: {exc}",
            }
        finally:
            self.disconnect()

    def fetch_messages(
        self,
        sender_filters: list[str] | None = None,
        criteria: str = "UNSEEN",
        limit: int = 25,
        since_days: int | None = None,
        search_all: bool = False,
    ) -> list[EmailMessage]:
        """Fetch matching email messages from the configured mailbox."""
        if not self.is_connected:
            if not self.connect():
                logger.error("Cannot fetch messages: not connected to Gmail.")
                return []

        assert self._imap is not None
        target_senders = sender_filters or self.config.target_senders
        messages: list[EmailMessage] = []

        try:
            status, _ = self._imap.select(self.config.folder, readonly=not self.config.mark_as_read)
            if status != "OK":
                logger.error("Failed to select folder %s", self.config.folder)
                return []

            uids_to_fetch: list[bytes] = []

            # Date restriction if requested
            date_filter = ""
            if since_days:
                since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
                date_filter = f' SINCE "{since_date}"'

            # Mailbox-wide search is the correctness-preserving default used by
            # ingestion. Sender searches remain available as an explicit
            # narrowing optimization.
            search_terms: list[str]
            if search_all:
                search_terms = [f"({criteria}{date_filter})"]
            else:
                search_terms = [
                    f'({criteria} FROM "{sender}"{date_filter})'
                    for sender in target_senders
                ]
            for search_term in search_terms:
                res, data = self._imap.search(None, search_term)
                if res == "OK" and data and data[0]:
                    for msg_id in data[0].split():
                        if msg_id not in uids_to_fetch:
                            uids_to_fetch.append(msg_id)

            # Limit total messages to fetch (newest first)
            uids_to_fetch = uids_to_fetch[-limit:]
            uids_to_fetch.reverse()  # Newest first

            for uid_bytes in uids_to_fetch:
                uid_str = uid_bytes.decode()
                res, msg_data = self._imap.fetch(uid_bytes, "(RFC822)")
                if res != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email_bytes = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_email_bytes = part[1]
                        break

                if not raw_email_bytes:
                    continue

                msg_obj = email.message_from_bytes(raw_email_bytes)
                parsed_msg = self._parse_mime_message(uid_str, msg_obj)
                messages.append(parsed_msg)

            logger.info("Fetched %d messages from Gmail", len(messages))
            return messages

        except Exception as exc:
            logger.error("Error during message retrieval: %s", exc)
            return []

    def mark_as_read(self, uids: list[str]) -> bool:
        """Mark given email UIDs as read (\\Seen)."""
        if not self.is_connected or not self._imap or not uids:
            return False
        try:
            for uid in uids:
                self._imap.store(uid.encode(), "+FLAGS", "\\Seen")
            return True
        except Exception as exc:
            logger.error("Failed to mark messages as read: %s", exc)
            return False

    def _parse_mime_message(self, uid: str, msg: email.message.Message) -> EmailMessage:
        """Convert a standard Python email.message.Message into an EmailMessage dataclass."""
        subject = _decode_mime_header(msg.get("Subject", ""))
        from_hdr = _decode_mime_header(msg.get("From", ""))
        to_hdr = _decode_mime_header(msg.get("To", ""))
        date_hdr = _decode_mime_header(msg.get("Date", ""))
        msg_id = _decode_mime_header(msg.get("Message-ID", ""))

        # Parse date timestamp
        dt_val: datetime | None = None
        if date_hdr:
            try:
                parsed_tuple = email.utils.parsedate_to_datetime(date_hdr)
                if parsed_tuple:
                    dt_val = parsed_tuple
            except Exception:
                pass

        body_html = ""
        body_plain = ""
        headers: dict[str, str] = {}

        for k, v in msg.items():
            headers[k] = _decode_mime_header(v)

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="replace")
                        if content_type == "text/html" and not body_html:
                            body_html = text
                        elif content_type == "text/plain" and not body_plain:
                            body_plain = text
                except Exception:
                    continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                    if msg.get_content_type() == "text/html":
                        body_html = text
                    else:
                        body_plain = text
            except Exception:
                pass

        sender_clean = _extract_email_address(from_hdr)

        return EmailMessage(
            uid=uid,
            message_id=msg_id,
            sender=sender_clean,
            recipient=to_hdr,
            subject=subject,
            date_str=date_hdr,
            date_timestamp=dt_val,
            body_html=body_html,
            body_plain=body_plain,
            headers=headers,
            folder=self.config.folder,
        )
