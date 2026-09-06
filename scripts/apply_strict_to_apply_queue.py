from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.auto_apply.draft_models import ApplicationDraft, ApplicationField, ApplicationState, FieldSource, FieldType
from job_application_agents.auto_apply.firestore import FirestoreDraftRepository

USER_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur_apps_googleusercontent_com"

# The EXACT 4 designated TO_APPLY jobs
TO_APPLY_MAP = {
    "MINT_BS075ACB-121314": {
        "company": "DEPAFI",
        "role": "Concepteur-développeur d'applications",
        "match_score": 80,
        "job_url": "https://choisirleservicepublic.gouv.fr/offre-emploi/depafi-75-concepteur---developpeur-d-applications-conceptrice---developpeuse-d-applications-reference-MINT_BS075ACB-121314/",
        "local_path": "job-search/applications/depafi/concepteur-developpeur-applications/MINT_BS075ACB-121314/v003",
        "custom_fields": [
            ApplicationField(id="public_sector", label="Expérience dans le secteur public / ministères", type=FieldType.TEXT, value="Expérience avec projets gouvernementaux et conformité RGPD.", source=FieldSource.RESUME),
        ]
    },
    "dinum-fullstack-4148": {
        "company": "DINUM",
        "role": "Développeur Fullstack Python / Cloud",
        "match_score": 77,
        "job_url": "https://www.linkedin.com/jobs/view/dinum-fullstack-dev-4148",
        "local_path": "job-search/applications/dinum/ingenieur-applique-intelligence-artificielle/2026-2359818/v006",
        "custom_fields": [
            ApplicationField(id="python_stack", label="Stack Python / Cloud maîtrisé", type=FieldType.TEXT, value="Python, FastAPI, Docker, Kubernetes, GCP/Scaleway, PostgreSQL.", source=FieldSource.PROFILE),
        ]
    },
    "3f55aef6-c6ea-4781-95b1-94a5e54dc1dd": {
        "company": "micro1",
        "role": "GPU Programming Software Engineer",
        "match_score": 68,
        "job_url": "https://jobs.micro1.ai/post/3f55aef6-c6ea-4781-95b1-94a5e54dc1dd",
        "local_path": "job-search/applications/micro1/gpu-programming-software-engineer/3f55aef6-c6ea-4781-95b1-94a5e54dc1dd/v001",
        "custom_fields": [
            ApplicationField(id="gpu_experience", label="GPU & Parallel Computing Experience", type=FieldType.TEXTAREA, value="Experience profiling and optimizing LLM workloads and CUDA container environments.", source=FieldSource.RESUME),
        ]
    },
    "2761": {
        "company": "Tieto",
        "role": "Junior Software Engineer",
        "match_score": 63,
        "job_url": "https://careers.tieto.com/job/junior-software-engineer-tieto-caretech-m-f-d-in-espoo-finland-jid-2761?_atxsrc=AttraxLinkedin",
        "local_path": "job-search/applications/tieto/junior-software-engineer/2761/v001",
        "custom_fields": [
            ApplicationField(id="relocation", label="Willingness to work in Espoo / Remote EU", type=FieldType.SELECT, value="Yes", options=["Yes", "No"], source=FieldSource.PROFILE),
        ]
    },
}

APPLIED_COMPANIES = ["gorgias", "mistral", "crédit agricole", "credit agricole", "almedia", "waving", "prima", "ravogen", "international tech", "data engineer"]
REJECTED_COMPANIES = ["hugging face", "new grad"]


