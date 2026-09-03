#!/usr/bin/env python3
"""Start Codex with this repository and the job-search data root in scope."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path.home() / "Documents" / "job-search")
    parser.add_argument("--live", action="store_true", help="opt into live Firebase rendering")
    parser.add_argument("--firebase-project-id", help="Firebase project ID (required with --live)")
    parser.add_argument("codex_args", nargs="*")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    data_root = args.data_root.expanduser().resolve()
    if data_root == repo or data_root.is_relative_to(repo) or repo.is_relative_to(data_root):
        raise SystemExit(
            "--data-root must be a separate private directory that does not "
            "contain or live inside the repository"
        )
    runtime_bin = repo / ".venv" / "bin"
    if not (runtime_bin / "python").is_file():
        raise SystemExit("missing .venv runtime; run python3 scripts/setup.py first")
    os.environ["PATH"] = str(runtime_bin) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault(
        "JAA_ARTIFACT_ROOT",
        str(data_root / ".render-service" / "artifacts"),
    )
    os.environ.setdefault("JAA_RENDER_MODE", "local")
    if args.live:
        project_id = args.firebase_project_id or os.environ.get("JAA_FIREBASE_PROJECT_ID")
        if not project_id:
            raise SystemExit("--live requires --firebase-project-id or JAA_FIREBASE_PROJECT_ID")
        os.environ["JAA_FIREBASE_PROJECT_ID"] = project_id
        os.environ["JAA_RENDER_MODE"] = "cloud"
        os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
    else:
        # A normal launch must be unable to fall through to a configured live
        # Firestore project. The emulator can be started separately by the
        # local render stack; failing closed is safer than using production.
        os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8080"
        os.environ["JAA_FIREBASE_PROJECT_ID"] = "demo-job-application-agents"

    # Integration credentials belong to the coordinator/connector process,
    # never to Codex workers or their subprocesses. Keep only configuration
    # needed to select the data and Firebase/render backends.
    for secret_name in (
        "NOTION_TOKEN",
        "NOTION_API_KEY",
        "GMAIL_ACCESS_TOKEN",
        "GMAIL_REFRESH_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "FIREBASE_TOKEN",
        "BROWSER_COOKIE",
        "PLAYWRIGHT_STORAGE_STATE",
    ):
        os.environ.pop(secret_name, None)
    # A complete application reserves five nested workers (extraction,
    # evidence, writer, copy humanizer, and reviewer). Keep these limits
    # visible to the coordinator so a queue cannot oversubscribe the
    # six-thread session.
    os.environ.setdefault("JAA_WORKFLOW_MAX_NESTED_SLOTS", "6")
    os.environ.setdefault("JAA_WORKFLOW_MAX_CONCURRENT_APPLICATIONS", "1")
    try:
        nested_slots = int(os.environ["JAA_WORKFLOW_MAX_NESTED_SLOTS"])
    except ValueError as exc:
        raise SystemExit("JAA_WORKFLOW_MAX_NESTED_SLOTS must be an integer") from exc
    if nested_slots < 1:
        raise SystemExit("JAA_WORKFLOW_MAX_NESTED_SLOTS must be positive")
    command = [
        "codex", "-C", str(repo), "--add-dir", str(data_root),
        "-c", "agents.enabled=true", "-c", f"agents.max_concurrent_threads_per_session={nested_slots}",
        *args.codex_args,
    ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
