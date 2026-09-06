#!/usr/bin/env python3
"""Publish draft to Cloud Firestore and test cloud queue submission flow."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from google.cloud import firestore
from job_application_agents.auto_apply.draft_models import (
    ApplicationDraft,
    ApplicationField,
    ApprovalToken,
    FieldSource,
    FieldType,
)
from job_application_agents.auto_apply.firestore import FirestoreDraftRepository
from job_application_agents.auto_apply.service import AutoApplyService

USER_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur_apps_googleusercontent_com"
APP_ID = "gorgias-ai-infra"


def main() -> int:
    print("==================================================================")
    print("🚀 PUBLISHING LIVE DRAFT TO CLOUD FIRESTORE")
    print("==================================================================")
    print(f"Project ID: tinder-jobs-4bf1b")
    print(f"User ID:    {USER_ID}")
    print(f"App ID:     {APP_ID}")
    print("==================================================================\n")

    app_dir = Path("job-search/applications/gorgias/software-engineer-internal-ai-platform/d8ebc41a-393c-4226-8c1b-e5070b943ddb")
    v_dir = app_dir / "v004"
    draft_file = v_dir / "draft.json"

    if not draft_file.is_file():
        print(f"Error: {draft_file} not found.", file=sys.stderr)
        return 1

    job_file = v_dir / "job.json"
    job_data = json.loads(job_file.read_text(encoding="utf-8")) if job_file.is_file() else {}

    from job_application_agents.auto_apply.matcher import JobMatchScorer
    scorer_result = JobMatchScorer.score_job(job_data)
    print(f" -> Computed Match Score: {scorer_result.total_score} / 100 ({scorer_result.rating})")

    draft = ApplicationDraft.from_dict(json.loads(draft_file.read_text(encoding="utf-8")))
    draft.application_id = APP_ID
    draft.match_score = scorer_result.total_score
    draft.match_breakdown = scorer_result.to_dict()

    repo = FirestoreDraftRepository(project_id="tinder-jobs-4bf1b")

    # 1. Save draft to Firestore
    print("[1/3] Uploading ApplicationDraft (Rev 1) with Match Score to Firestore...")
    doc_path = repo.save_draft(user_id=USER_ID, draft=draft)
    print(f" -> Draft stored at: {doc_path}")
    print(f" -> Draft Hash:      {draft.draft_hash}")

    # 2. Update Application metadata
    app_ref = repo.client.collection("users").document(USER_ID).collection("applications").document(APP_ID)
    app_ref.set(
        {
            "id": APP_ID,
            "title": "Gorgias - Software Engineer - Internal AI Platform",
            "company": "Gorgias",
            "role": "Software Engineer - Internal AI Platform",
            "status": "TO_APPLY",
            "active_draft_revision": draft.revision,
            "active_draft_hash": draft.draft_hash,
            "match_score": scorer_result.total_score,
            "match_breakdown": scorer_result.to_dict(),
            "local_path": str(v_dir.resolve()),
            "job": {
                "company": "Gorgias",
                "role": "Software Engineer - Internal AI Platform",
                "url": draft.target_url,
                "summary": "Building internal AI platforms and agents for Gorgias customer service ecosystem.",
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        merge=True,
    )
    print(" -> Application metadata synced with Match Score successfully.")


    print("\n[2/3] Checking Mobile Review PWA Status...")
    print(" -> Mobile PWA URL: https://tinder-jobs-4bf1b.web.app")
    print(" -> Open this URL on your mobile phone or browser to see the live synced draft!")

    # 3. Simulate Enqueueing Approval Token to test Worker Execution
    if "--enqueue-approval" in sys.argv:
        print("\n[3/3] Enqueueing Approval Token & Submission Job...")
        token = ApprovalToken(
            application_id=APP_ID,
            revision=draft.revision,
            draft_hash=draft.draft_hash,
        )
        repo.save_approval_token(user_id=USER_ID, token=token)
        job_id = repo.enqueue_submission_job(user_id=USER_ID, application_id=APP_ID, token=token)
        print(f" -> Enqueued submission job: {job_id}")
        print(" -> The running background worker should claim this job immediately!")

    print("\n==================================================================")
    print("✅ FIRESTORE DRAFT SEEDED SUCCESSFULLY")
    print("==================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
