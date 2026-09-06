"""Factories for selecting a configured email transport."""

from __future__ import annotations

from ..base import BaseEmailClient
from ..models import EmailAccountConfig, EmailMessage
from .gmail_api_client import GmailApiClient
from .gmail_client import GmailClient


class FallbackEmailClient(BaseEmailClient):
    """Prefer Gmail API and use IMAP only when API access is unavailable."""

    def __init__(self, primary: GmailApiClient, fallback: GmailClient) -> None:
        self.primary = primary
        self.fallback = fallback
        self._active: BaseEmailClient | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._active and self._active.is_connected)

    def _connect_preferred(self) -> BaseEmailClient | None:
        if self.primary.is_connected or self.primary.connect():
            self._active = self.primary
            return self.primary
        if self.fallback.is_connected or self.fallback.connect():
            self._active = self.fallback
            return self.fallback
        return None

    def connect(self) -> bool:
        return self._connect_preferred() is not None

    def disconnect(self) -> None:
        self.primary.disconnect()
        self.fallback.disconnect()
        self._active = None

    def test_connection(self) -> dict[str, object]:
        # Test the API first. Its diagnostic is useful even when no fallback is
        # configured, while a successful fallback is reported explicitly.
        primary_result = self.primary.test_connection()
        if primary_result.get("status") == "READY":
            primary_result["transport"] = "gmail_api"
            self._active = self.primary
            return primary_result

        fallback_result = self.fallback.test_connection()
        if fallback_result.get("status") == "READY":
            fallback_result["transport"] = "imap_fallback"
            self._active = self.fallback
            fallback_result["message"] = (
                "Gmail API unavailable; IMAP App Password fallback verified successfully."
            )
            return fallback_result
        primary_result["fallback"] = fallback_result
        return primary_result

    def fetch_messages(
        self,
        sender_filters: list[str] | None = None,
        criteria: str = "UNSEEN",
        limit: int = 25,
        since_days: int | None = None,
        search_all: bool = False,
    ) -> list[EmailMessage]:
        client = self._active if self.is_connected else self._connect_preferred()
        if client is None:
            return []
        return client.fetch_messages(
            sender_filters=sender_filters,
            criteria=criteria,
            limit=limit,
            since_days=since_days,
            search_all=search_all,
        )

    def mark_as_read(self, uids: list[str]) -> bool:
        if self._active is None:
            return False
        return self._active.mark_as_read(uids)


def create_email_client(config: EmailAccountConfig) -> BaseEmailClient:
    """Create the configured Gmail API client with optional IMAP fallback."""

    mode = (config.auth_mode or "app_password").strip().lower()
    if mode in {"gmail_api", "oauth2"}:
        return FallbackEmailClient(GmailApiClient(config), GmailClient(config))
    if mode == "app_password":
        return GmailClient(config)
    raise ValueError(
        "unsupported Gmail auth_mode; choose 'gmail_api', 'oauth2', or 'app_password'"
    )


__all__ = ["FallbackEmailClient", "create_email_client"]
