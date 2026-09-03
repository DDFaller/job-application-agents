from __future__ import annotations

import os
from pathlib import Path

from job_application_agents.config import load_storage_config


DEFAULT_EMULATOR_PROJECT_ID = "demo-job-application-agents"


def firebase_project_id() -> str:
    configured = (
        os.environ.get("JAA_FIREBASE_PROJECT_ID")
        or os.environ.get("GCLOUD_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
    )
    if configured:
        return configured
    configured_file = load_storage_config().firestore_project_id
    if configured_file:
        return configured_file
    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return DEFAULT_EMULATOR_PROJECT_ID
    raise RuntimeError("set JAA_FIREBASE_PROJECT_ID before connecting to live Firestore")


def artifact_root() -> Path:
    configured = os.environ.get("JAA_ARTIFACT_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
    elif (configured_data_root := load_storage_config().data_root) is not None:
        root = (configured_data_root / ".render-service" / "artifacts").resolve()
    elif (Path.home() / "Documents" / "job-search").is_dir():
        root = (Path.home() / "Documents" / "job-search" / ".render-service" / "artifacts").resolve()
    elif Path("job-search").is_dir():
        root = Path("job-search/.render-service/artifacts").resolve()
    else:
        root = (Path.home() / ".cache" / "job-application-agents" / "artifacts").resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return root


DEFAULT_USER_ID = "default-user"


def get_user_id(data_root: Path | None = None) -> str:
    """Resolve the active user ID from env, local config, ADC credentials, or default."""
    from_env = os.environ.get("JAA_USER_ID")
    if from_env and from_env.strip():
        return from_env.strip()

    candidate_configs = [
        (data_root or (Path.home() / "Documents" / "job-search")) / ".config.json",
        Path.home() / ".config" / "job-application-agents" / "config.json",
    ]
    for config_path in candidate_configs:
        try:
            if config_path.is_file():
                import json
                data = json.loads(config_path.read_text(encoding="utf-8"))
                uid = data.get("user_id") or data.get("userId")
                if uid and str(uid).strip():
                    return str(uid).strip()
        except Exception:
            pass

    adc_path = Path(os.environ.get(
        "JAA_ADC_PATH",
        str(Path.home() / ".config" / "gcloud" / "application_default_credentials.json"),
    )).expanduser()
    if adc_path.is_file():
        try:
            import json
            data = json.loads(adc_path.read_text(encoding="utf-8"))
            account = data.get("account") or data.get("client_id")
            if account and str(account).strip():
                # Sanitize email or client_id to safe ID
                import re
                safe = re.sub(r"[^a-zA-Z0-9_-]", "_", str(account).strip())
                return safe
        except Exception:
            pass

    return DEFAULT_USER_ID
