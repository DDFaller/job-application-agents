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


def load_dotenv(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Parse a simple .env file into os.environ without third-party dependencies.

    Existing environment variables are preserved unless ``override=True``.
    Lines with comments (#) or empty lines are ignored. Values wrapped in
    single or double quotes are stripped.
    """
    if path is None:
        # Search current directory, repo root, and config directory
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parent.parent / ".env",
            CONFIG_DIRECTORY / ".env",
        ]
        for candidate in candidates:
            if candidate.is_file():
                path = candidate
                break
    if path is None or not path.is_file():
        return {}

    loaded: dict[str, str] = {}
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        key = key.strip()
        val = raw_val.strip()
        if len(val) >= 2 and ((val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'"))):
            val = val[1:-1]
        loaded[key] = val
        if override or key not in os.environ:
            os.environ[key] = val
    return loaded


# Automatically load .env if present
load_dotenv()

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


def resolve_data_root(
    explicit: Path | str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
    repository_root: Path | None = None,
) -> Path:
    """Resolve the one private data root without consulting the working directory.

    Managed workflows must not silently select ``./job-search``: an agent
    session can have a different working directory or sandbox mount from its
    coordinator.  Explicit input wins, then environment, then user config.
    """

    env = os.environ if environ is None else environ
    value: Path | str | None = explicit
    if value is None:
        value = _env(env, "JAA_DATA_ROOT", "INTEGRATIONS_DATA_ROOT")
    if value is None:
        value = load_storage_config(config_path, environ=env).data_root
    if value is None:
        raise ConfigurationError(
            "data root is required; pass --data-root, set JAA_DATA_ROOT, "
            "or configure storage.data_root"
        )
    root = Path(value).expanduser().resolve()
    repo = repository_root.expanduser().resolve() if repository_root else None
    if repo and (root == repo or root.is_relative_to(repo) or repo.is_relative_to(root)):
        raise ConfigurationError("data root must be outside the repository")
    return root


def _strip_jsonc_comments(text: str) -> str:
    """Strip // single line and /* */ block comments from JSONC."""
    # Remove block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove line comments that are not inside quotes
    lines = []
    for line in text.splitlines():
        in_quote = False
        quote_char = ""
        escape = False
        comment_idx = None
        for i, char in enumerate(line):
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char in ('"', "'"):
                if not in_quote:
                    in_quote = True
                    quote_char = char
                elif quote_char == char:
                    in_quote = False
            elif not in_quote and char == "/" and i + 1 < len(line) and line[i + 1] == "/":
                comment_idx = i
                break
        if comment_idx is not None:
            lines.append(line[:comment_idx])
        else:
            lines.append(line)
    return "\n".join(lines)


def load_json_config(path: Path | None = None) -> dict[str, Any]:
    """Load one JSON/JSONC object, returning an empty object when absent.

    Looks for specified path, or checks in-repo and user config directory
    (supporting both config.json and config.jsonc).
    """

    if path is not None:
        candidates = [path.expanduser()]
    else:
        repo_root = Path(__file__).resolve().parent.parent
        candidates = [
            CONFIG_PATH,
            CONFIG_PATH.with_suffix(".jsonc"),
            repo_root / "config.json",
            repo_root / "config.jsonc",
        ]

    config_path = None
    for candidate in candidates:
        if candidate.is_file():
            config_path = candidate
            break

    if config_path is None:
        return {}

    if config_path.name.endswith(".example.jsonc"):
        raise ConfigurationError(f"invalid JSON configuration {config_path}: example files cannot be used directly")

    try:
        raw_text = config_path.read_text(encoding="utf-8")
        clean_text = _strip_jsonc_comments(raw_text) if config_path.suffix == ".jsonc" else raw_text
        value = json.loads(clean_text)
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
    application_backend: str = "firestore_only"
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
    backend = backend or _configured(config, "application_backend") or "firestore_only"
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
    "resolve_data_root",
]
