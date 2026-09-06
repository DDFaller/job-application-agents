"""Read-only Gmail API client for job-alert ingestion."""

from __future__ import annotations

import base64
import email
import logging
import os
from pathlib import Path
from typing import Any

from ..base import BaseEmailClient
from ..models import EmailAccountConfig, EmailMessage
from .gmail_client import GmailClient

logger = logging.getLogger(__name__)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_API_SCOPES = (GMAIL_READONLY_SCOPE,)
DEFAULT_CLIENT_SECRETS_PATH = Path.home() / ".config" / "job-application-agents" / "gmail-client-secret.json"
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "job-application-agents" / "gmail-token.json"


class GmailApiConfigurationError(RuntimeError):
    """Raised when Gmail API OAuth configuration is incomplete or invalid."""


class GmailApiClient(BaseEmailClient):
    """Gmail API client using an installed-app OAuth flow and read-only access."""

    def __init__(self, config: EmailAccountConfig, service: Any | None = None) -> None:
        self.config = config
        self._service = service
        self._connected = service is not None
        self._last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._service is not None

    @property
    def client_secrets_path(self) -> Path:
        return Path(self.config.client_secrets_path or DEFAULT_CLIENT_SECRETS_PATH).expanduser().resolve()

    @property
    def token_path(self) -> Path:
        return Path(self.config.oauth_token_path or DEFAULT_TOKEN_PATH).expanduser().resolve()

    def _credentials(self, *, interactive: bool = True) -> Any:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GmailApiConfigurationError(
                "Gmail API dependencies are missing; install google-api-python-client, "
                "google-auth-httplib2, and google-auth-oauthlib"
            ) from exc

        credentials = None
        token_path = self.token_path
        if token_path.is_file():
            try:
                credentials = Credentials.from_authorized_user_file(
                    str(token_path), list(GMAIL_API_SCOPES)
                )
            except (OSError, ValueError) as exc:
                logger.warning("Ignoring invalid Gmail OAuth token %s: %s", token_path, exc)

        if credentials and credentials.valid:
            return credentials
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                self._save_credentials(credentials)
                return credentials
            except Exception as exc:
                logger.warning("Gmail OAuth token refresh failed: %s", exc)

        if not interactive:
            raise GmailApiConfigurationError(
                f"Gmail OAuth authorization is required; run authorize-gmail with client "
                f"secrets at {self.client_secrets_path}"
            )
        if not self.client_secrets_path.is_file():
            raise GmailApiConfigurationError(
                f"Gmail desktop OAuth client JSON not found: {self.client_secrets_path}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_path), list(GMAIL_API_SCOPES)
        )
        credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        self._save_credentials(credentials)
        return credentials

    def _save_credentials(self, credentials: Any) -> None:
        token_path = self.token_path
        token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = token_path.with_name(f".{token_path.name}.{os.getpid()}.tmp")
        temporary.write_text(credentials.to_json(), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(token_path)
        try:
            os.chmod(token_path, 0o600)
        except OSError:
            pass

    def _build_service(self, credentials: Any) -> Any:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GmailApiConfigurationError(
                "Gmail API dependencies are missing; install google-api-python-client, "
                "google-auth-httplib2, and google-auth-oauthlib"
            ) from exc
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def authorize(self) -> str:
        """Run or refresh OAuth and return the authorized Gmail address."""
        credentials = self._credentials(interactive=True)
        self._service = self._build_service(credentials)
        self._connected = True
        return self._profile_email()

    def connect(self) -> bool:
        """Load cached OAuth credentials without starting an interactive flow."""
        try:
            credentials = self._credentials(interactive=False)
            self._service = self._build_service(credentials)
            self._connected = True
            self._last_error = None
            return True
        except Exception as exc:
            self._connected = False
            self._service = None
            self._last_error = str(exc)
            logger.error("Failed to connect to Gmail API: %s", exc)
            return False

    def disconnect(self) -> None:
        """Release the Gmail API service handle without revoking OAuth access."""
        self._service = None
        self._connected = False

    def _profile_email(self) -> str:
        if not self._service:
            return self.config.email_address
        profile = self._service.users().getProfile(userId="me").execute()
        email_address = str(profile.get("emailAddress") or "").strip()
        if email_address:
            self.config.email_address = email_address
        return email_address

    def test_connection(self) -> dict[str, Any]:
        """Verify OAuth and Gmail API access without changing mailbox state."""
        if not self.is_connected and not self.connect():
            return {
                "status": "CONFIG_ERROR",
                "connected": False,
                "message": self._last_error or "Gmail API authorization failed",
            }
        try:
            email_address = self._profile_email()
            response = self._service.users().messages().list(
                userId="me", maxResults=1, q="in:anywhere"
            ).execute()
            return {
                "status": "READY",
                "connected": True,
                "email_address": email_address,
                "message_count_sample": len(response.get("messages", [])),
                "scope": GMAIL_READONLY_SCOPE,
                "message": "Gmail API read-only access verified successfully.",
            }
        except Exception as exc:
            self._last_error = str(exc)
            return {"status": "API_ERROR", "connected": False, "message": str(exc)}

    @staticmethod
    def _query_for_criteria(criteria: str, folder: str, since_days: int | None) -> str:
        terms: list[str] = []
        if criteria == "UNSEEN":
            terms.append("is:unread")
        elif criteria == "ALL":
            terms.append("in:anywhere")
        elif criteria.strip():
            terms.append(criteria.strip())

        if folder and folder.upper() == "INBOX":
            terms.append("in:inbox")
        elif folder:
            terms.append(f"label:{folder}")
        if since_days is not None:
            if since_days < 0:
                raise ValueError("since_days must be non-negative")
            terms.append(f"newer_than:{since_days}d")
        return " ".join(terms)

    def _list_message_ids(
        self, query: str, limit: int, sender_filters: list[str] | None, search_all: bool
    ) -> list[str]:
        assert self._service is not None
        queries = [query]
        if not search_all and sender_filters:
            queries = [f"{query} from:{sender}".strip() for sender in sender_filters]
        ids: list[str] = []
        for candidate_query in queries:
            response = self._service.users().messages().list(
                userId="me", q=candidate_query, maxResults=min(max(limit, 1), 100)
            ).execute()
            for message in response.get("messages", []):
                message_id = str(message.get("id") or "")
                if message_id and message_id not in ids:
                    ids.append(message_id)
        return ids[:limit]

    def fetch_messages(
        self,
        sender_filters: list[str] | None = None,
        criteria: str = "UNSEEN",
        limit: int = 25,
        since_days: int | None = None,
        search_all: bool = False,
    ) -> list[EmailMessage]:
        """Fetch newest messages as parsed MIME objects for the existing pipeline."""
        if limit <= 0:
            return []
        if not self.is_connected and not self.connect():
            logger.error("Cannot fetch messages: Gmail API is not connected")
            return []
        assert self._service is not None
        query = self._query_for_criteria(criteria, self.config.folder, since_days)
        messages: list[EmailMessage] = []
        try:
            ids = self._list_message_ids(query, limit, sender_filters, search_all)
            for message_id in ids:
                response = self._service.users().messages().get(
                    userId="me", id=message_id, format="raw"
                ).execute()
                raw_value = response.get("raw")
                if not raw_value:
                    continue
                raw_email = base64.urlsafe_b64decode(str(raw_value) + "===")
                parsed = GmailClient(self.config)._parse_mime_message(
                    message_id, email.message_from_bytes(raw_email)
                )
                parsed.folder = self.config.folder
                messages.append(parsed)
            logger.info("Fetched %d messages from Gmail API", len(messages))
            return messages
        except Exception as exc:
            self._last_error = str(exc)
            logger.error("Error during Gmail API message retrieval: %s", exc)
            return []

    def mark_as_read(self, uids: list[str]) -> bool:
        """Refuse mailbox mutation because API mode intentionally uses gmail.readonly."""
        if uids:
            logger.warning("Gmail API mode is read-only; not marking messages as read")
        return False


__all__ = [
    "DEFAULT_CLIENT_SECRETS_PATH",
    "DEFAULT_TOKEN_PATH",
    "GMAIL_API_SCOPES",
    "GMAIL_READONLY_SCOPE",
    "GmailApiClient",
    "GmailApiConfigurationError",
]
