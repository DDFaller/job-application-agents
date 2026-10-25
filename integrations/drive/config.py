"""Runtime configuration for the read-only Google Drive artifact folder."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from job_application_agents.config import ConfigurationError, load_json_config

from .client import parse_folder_id


DRIVE_AUTH_MODES = ("oauth", "service_account")
DEFAULT_CLIENT_SECRETS_PATH = (
    Path.home() / ".config" / "job-application-agents" / "drive-client-secret.json"
)
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "job-application-agents" / "drive-token.json"
DEFAULT_DATA_ROOT = Path.home() / "Documents" / "job-search"


def _env(environ: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _drive_section(config: Mapping[str, object]) -> Mapping[str, object]:
    section = config.get("drive")
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigurationError("drive configuration must be a JSON object")
    return section


def _path(value: object, field: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty string")
    return Path(value).expanduser()


@dataclass(frozen=True)
class DriveConfig:
    """Resolved Drive settings. Environment variables win over the config file."""

    folder_id: str | None = None
    auth_mode: str = "oauth"
    client_secrets_path: Path = DEFAULT_CLIENT_SECRETS_PATH
    token_path: Path = DEFAULT_TOKEN_PATH
    service_account_file: Path | None = None
    service_account_from_env: bool = False
    data_root: Path = DEFAULT_DATA_ROOT


def load_drive_config(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> DriveConfig:
    """Load the Drive folder settings without reading credential file contents."""

    env = os.environ if environ is None else environ
    config = load_json_config(path)
    drive = _drive_section(config)

    raw_folder = _env(env, "JAA_DRIVE_FOLDER_ID") or drive.get("folder_id")
    folder_id = None
    if raw_folder is not None:
        if not isinstance(raw_folder, str):
            raise ConfigurationError("drive folder_id must be a string")
        folder_id = parse_folder_id(raw_folder)

    auth_mode = _env(env, "JAA_DRIVE_AUTH_MODE") or drive.get("auth_mode") or "oauth"
    if not isinstance(auth_mode, str) or auth_mode not in DRIVE_AUTH_MODES:
        raise ConfigurationError(
            f"drive auth_mode must be one of: {', '.join(DRIVE_AUTH_MODES)}"
        )

    client_secrets = _path(
        _env(env, "JAA_DRIVE_CLIENT_SECRETS_PATH") or drive.get("client_secrets_path"),
        "drive client_secrets_path",
    ) or DEFAULT_CLIENT_SECRETS_PATH
    token_path = _path(
        _env(env, "JAA_DRIVE_TOKEN_PATH") or drive.get("token_path"),
        "drive token_path",
    ) or DEFAULT_TOKEN_PATH
    service_account_file = _path(
        _env(env, "JAA_DRIVE_SERVICE_ACCOUNT_FILE") or drive.get("service_account_file"),
        "drive service_account_file",
    )
    data_root = _path(
        _env(env, "JAA_DATA_ROOT", "INTEGRATIONS_DATA_ROOT") or config.get("data_root"),
        "data_root",
    ) or DEFAULT_DATA_ROOT
    return DriveConfig(
        folder_id=folder_id,
        auth_mode=auth_mode,
        client_secrets_path=client_secrets,
        token_path=token_path,
        service_account_file=service_account_file,
        service_account_from_env=bool(_env(env, "JAA_DRIVE_SERVICE_ACCOUNT_JSON")),
        data_root=data_root,
    )


def materialize_service_account_json(
    raw: str, *, destination: Path, repo_root: Path
) -> Path:
    """Write a service-account key outside the repository and return its path.

    The JSON value is never included in error messages.
    """

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigurationError("JAA_DRIVE_SERVICE_ACCOUNT_JSON is not valid JSON")
    if (
        not isinstance(value, dict)
        or value.get("type") != "service_account"
        or not isinstance(value.get("client_email"), str)
        or not value.get("client_email", "").strip()
        or not isinstance(value.get("private_key"), str)
        or not value.get("private_key", "").strip()
    ):
        raise ConfigurationError(
            "JAA_DRIVE_SERVICE_ACCOUNT_JSON must be a Google service account key"
        )

    destination = destination.expanduser().resolve()
    repo_root = repo_root.expanduser().resolve()
    if destination == repo_root or _is_relative_to(destination, repo_root) or _is_relative_to(repo_root, destination):
        raise ConfigurationError(
            "refusing to write the Drive service account key inside the repository"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(destination)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return destination


def default_service_account_cache() -> Path:
    """Return the private cache path used for an env-provided service account key."""

    return Path(tempfile.gettempdir()) / "job-application-agents" / "drive-service-account.json"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
