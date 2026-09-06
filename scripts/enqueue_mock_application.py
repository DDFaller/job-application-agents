from __future__ import annotations

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

from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
from job_application_agents.sync.firestore import FirestoreUserSyncRepository
from job_application_agents.sync.models import ApplicationSyncSnapshot, ApplicationVersionSnapshot

PROJECT_ID = os.environ.get("JAA_FIREBASE_PROJECT_ID", "tinder-jobs-4bf1b")
USER_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur_apps_googleusercontent_com"
DB_ID = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"


def main():
    print(f"Connecting to live Firestore project: {PROJECT_ID}")
    sync_repo = FirestoreUserSyncRepository(project_id=PROJECT_ID)
    job_repo = FirestoreNotionJobRepository(project_id=PROJECT_ID)

    app_id = "anthropic__staff-research-infra__mock-2026"
    version_id = "v001"
    now_iso = sync_repo._now_iso()

    # 1. Create Application Snapshot
    version_snap = ApplicationVersionSnapshot(
        version=version_id,
        generated_at=now_iso,
        manifest={"version": version_id, "title": "Anthropic Application"},
        bundle={"version": version_id, "company": "Anthropic"},
        job={
            "company": "Anthropic",
            "role": "Staff Research Infrastructure Engineer",
            "location": "San Francisco, CA (Hybrid / Remote)",
            "work_model": "Hybrid",
            "source": "Company Website",
            "url": "https://jobs.anthropic.com/staff-research-infrastructure-engineer",
            "job_id": "mock-2026",
            "summary": "Lead the design, deployment, and operation of ultra-scale GPU clusters for frontier AI training.",
            "requirements": [
                "10+ years experience building distributed systems infrastructure",
                "Deep experience with Kubernetes, Slurm, InfiniBand, and cloud GPU clusters",
                "Strong software engineering in Python, Go, or Rust",
            ],
        },
        sources={
            "resume.tex": "\\documentclass{article}\n\\begin{document}\nAnthropic Staff Research Infrastructure Resume\n\\end{document}",
            "letter.tex": "\\documentclass{article}\n\\begin{document}\nMotivation Letter for Anthropic\n\\end{document}",
            "match-analysis.md": "Exceptional fit for large-scale GPU training cluster automation.",
        },
        quality_gate={"status": "PASSED"},
        semantic_review={"status": "APPROVED"},
        document_text_sha256={},
        document_revision=1,
        source_provenance="local",
        artifacts={},
        documents={},
    )


    app_snap = ApplicationSyncSnapshot(
        application_id=app_id,
        company="Anthropic",
        company_slug="anthropic",
        role="Staff Research Infrastructure Engineer",
        role_slug="staff-research-infra",
        job_id_or_hash="mock-2026",
        status="TO_APPLY",
        current_version=version_id,
        canonical_url="https://jobs.anthropic.com/staff-research-infrastructure-engineer",
        match_summary="High-priority application for AI training infrastructure and distributed systems scaling.",
        selected_profile="ai-infrastructure-engineer",
        gaps=[],
        generated_at=now_iso,
        updated_at=now_iso,
        versions={version_id: version_snap},
    )

    print(f"\nStep 1: Saving mock application to Firestore (/users/{USER_ID}/applications/{app_id})...")
    sync_repo.save_application(USER_ID, app_snap)
    print(" -> OK Application saved to Firestore!")

    # 2. Enqueue Job to notionJobs Queue
    print(f"\nStep 2: Enqueuing sync job to Firestore 'notionJobs' collection...")
    payload = {
        "current_version": version_id,
        "notion_database_id": DB_ID,
        "title": "Anthropic - Staff Research Infrastructure Engineer",
        "job": {
            "company": "Anthropic",
            "role": "Staff Research Infrastructure Engineer",
            "location": "San Francisco, CA (Hybrid / Remote)",
            "work_model": "Hybrid",
            "source": "Company Website",
            "url": "https://jobs.anthropic.com/staff-research-infrastructure-engineer",
            "job_id": "mock-2026",
            "summary": "Lead the design, deployment, and operation of ultra-scale GPU clusters for frontier AI training.",
            "requirements": [
                "10+ years experience building distributed systems infrastructure",
                "Deep experience with Kubernetes, Slurm, InfiniBand, and cloud GPU clusters",
                "Strong software engineering in Python, Go, or Rust",
            ],
        },
        "match": {
            "summary": "Exceptional fit for large-scale GPU training cluster automation and high-throughput model training infrastructure.",
            "analysis": "Proven capability in building scalable distributed systems, async services, and containerized workflows.",
            "gaps": ["None identified"],
        },
    }

    job = job_repo.enqueue(
        user_id=USER_ID,
        application_id=app_id,
        action="CREATE_OR_UPDATE",
        payload=payload,
    )
    print(f" -> OK Job Enqueued! ID: {job.id} | State: {job.state}")

    # 3. Supervise Process (Polling Firestore State)
    print("\nStep 3: Supervising Cloud Worker (Monitoring Firestore 'notionJobs' state)...")
    print("NOTE: Running in pure supervisor mode — NO local worker will be executed.\n")

    for attempt in range(1, 13):
        time.sleep(5)
        current_job = job_repo.get(job.id)
        if not current_job:
            print(f"[{attempt * 5}s] Job not found in queue.")
            continue

        state = current_job.state
        leased_by = current_job.leased_by
        print(f"[{attempt * 5}s] Job State: {state} | Leased By: {leased_by or 'None'}")

        if state == "SUCCEEDED":
            print("\nSUCCESS! Cloud worker has processed the job:")
            print(json.dumps(current_job.result, indent=2))

            # Check application in Firestore
            updated_app = sync_repo.fetch_application(USER_ID, app_id)
            if updated_app:
                print(f"Notion Page ID: {updated_app.notion_page_id}")
                print(f"Notion Page URL: {updated_app.notion_page_url}")
            return 0
        elif state == "FAILED":
            print(f"\nFAIL: Cloud worker marked job as FAILED: {current_job.error_detail}")
            return 1

    print("\nSupervisor timeout (60s): Job is currently still in state:", state)
    print("If your cloud worker is deployed on Cloud Run/GCP, it will process the job when triggered.")
    return 0


if __name__ == "__main__":
    main()
