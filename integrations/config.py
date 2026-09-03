"""Configuration management for the integrations subsystem."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from job_application_agents.config import load_storage_config

from .models import EmailAccountConfig


DEFAULT_SENDERS = [
    "jobalerts-noreply@linkedin.com",
    "alert@indeed.com",
    "do-not-reply@indeed.com",
    "jobs-noreply@glassdoor.com",
    "notifications@otta.com",
    "no-reply@greenhouse.io",
    "jobs@lever.co",
]


class IntegrationsConfig:
    """Manages configuration for integrations with layered fallback resolution."""

    CONFIG_FILENAMES = [
        "integrations.config.json",
        ".integrations.json",
        "integrations.json",
    ]

    def __init__(self, custom_config_path: Path | None = None) -> None:
        self.custom_config_path = custom_config_path
        self._raw_config: dict[str, Any] = self._load_file_config()

    def _find_config_file(self) -> Path | None:
        if self.custom_config_path and self.custom_config_path.is_file():
            return self.custom_config_path

        env_path = os.getenv("INTEGRATIONS_CONFIG_FILE")
        if env_path and Path(env_path).is_file():
            return Path(env_path)

        search_locations = [
            Path.cwd(),
            Path.cwd() / "job-search",
            Path.home() / "Documents" / "job-search",
            Path.home() / ".config" / "job-application-agents",
        ]

        for loc in search_locations:
            for fname in self.CONFIG_FILENAMES:
                candidate = loc / fname
                if candidate.is_file():
                    return candidate
        generic_config = Path.home() / ".config" / "job-application-agents" / "config.json"
        if generic_config.is_file():
            return generic_config
        return None

    def _load_file_config(self) -> dict[str, Any]:
        cfg_file = self._find_config_file()
        if cfg_file and cfg_file.is_file():
            try:
                return json.loads(cfg_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def get_email_config(self) -> EmailAccountConfig:
        """Resolve email configuration from environment variables, config file, or defaults."""
        file_email = self._raw_config.get("email", {})

        # Environment variables take highest precedence
        email_address = (
            os.getenv("GMAIL_USER")
            or os.getenv("GMAIL_EMAIL")
            or os.getenv("GMAIL_ADDRESS")
            or file_email.get("email_address")
            or ""
        )

        app_password = (
            os.getenv("GMAIL_APP_PASSWORD")
            or os.getenv("GMAIL_PASSWORD")
            or file_email.get("app_password")
            or ""
        )

        imap_server = (
            os.getenv("GMAIL_IMAP_SERVER")
            or file_email.get("imap_server")
            or "imap.gmail.com"
        )

        imap_port = int(
            os.getenv("GMAIL_IMAP_PORT")
            or file_email.get("imap_port")
            or 993
        )

        use_ssl = os.getenv("GMAIL_USE_SSL", "true").lower() in ("true", "1", "yes")

        folder = os.getenv("GMAIL_FOLDER") or file_email.get("folder") or "INBOX"

        # Target senders list
        env_senders = os.getenv("GMAIL_TARGET_SENDERS")
        if env_senders:
            target_senders = [s.strip() for s in env_senders.split(",") if s.strip()]
        elif "target_senders" in file_email:
            target_senders = list(file_email["target_senders"])
        else:
            target_senders = list(DEFAULT_SENDERS)

        max_messages = int(
            os.getenv("GMAIL_MAX_MESSAGES")
            or file_email.get("max_messages")
            or 25
        )

        search_criteria = (
            os.getenv("GMAIL_SEARCH_CRITERIA")
            or file_email.get("search_criteria")
            or "UNSEEN"
        )

        mark_as_read = (
            os.getenv("GMAIL_MARK_AS_READ", "false").lower() in ("true", "1", "yes")
            or file_email.get("mark_as_read", False)
        )

        auth_mode = (
            os.getenv("GMAIL_AUTH_MODE")
            or file_email.get("auth_mode")
            or "app_password"
        )

        oauth_token_path = (
            os.getenv("GMAIL_OAUTH_TOKEN_PATH")
            or file_email.get("oauth_token_path")
        )
        client_secrets_path = (
            os.getenv("GMAIL_CLIENT_SECRETS_PATH")
            or file_email.get("client_secrets_path")
        )

        return EmailAccountConfig(
            email_address=email_address,
            app_password=app_password,
            imap_server=imap_server,
            imap_port=imap_port,
            use_ssl=use_ssl,
            folder=folder,
            target_senders=target_senders,
            search_criteria=search_criteria,
            max_messages=max_messages,
            mark_as_read=mark_as_read,
            auth_mode=auth_mode,
            oauth_token_path=oauth_token_path,
            client_secrets_path=client_secrets_path,
        )

    def get_min_match_score(self) -> int:
        """Minimum match score threshold to stage or highlight a job."""
        env_val = os.getenv("MATCH_SCORE_MIN_THRESHOLD")
        if env_val:
            try:
                return int(env_val)
            except ValueError:
                pass
        return int(self._raw_config.get("min_match_score", 60))

    def get_staging_directory(self) -> Path:
        """Resolve staging directory for ingested jobs."""
        env_dir = os.getenv("INGESTION_STAGING_DIR")
        if env_dir:
            return Path(env_dir).expanduser().resolve()

        file_dir = self._raw_config.get("staging_dir")
        if file_dir:
            return Path(file_dir).expanduser().resolve()

        # Default paths in priority order
        candidates = [
            Path("job-search/staging_job"),
            Path.home() / "Documents" / "job-search" / "staging_job",
            Path("staging_job"),
        ]
        for c in candidates:
            if c.parent.is_dir():
                return c.resolve()
        return Path("job-search/staging_job").resolve()

    def get_data_root(self) -> Path:
        """Resolve the durable local data root used by integration ledgers."""
        env_root = os.getenv("INTEGRATIONS_DATA_ROOT") or os.getenv("JAA_DATA_ROOT")
        if env_root:
            return Path(env_root).expanduser().resolve()
        configured = self._raw_config.get("data_root")
        if configured:
            return Path(configured).expanduser().resolve()
        configured = load_storage_config().data_root
        if configured is not None:
            return configured
        # The repository's existing job-search directory is the conventional
        # private data root and is ignored by version control.
        return (Path.cwd() / "job-search").resolve()

    def get_playwright_settings(self) -> dict[str, Any]:
        """Get Playwright runtime settings."""
        headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() not in ("false", "0", "no")
        slowmo = int(os.getenv("PLAYWRIGHT_SLOWMO", "0"))
        return {
            "headless": headless,
            "slowmo": slowmo,
            "timeout_ms": int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "30000")),
        }

    def save_config(self, destination_path: Path | None = None) -> Path:
        """Save active config to file for persistent configuration."""
        target = destination_path or self._find_config_file() or Path("integrations.config.json")
        target.parent.mkdir(parents=True, exist_ok=True)

        email_cfg = self.get_email_config().to_dict()
        data = {
            "email": email_cfg,
            "min_match_score": self.get_min_match_score(),
            "staging_dir": str(self.get_staging_directory()),
            "data_root": str(self.get_data_root()),
            "playwright": self.get_playwright_settings(),
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return target


default_config = IntegrationsConfig()
