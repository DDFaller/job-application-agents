from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if __name__ == "__main__" and VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.plugins.notion.firestore import FirestoreNotionJobRepository
from job_application_agents.sync.firestore import FirestoreUserSyncRepository
from job_application_agents.sync.models import ApplicationSyncSnapshot, ApplicationVersionSnapshot

PROJECT_ID = "tinder-jobs-4bf1b"
USER_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur_apps_googleusercontent_com"
DB_ID = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")


def main():
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN environment variable is required")
    print(f"=== END-TO-END FLOW TEST: Cohere Mock Application ===")
    print(f"Firestore Project: {PROJECT_ID}")
    print(f"User ID:           {USER_ID}")
    print(f"Target Notion DB:  {DB_ID}\n")

    sync_repo = FirestoreUserSyncRepository(project_id=PROJECT_ID)
    job_repo = FirestoreNotionJobRepository(project_id=PROJECT_ID)

    app_id = "cohere__principal-ml-infra__mock-2026"
    version_id = "v001"
    now_iso = sync_repo._now_iso()

    # Step 1: Write application document and version subcollection in Firestore
    print("[1/4] Writing new application to Firestore...")
    version_snap = ApplicationVersionSnapshot(
        version=version_id,
        generated_at=now_iso,
        manifest={"version": version_id, "title": "Cohere ML Infra Application"},
        bundle={"version": version_id, "company": "Cohere"},
        job={
            "company": "Cohere",
            "role": "Principal ML Infrastructure Engineer",
            "location": "Toronto / London / Remote",
            "work_model": "Remote",
            "source": "Company Website",
            "url": "https://cohere.com/careers/principal-ml-infra-2026",
            "job_id": "cohere-infra-2026",
            "summary": "Design high-performance distributed serving pipelines and kernel optimizations for LLMs.",
            "requirements": [
                "Expertise in distributed LLM inference and serving frameworks (vLLM, TensorRT-LLM, Triton)",
                "High proficiency in Python, C++, and CUDA kernel tuning",
                "Proven track record scaling multi-region production AI systems",
            ],
        },
        sources={
            "resume.tex": "\\documentclass{article}\n\\begin{document}\nCohere Principal ML Infrastructure Resume\n\\end{document}",
            "letter.tex": "\\documentclass{article}\n\\begin{document}\nMotivation Letter for Cohere\n\\end{document}",
            "match-analysis.md": "Exceptional fit for distributed serving architecture, latency profiling, and kernel acceleration.",
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
        company="Cohere",
        company_slug="cohere",
        role="Principal ML Infrastructure Engineer",
        role_slug="principal-ml-infra",
        job_id_or_hash="cohere-infra-2026",
        status="APPLIED",
        current_version=version_id,
        canonical_url="https://cohere.com/careers/principal-ml-infra-2026",
        match_summary="High-scoring match for large-scale model inference, async servers, and distributed runtime acceleration.",
        selected_profile="ml-infrastructure-engineer",
        gaps=[],
        generated_at=now_iso,
        updated_at=now_iso,
        versions={version_id: version_snap},
    )

    sync_repo.save_application(USER_ID, app_snap)
    print(f" -> OK Application saved under /users/{USER_ID}/applications/{app_id}")

    # Step 2: Enqueue sync job in Firestore notionJobs queue
    print("\n[2/4] Enqueuing sync job to Firestore 'notionJobs' queue...")
    payload = {
        "current_version": version_id,
        "notion_database_id": DB_ID,
        "title": "Cohere - Principal ML Infrastructure Engineer",
        "job": {
            "company": "Cohere",
            "role": "Principal ML Infrastructure Engineer",
            "location": "Toronto / London / Remote",
            "work_model": "Remote",
            "source": "Company Website",
            "url": "https://cohere.com/careers/principal-ml-infra-2026",
            "job_id": "cohere-infra-2026",
            "summary": "Design high-performance distributed serving pipelines and kernel optimizations for LLMs.",
            "requirements": [
                "Expertise in distributed LLM inference and serving frameworks (vLLM, TensorRT-LLM, Triton)",
                "High proficiency in Python, C++, and CUDA kernel tuning",
                "Proven track record scaling multi-region production AI systems",
            ],
        },
        "match": {
            "summary": "High-scoring match for large-scale model inference, async servers, and distributed runtime acceleration.",
            "analysis": "Proven expertise in building low-latency inference services and managing high-throughput distributed systems.",
            "gaps": ["None identified"],
        },
    }

    job = job_repo.enqueue(
        user_id=USER_ID,
        application_id=app_id,
        action="CREATE_OR_UPDATE",
        payload=payload,
    )
    print(f" -> OK Enqueued Job ID: {job.id} (State: {job.state})")

    # Step 3: Trigger Notion Worker to process the queue
    print("\n[3/4] Running NotionWorker against live Firestore queue...")
    worker_cmd = [
        str(VENV_PYTHON),
        "scripts/sync.py",
        "worker-notion",
        "--once",
        "--live",
    ]
    env = os.environ.copy()
    env["NOTION_TOKEN"] = NOTION_TOKEN
    proc = subprocess.run(worker_cmd, env=env, capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print("Worker error:", proc.stderr)
        return 1

    # Step 4: Verify Firestore application document decoration & Notion Card
    print("[4/4] Verifying completed sync...")
    updated_job = job_repo.get(job.id)
    if not updated_job:
        print("Error: Job disappeared from queue")
        return 1

    print(f" -> Queue Job State: {updated_job.state}")
    print(f" -> Queue Job Result: {json.dumps(updated_job.result, indent=2)}")

    updated_app = sync_repo.fetch_application(USER_ID, app_id)
    if updated_app:
        print(f"\nFirestore Application Record Updated:")
        print(f" - Notion Page ID:  {updated_app.notion_page_id}")
        print(f" - Notion Page URL: {updated_app.notion_page_url}")
        print(f" - Stored Documents: {list(updated_app.documents.keys())}")

    print("\n=== SUCCESS: End-to-End Flow Verified ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
