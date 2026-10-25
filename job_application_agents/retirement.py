"""Project-specific retirement policy; local rendering remains available."""
import json
import os
from urllib.parse import urlparse

RETIRED_PROJECT = "tinder-jobs-4bf1b"
MESSAGE = "Cloud rendering and automatic Notion sync for tinder-jobs-4bf1b were retired on 2026-10-05. Use local rendering; stored records remain available."

def configured_project():
    for key in ("JAA_FIREBASE_PROJECT_ID", "GCLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT"):
        if os.environ.get(key):
            return os.environ[key]
    try:
        return json.loads(os.environ.get("FIREBASE_CONFIG", "{} ")).get("projectId")
    except (ValueError, AttributeError):
        return None

def require_active(project=None, *, url=None):
    host = urlparse(url or "").hostname or ""
    retired_host = host in {
        "jaa-latex-worker-l4k2wdufaa-ew.a.run.app",
        "jaa-latex-worker-550800882354.europe-west1.run.app",
    }
    if retired_host or ((project or configured_project()) == RETIRED_PROJECT
                        and not os.environ.get("FIRESTORE_EMULATOR_HOST")):
        raise RuntimeError(MESSAGE)
