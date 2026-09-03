"""Shared runtime configuration for storage and document rendering.

The checked-in ``*.example.jsonc`` files are documentation only. Runtime
configuration is read from strict, comment-free JSON files under the user's
configuration directory. Environment variables retain precedence so existing
deployments and command-line workflows remain compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


CONFIG_DIRECTORY = Path.home() / ".config" / "job-application-agents"
CONFIG_PATH = CONFIG_DIRECTORY / "config.json"
RENDER_CONFIG_PATH = CONFIG_DIRECTORY / "render.json"

APPLICATION_BACKENDS = (
    "firestore_notion",
    "firestore_only",
    "notion_only",
    "local_only",
)
NOTION_SYNC_MODES = ("bidirectional", "firestore_to_notion", "disabled")
RENDER_ENGINES = ("xelatex", "cvrender")
RENDER_MODES = ("local", "cloud", "auto")
RENDER_PROFILES = ("auto", "international", "france")
RENDER_TEMPLATES = ("builtin",)
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class ConfigurationError(ValueError):
    """Raised when a runtime configuration file contains invalid values."""


def load_json_config(path: Path | None = None) -> dict[str, Any]:
    """Load one strict JSON object, returning an empty object when absent.

    Deliberately using :func:`json.loads` here means JSONC comments are not
    accepted at runtime. The example files are intended to be copied and
    edited into the two comment-free files in ``~/.config``.
    """

    config_path = (path or CONFIG_PATH).expanduser()
    if not config_path.is_file():
        return {}
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"invalid JSON configuration {config_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"configuration must be a JSON object: {config_path}")
    return value


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Backward-compatible short name for loading the storage config."""

    return load_json_config(path)


def _env(environ: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _configured(config: Mapping[str, Any], key: str) -> Any:
    value = config.get(key)
    if value is not None:
        return value
    storage = config.get("storage")
    if isinstance(storage, dict):
        return storage.get(key)
    return None


def _path(value: Any) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError("path configuration values must be non-empty strings")
    return Path(value).expanduser().resolve()


def _required_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class StorageConfig:
    # Local files are always retained as the artifact/evidence store.  The
    # backend names describe the optional application-status integration.
    application_backend: str = "notion_only"
    notion_sync: str = "disabled"
    data_root: Path | None = None
    applications_root: Path | None = None
    firestore_project_id: str | None = None
    notion_database_id: str | None = None


def load_storage_config(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> StorageConfig:
    """Resolve storage settings with environment variables taking precedence."""

    env = os.environ if environ is None else environ
    config = load_json_config(path)
    backend = _env(env, "JAA_APPLICATION_BACKEND", "APPLICATION_BACKEND")
    backend = backend or _configured(config, "application_backend") or "notion_only"
    if backend not in APPLICATION_BACKENDS:
        raise ConfigurationError(
            f"application_backend must be one of: {', '.join(APPLICATION_BACKENDS)}"
        )

    notion_sync = _env(env, "JAA_NOTION_SYNC", "NOTION_SYNC")
    notion_sync = notion_sync or _configured(config, "notion_sync") or "disabled"
    if notion_sync not in NOTION_SYNC_MODES:
        raise ConfigurationError(f"notion_sync must be one of: {', '.join(NOTION_SYNC_MODES)}")

    data_root = _path(_env(env, "INTEGRATIONS_DATA_ROOT", "JAA_DATA_ROOT") or _configured(config, "data_root"))
    applications_root = _path(
        _env(env, "JAA_APPLICATIONS_ROOT", "APPLICATIONS_ROOT")
        or _configured(config, "applications_root")
    )
    if applications_root is None and data_root is not None:
        applications_root = data_root / "applications"

    project_id = _env(
        env, "JAA_FIREBASE_PROJECT_ID", "GCLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT"
    ) or _required_string(_configured(config, "firestore_project_id"), "firestore_project_id")
    notion_database_id = _env(env, "NOTION_DATABASE_ID") or _required_string(
        _configured(config, "notion_database_id"), "notion_database_id"
    )
    return StorageConfig(
        application_backend=backend,
        notion_sync=notion_sync,
        data_root=data_root,
        applications_root=applications_root,
        firestore_project_id=project_id,
        notion_database_id=notion_database_id,
    )


def cvrender_adapter_available() -> bool:
    """Return whether the optional external CV renderer adapter is installed."""

    return importlib.util.find_spec("job_application_agents.render_service.cvrender") is not None


def available_render_engines() -> tuple[str, ...]:
    """Return renderer engines usable by this installation."""

    if cvrender_adapter_available():
        return RENDER_ENGINES
    return ("xelatex",)


def _validate_slug(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SLUG_PATTERN.fullmatch(value):
        raise ConfigurationError(f"{field} must be 'builtin' or a lower-case slug")
    return value


@dataclass(frozen=True)
class RenderConfig:
    engine: str = "xelatex"
    mode: str = "local"
    profile: str = "auto"
    template: str = "builtin"


def load_render_config(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> RenderConfig:
    """Resolve rendering settings and reject unavailable renderer adapters."""

    env = os.environ if environ is None else environ
    config = load_json_config(path or RENDER_CONFIG_PATH)
    engine = _env(env, "JAA_RENDER_ENGINE", "RENDER_ENGINE") or config.get("engine") or "xelatex"
    if engine not in RENDER_ENGINES:
        raise ConfigurationError(f"engine must be one of: {', '.join(RENDER_ENGINES)}")
    if engine not in available_render_engines():
        raise ConfigurationError(
            "render engine 'cvrender' is configured, but its adapter is unavailable"
        )

    mode = _env(env, "JAA_RENDER_MODE", "RENDER_MODE") or config.get("mode") or "local"
    if mode not in RENDER_MODES:
        raise ConfigurationError(f"mode must be one of: {', '.join(RENDER_MODES)}")

    profile = _env(env, "JAA_RENDER_PROFILE", "RENDER_PROFILE") or config.get("profile") or "auto"
    if profile not in RENDER_PROFILES:
        profile = _validate_slug(profile, "profile")
    template = _env(env, "JAA_RENDER_TEMPLATE", "RENDER_TEMPLATE") or config.get("template") or "builtin"
    if template != "builtin":
        template = _validate_slug(template, "template")
    return RenderConfig(engine=engine, mode=mode, profile=profile, template=template)


__all__ = [
    "APPLICATION_BACKENDS",
    "CONFIG_DIRECTORY",
    "CONFIG_PATH",
    "ConfigurationError",
    "NOTION_SYNC_MODES",
    "RENDER_CONFIG_PATH",
    "RENDER_ENGINES",
    "RENDER_MODES",
    "RENDER_PROFILES",
    "RENDER_TEMPLATES",
    "RenderConfig",
    "StorageConfig",
    "available_render_engines",
    "cvrender_adapter_available",
    "load_config",
    "load_json_config",
    "load_render_config",
    "load_storage_config",
]
