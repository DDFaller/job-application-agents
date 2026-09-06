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
from job_application_agents.auto_apply.matcher import JobMatchScorer

USER_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur_apps_googleusercontent_com"


def seed_top_drafts():
    repo = FirestoreDraftRepository(project_id="tinder-jobs-4bf1b")
    base_dir = Path("job-search/applications")

    print("==================================================================")
    print("🌱 SEEDING STRUCTURED DRAFTS FOR TOP 5 APPLICATIONS IN FIRESTORE")
    print("==================================================================")

    # Candidate default facts
    default_fields = [
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


    # Fetch top TO_APPLY jobs from Firestore
    apps_ref = repo.client.collection("users").document(USER_ID).collection("applications")
    docs = list(apps_ref.stream())

    to_apply = [d.to_dict() for d in docs if d.to_dict().get("status") == "TO_APPLY"]
    to_apply.sort(key=lambda x: x.get("match_score") or 0, reverse=True)

    top_5 = to_apply[:5]
    print(f"Targeting Top {len(top_5)} applications:")

    for idx, app in enumerate(top_5, 1):
        app_id = app.get("id")
        company = app.get("company", "Company")
        role = app.get("role", "Software Engineer")
        match_score = app.get("match_score", 85)
        match_bd = app.get("match_breakdown", {})
        job_url = app.get("job", {}).get("url") or f"https://jobs.example.com/{app_id}"
        local_path = app.get("local_path")

        v_path = Path(local_path) if local_path else (base_dir / company.lower() / role.lower() / app_id / "v001")
        resume_pdf = v_path / "resume.pdf"
        letter_pdf = v_path / "motivation-letter.pdf"

        # Check for role-specific fields
        custom_fields = list(default_fields)
        if "gorgias" in company.lower():
            custom_fields.extend([
                ApplicationField(id="hybrid", label="Commit to 2 days/week Paris Office Hybrid", type=FieldType.SELECT, value="Yes", options=["Yes", "No"], source=FieldSource.PROFILE),
                ApplicationField(id="referral", label="Referral / How did you hear about us", type=FieldType.TEXT, value="Engineering Platform Lead", source=FieldSource.RESUME),
            ])
        elif "pigment" in company.lower():
            custom_fields.extend([
                ApplicationField(id="scale", label="Experience with high-throughput distributed systems", type=FieldType.TEXTAREA, value="Built Kafka & BigQuery distributed streaming pipelines at Back Market with Datadog observability.", source=FieldSource.RESUME),
                ApplicationField(id="notice_period", label="Notice Period / Availability", type=FieldType.TEXT, value="Immediately available", source=FieldSource.PROFILE),
            ])
        elif "hub" in company.lower():
            custom_fields.extend([
                ApplicationField(id="stage_fit", label="Why early-stage founding engineering?", type=FieldType.TEXTAREA, value="Experienced with full-cycle autonomous development, infrastructure ownership, and rapid product iteration.", source=FieldSource.RESUME),
            ])


        draft = ApplicationDraft(
            application_id=app_id,
            company=company,
            job_title=role,
            target_url=job_url,
            revision=1,
            fields=custom_fields,
            resume_path=str(resume_pdf.resolve()) if resume_pdf.is_file() else str(v_path / "resume.pdf"),
            letter_path=str(letter_pdf.resolve()) if letter_pdf.is_file() else None,
            match_score=match_score,
            match_breakdown=match_bd,
            state=ApplicationState.REVIEW_READY,
        )

        doc_path = repo.save_draft(user_id=USER_ID, draft=draft)
        print(f"[{idx}/5] Seeded Draft for {company} - {role} ({match_score}/100) -> {doc_path}")

    print("\n==================================================================")
    print("✅ TOP 5 DRAFTS SEEDED SUCCESSFULLY IN FIRESTORE")
    print("==================================================================")


if __name__ == "__main__":
    seed_top_drafts()