def run():
    repo = FirestoreDraftRepository(project_id="tinder-jobs-4bf1b")
    now_iso = datetime.now(timezone.utc).isoformat()
    apps_ref = repo.client.collection("users").document(USER_ID).collection("applications")

    print("==================================================================")
    print("🧹 CLEANING & STRICTLY SETTING TO_APPLY QUEUE IN FIRESTORE")
    print("==================================================================")

    # Clean every document in Firestore
    for doc in apps_ref.stream():
        app_id = doc.id
        d = doc.to_dict()
        company = (d.get("company") or "").lower()
        role = (d.get("role") or "").lower()
        title = (d.get("title") or "").lower()

        if app_id in TO_APPLY_MAP:
            continue

        # Determine non-TO_APPLY status
        if any(c in company or c in role or c in title for c in APPLIED_COMPANIES):
            target_status = "APPLIED"
        elif any(c in company or c in role or c in title for c in REJECTED_COMPANIES):
            target_status = "REJECTED"
        else:
            target_status = "DROPPED"

        apps_ref.document(app_id).update({
            "status": target_status,
            "updated_at": now_iso,
        })
        print(f" -> Marked non-TO_APPLY: {app_id} ({d.get('company')}) -> {target_status}")

    # Standard candidate fields
    base_fields = [
        ApplicationField(id="name", label="Full Name", type=FieldType.TEXT, value="Daniel Faller", source=FieldSource.PROFILE, required=True),
        ApplicationField(id="email", label="Email Address", type=FieldType.TEXT, value="danielmfaller@protonmail.com", source=FieldSource.PROFILE, required=True),
        ApplicationField(id="phone", label="Phone Number", type=FieldType.TEXT, value="+330750159011", source=FieldSource.PROFILE, required=True),
        ApplicationField(id="location", label="Location / City", type=FieldType.TEXT, value="Paris, France", source=FieldSource.PROFILE, required=True),
        ApplicationField(id="linkedin", label="LinkedIn Profile", type=FieldType.TEXT, value="https://www.linkedin.com/in/daniel-m-faller/?locale=en", source=FieldSource.PROFILE),
        ApplicationField(id="github", label="GitHub Profile", type=FieldType.TEXT, value="https://github.com/DDFaller", source=FieldSource.PROFILE),
        ApplicationField(id="portfolio", label="Portfolio / Website", type=FieldType.TEXT, value="https://ddfaller.github.io/Projects_index/", source=FieldSource.PROFILE),
        ApplicationField(id="auth", label="Legal Work Authorization (France / EU)", type=FieldType.SELECT, value="Yes", options=["Yes", "No"], source=FieldSource.PROFILE, required=True),
        ApplicationField(id="visa", label="Require Visa Sponsorship Now or in Future", type=FieldType.SELECT, value="No", options=["Yes", "No"], source=FieldSource.PROFILE, required=True),
    ]

    print("\n -> Seeding and activating the 4 TO_APPLY jobs...")
    for idx, (app_id, item) in enumerate(TO_APPLY_MAP.items(), 1):
        company = item["company"]
        role = item["role"]
        score = item["match_score"]
        job_url = item["job_url"]
        local_p = Path(item["local_path"])

        resume_path = local_p / "resume.pdf"
        letter_path = local_p / "motivation-letter.pdf"

        # Update application metadata
        apps_ref.document(app_id).set({
            "id": app_id,
            "company": company,
            "role": role,
            "title": f"{company} - {role}",
            "status": "TO_APPLY",
            "match_score": score,
            "active_draft_revision": 1,
            "local_path": str(local_p.resolve()) if local_p.is_dir() else None,
            "job": {
                "company": company,
                "role": role,
                "url": job_url,
            },
            "updated_at": now_iso,
        }, merge=True)

        # Build fields
        fields = list(base_fields) + item.get("custom_fields", [])

        draft = ApplicationDraft(
            application_id=app_id,
            company=company,
            job_title=role,
            target_url=job_url,
            revision=1,
            fields=fields,
            resume_path=str(resume_path.resolve()) if resume_path.is_file() else str(local_p / "resume.pdf"),
            letter_path=str(letter_path.resolve()) if letter_path.is_file() else None,
            match_score=score,
            state=ApplicationState.REVIEW_READY,
        )

        doc_path = repo.save_draft(user_id=USER_ID, draft=draft)
        print(f" [{idx}/4] ✅ TO_APPLY: {company} - {role} ({score}/100) -> {doc_path}")

    print("\n==================================================================")
    print("🎉 FIRESTORE STRICTLY CONTAINS EXACTLY 4 TO_APPLY JOBS")
    print("==================================================================")


if __name__ == "__main__":
    run()
