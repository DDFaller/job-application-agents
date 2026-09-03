#!/usr/bin/env python3
"""Inspect local artifacts or explicitly synchronize them with Firestore.

The default command is local-only. Firestore push/pull/status and the queued
Notion worker require ``--cloud`` (and ``--live`` additionally selects live
Firebase instead of the local emulator).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

# Auto-switch to .venv python if running under system python
if VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from job_application_agents.config import load_storage_config
from job_application_agents.render_service.config import firebase_project_id, get_user_id
from job_application_agents.sync.firestore import FirestoreUserSyncRepository
from job_application_agents.sync.service import SyncService


def create_service(args: argparse.Namespace) -> tuple[SyncService, str]:
    if not (getattr(args, "cloud", False) or getattr(args, "live", False)):
        raise RuntimeError("Firestore sync is opt-in; pass --cloud or --live")
    if getattr(args, "live", False):
        if not (args.firebase_project_id or os.environ.get("JAA_FIREBASE_PROJECT_ID")):
            raise RuntimeError("--live requires --firebase-project-id or JAA_FIREBASE_PROJECT_ID")
        os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
    else:
        os.environ.setdefault("JAA_FIREBASE_PROJECT_ID", "demo-job-application-agents")
        os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")

    project_id = args.firebase_project_id or firebase_project_id()
    data_root = args.data_root.expanduser().resolve()
    user_id = args.user_id or get_user_id(data_root)

    repo = FirestoreUserSyncRepository(project_id=project_id)
    notion_repo = None
    if os.environ.get("NOTION_TOKEN") or args.command in {"push", "status"}:
        from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
        notion_repo = FirestoreNotionJobRepository(project_id=project_id, client=repo.client)
    service = SyncService(repository=repo, default_data_root=data_root, notion_repository=notion_repo)
    return service, user_id


def cmd_push(args: argparse.Namespace) -> int:
    try:
        service, user_id = create_service(args)
    except RuntimeError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 2
    data_root = args.data_root.expanduser().resolve()
    push_all_flag = args.all or (not args.curriculum and not args.profiles and not args.applications and not args.app_dir)

    print(f"Pushing to Firestore for user: {user_id} (project: {service.repository.project_id})")

    if args.app_dir:
        app_path = args.app_dir.expanduser().resolve()
        snapshot = service.push_application_directory(user_id, app_path)
        print(f"OK Pushed application: {snapshot.application_id} (version {snapshot.current_version})")
        return 0

    pushed_items = []
    if push_all_flag or args.curriculum:
        try:
            curr = service.push_curriculum(user_id, data_root)
            print(f"OK Pushed curriculum: version {curr.version} ({len(curr.sources)} source files)")
            pushed_items.append("curriculum")
        except Exception as exc:
            print(f"FAIL Pushing curriculum: {exc}", file=sys.stderr)
            if not push_all_flag:
                return 1

    if push_all_flag or args.profiles:
        try:
            prof = service.push_profiles(user_id, data_root)
            print(f"OK Pushed role profiles: version {prof.version}")
            pushed_items.append("profiles")
        except Exception as exc:
            print(f"FAIL Pushing profiles: {exc}", file=sys.stderr)
            if not push_all_flag:
                return 1

    if push_all_flag or args.applications:
        try:
            apps = service.push_applications(user_id, data_root)
            print(f"OK Pushed {len(apps)} applications")
            for app in apps:
                print(f"   - {app.application_id} ({app.current_version})")
                pushed_items.append(f"app:{app.application_id}")
        except Exception as exc:
            print(f"FAIL Pushing applications: {exc}", file=sys.stderr)
            if not push_all_flag:
                return 1

    print(f"\nPush complete ({len(pushed_items)} items synced).")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    try:
        service, user_id = create_service(args)
    except RuntimeError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 2
    data_root = args.data_root.expanduser().resolve()
    pull_all_flag = args.all or (not args.curriculum and not args.profiles and not args.applications)

    print(f"Pulling from Firestore for user: {user_id} (project: {service.repository.project_id})")

    pulled_items = []
    if pull_all_flag or args.curriculum:
        try:
            if service.pull_curriculum(user_id, data_root):
                print(f"OK Pulled curriculum sources to {data_root / 'sources'}")
                pulled_items.append("curriculum")
            else:
                print("NOTE No remote curriculum found in Firestore.")
        except Exception as exc:
            print(f"FAIL Pulling curriculum: {exc}", file=sys.stderr)
            if not pull_all_flag:
                return 1

    if pull_all_flag or args.profiles:
        try:
            if service.pull_profiles(user_id, data_root):
                print(f"OK Pulled profiles to {data_root / 'master-curriculum' / 'profiles'}")
                pulled_items.append("profiles")
            else:
                print("NOTE No remote profiles found in Firestore.")
        except Exception as exc:
            print(f"FAIL Pulling profiles: {exc}", file=sys.stderr)
            if not pull_all_flag:
                return 1

    if pull_all_flag or args.applications:
        try:
            app_ids = service.pull_applications(user_id, data_root)
            print(f"OK Pulled {len(app_ids)} applications to {data_root / 'applications'}")
            for app_id in app_ids:
                print(f"   - {app_id}")
                pulled_items.append(f"app:{app_id}")
        except Exception as exc:
            print(f"FAIL Pulling applications: {exc}", file=sys.stderr)
            if not pull_all_flag:
                return 1

    print(f"\nPull complete ({len(pulled_items)} items restored).")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if not (getattr(args, "cloud", False) or getattr(args, "live", False)):
        return cmd_local_status(args)
    service, user_id = create_service(args)
    data_root = args.data_root.expanduser().resolve()

    report = service.status(user_id, data_root)
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print(f"=== Firestore Sync Status (User: {user_id}) ===")
    print(f"Project ID: {service.repository.project_id}")
    print(f"Data Root:  {data_root}")
    print(f"\nCurriculum: {'SYNCED' if report.curriculum_synced else 'OUT OF SYNC'}")
    print(f"Profiles:   {'SYNCED' if report.profiles_synced else 'OUT OF SYNC'}")
    print(f"Applications: {report.local_apps_count} local, {report.remote_apps_count} in cloud")

    if report.pending_push:
        print("\nPending push to cloud:")
        for item in report.pending_push:
            print(f"  + {item}")

    if report.pending_pull:
        print("\nPending pull from cloud:")
        for item in report.pending_pull:
            print(f"  - {item}")

    if not report.pending_push and not report.pending_pull:
        print("\nAll local and cloud states are fully in sync.")

    return 0


def cmd_local_status(args: argparse.Namespace) -> int:
    """Report local artifact state without contacting Firestore."""
    data_root = args.data_root.expanduser().resolve()
    sources = data_root / "sources"
    profiles = data_root / "master-curriculum" / "profiles"
    applications = data_root / "applications"
    source_count = len(list(sources.glob("*.md"))) if sources.is_dir() else 0
    profile_ready = (profiles / "current.json").is_file()
    app_count = sum(1 for path in applications.rglob("current.json")) if applications.is_dir() else 0
    report = {
        "mode": "local_notion",
        "data_root": str(data_root),
        "source_markdown_files": source_count,
        "profiles_ready": profile_ready,
        "applications": app_count,
        "notion": "use the connected Notion MCP for status and workflow control",
    }
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print("=== Local + Notion Status ===")
        print(f"Data Root: {data_root}")
        print(f"Candidate source files: {source_count}")
        print(f"Profiles: {'READY' if profile_ready else 'NOT INITIALIZED'}")
        print(f"Applications: {app_count}")
        print("Notion: human-facing status authority (use the connected Notion MCP)")
        print("Firestore: disabled by default (use --cloud for explicit sync)")
    return 0


def cmd_worker_notion(args: argparse.Namespace) -> int:
    from job_application_agents.plugins.notion import DEFAULT_DATABASE_ID, NotionPlugin
    from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
    from job_application_agents.plugins.notion.worker import NotionWorker

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("Error: NOTION_TOKEN environment variable is required to run Notion worker.", file=sys.stderr)
        return 1

    if getattr(args, "live", False):
        if not (args.firebase_project_id or os.environ.get("JAA_FIREBASE_PROJECT_ID")):
            print("Error: --live requires --firebase-project-id or JAA_FIREBASE_PROJECT_ID", file=sys.stderr)
            return 2
        os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
    elif getattr(args, "cloud", False):
        os.environ.setdefault("JAA_FIREBASE_PROJECT_ID", "demo-job-application-agents")
        os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    else:
        print("Error: worker-notion is cloud functionality; pass --cloud or --live", file=sys.stderr)
        return 2

    project_id = args.firebase_project_id or firebase_project_id()
    db_id = args.database_id or os.environ.get("NOTION_DATABASE_ID") or DEFAULT_DATABASE_ID

    repo = FirestoreNotionJobRepository(project_id=project_id)
    plugin = NotionPlugin(token=token, database_id=db_id)
    worker = NotionWorker(repository=repo, plugin=plugin)
    print(f"Starting NotionWorker [{worker.worker_id}] (Target DB: {db_id}, Firebase: {project_id})...")
    return worker.run(once=args.once)



def cmd_test_notion_api(args: argparse.Namespace) -> int:
    from job_application_agents.plugins.notion import DEFAULT_DATABASE_ID
    from job_application_agents.plugins.notion.client import NotionClient
    from job_application_agents.plugins.notion.models import NotionCardPayload

    token = args.token or os.environ.get("NOTION_TOKEN")
    if not token:
        print("Error: NOTION_TOKEN is required. Pass --token or set NOTION_TOKEN.", file=sys.stderr)
        return 1

    db_id = args.database_id or os.environ.get("NOTION_DATABASE_ID") or DEFAULT_DATABASE_ID
    print(f"Testing Notion API with target database: {db_id}...")

    client = NotionClient(token=token)

    # 1. Auth check
    try:
        user_info = client._request("GET", "users/me")
        bot_name = user_info.get("name", "Unknown Bot")
        ws_name = (user_info.get("bot") or {}).get("workspace_name", "Unknown Workspace")
        print(f"OK [1/5] Authenticated as bot '{bot_name}' in workspace '{ws_name}'")
    except Exception as exc:
        print(f"FAIL [1/5] Authentication failed: {exc}", file=sys.stderr)
        return 1

    # 2. Upload test PDF
    try:
        dummy_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000053 00000 n \n0000000102 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF"
        file_id = client.upload_file("test-resume.pdf", "application/pdf", dummy_pdf)
        print(f"OK [2/5] 2-Step file upload successful (File ID: {file_id})")
    except Exception as exc:
        print(f"FAIL [2/5] File upload failed: {exc}", file=sys.stderr)
        return 1

    # 3. Create test card
    page_id = None
    try:
        payload = NotionCardPayload(
            application_title="[TEST] JAA Worker Probe Card",
            company="JAA Automated Test",
            role="Worker Probe",
            status="TO_APPLY",
            current_version="v001",
            job_summary_text="Temporary diagnostic probe verifying Notion worker functionality.",
            requirements_text="Automated testing verification.",
            match_analysis_text="Diagnostic probe passed initial checks.",
            gaps_text="None",
        )
        page = client.create_card(
            database_id=db_id,
            payload=payload,
            resume_file_id=file_id,
        )
        page_id = page.get("id")
        page_url = page.get("url")
        print(f"OK [3/5] Card creation successful (Page ID: {page_id}, URL: {page_url})")
    except Exception as exc:
        print(f"FAIL [3/5] Card creation failed: {exc}", file=sys.stderr)
        return 1

    # 4. Update document blocks
    try:
        client.update_card_documents(
            page_id=page_id,
            version="v002-probe",
            resume_file_id=file_id,
        )
        print("OK [4/5] Document replacement on card successful")
    except Exception as exc:
        print(f"FAIL [4/5] Document replacement failed: {exc}", file=sys.stderr)
        return 1

    # 5. Archive (delete) test card
    try:
        client.archive_card(page_id=page_id)
        print(f"OK [5/5] Test card cleanup / archiving successful (Archived: {page_id})")
    except Exception as exc:
        print(f"FAIL [5/5] Card cleanup failed: {exc}", file=sys.stderr)
        return 1

    print("\nAll 5 Notion API operations (Auth, Upload, Create, Update, Delete) verified successfully!")
    return 0


def cmd_set_notion_db(args: argparse.Namespace) -> int:
    try:
        service, user_id = create_service(args)
    except RuntimeError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 2
    db_id = args.database_id
    if not db_id:
        print("Error: --database-id is required.", file=sys.stderr)
        return 1

    service.repository.set_user_notion_config(user_id, db_id, enabled=True)
    print(f"OK Saved Notion database configuration for user '{user_id}':")
    print(f"   Database ID: {db_id}")
    print(f"   Firestore Project: {service.repository.project_id}")
    return 0


def resolve_default_data_root() -> Path:
    env_root = os.environ.get("JAA_DATA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    configured_root = load_storage_config().data_root
    if configured_root is not None:
        return configured_root
    local_root = Path("job-search")
    if local_root.is_dir():
        return local_root.resolve()
    return (Path.home() / "Documents" / "job-search").resolve()


def main() -> int:
    default_data_root = resolve_default_data_root()
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--user-id", help="Explicit user ID (default resolved from env/config)")
    common_parser.add_argument("--data-root", type=Path, default=default_data_root)
    common_parser.add_argument("--firebase-project-id", help="Firebase project ID")
    common_parser.add_argument("--cloud", action="store_true", help="Opt into Firestore-backed synchronization")
    common_parser.add_argument("--live", action="store_true", help="Connect to live Firebase (implies --cloud)")


    parser = argparse.ArgumentParser(description=__doc__, parents=[common_parser])
    subparsers = parser.add_subparsers(dest="command", required=True)

    # push
    p_push = subparsers.add_parser("push", help="Push local data to Firestore", parents=[common_parser])
    p_push.add_argument("--all", action="store_true", help="Push curriculum, profiles, and all applications")
    p_push.add_argument("--curriculum", action="store_true", help="Push master curriculum only")
    p_push.add_argument("--profiles", action="store_true", help="Push role profiles only")
    p_push.add_argument("--applications", action="store_true", help="Push applications only")
    p_push.add_argument("--app-dir", type=Path, help="Push specific application directory")

    # pull
    p_pull = subparsers.add_parser("pull", help="Pull cloud data from Firestore to local files", parents=[common_parser])
    p_pull.add_argument("--all", action="store_true", help="Pull curriculum, profiles, and applications")
    p_pull.add_argument("--curriculum", action="store_true", help="Pull master curriculum only")
    p_pull.add_argument("--profiles", action="store_true", help="Pull role profiles only")
    p_pull.add_argument("--applications", action="store_true", help="Pull applications only")

    # status
    p_status = subparsers.add_parser("status", help="Check sync status and drift", parents=[common_parser])
    p_status.add_argument("--json", action="store_true", help="Output status as JSON")

    # set-notion-db
    p_set_db = subparsers.add_parser("set-notion-db", help="Link your private Notion database ID to a cloud profile", parents=[common_parser])
    p_set_db.add_argument("--database-id", required=True, help="Your private Notion Database ID")

    # worker-notion
    p_worker = subparsers.add_parser("worker-notion", help="Run background Notion sync worker daemon", parents=[common_parser])
    p_worker.add_argument("--once", action="store_true", help="Process one job and exit")
    p_worker.add_argument("--database-id", help="Target Notion Database ID")

    # test-notion-api
    p_test_notion = subparsers.add_parser("test-notion-api", help="Test live Notion API connection, file uploads, and card CRUD")
    p_test_notion.add_argument("--token", help="Notion integration token")
    p_test_notion.add_argument("--database-id", help="Target Notion Database ID")

    args = parser.parse_args()

    commands = {
        "push": cmd_push,
        "pull": cmd_pull,
        "status": cmd_status,
        "set-notion-db": cmd_set_notion_db,
        "worker-notion": cmd_worker_notion,
        "test-notion-api": cmd_test_notion_api,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
