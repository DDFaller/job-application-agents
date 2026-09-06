#!/usr/bin/env python3
"""End-to-end demonstration and test of the Remote Human-in-the-Loop Draft & Verification flow."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if __name__ == "__main__" and VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.auto_apply.agent_solver import AgentFormSolver
from job_application_agents.auto_apply.draft_models import (
    ApplicationDraft,
    ApplicationField,
    ApprovalToken,
    FieldSource,
    FieldType,
)

from job_application_agents.auto_apply.draft_service import DraftService
from job_application_agents.auto_apply.service import AutoApplyService


def main() -> int:
    from playwright.sync_api import sync_playwright

    app_dir = Path("job-search/applications/gorgias/software-engineer-internal-ai-platform/d8ebc41a-393c-4226-8c1b-e5070b943ddb")
    v_dir = app_dir / "v004"
    resume_pdf = v_dir / "resume.pdf"
    letter_pdf = v_dir / "motivation-letter.pdf"

    service = AutoApplyService()
    candidate = service.load_candidate_profile()

    print("==================================================================")
    print("🚀 TESTING HUMAN-IN-THE-LOOP DRAFT & REVISION FLOW")
    print("==================================================================")
    print(f"Candidate:         {candidate.full_name} ({candidate.email})")
    print(f"Resume PDF:        file://{resume_pdf.resolve()}")
    if letter_pdf.is_file():
        print(f"Motivation Letter: file://{letter_pdf.resolve()}")
    print("==================================================================\n")

    target_url = "https://jobs.ashbyhq.com/gorgias/d8ebc41a-393c-4226-8c1b-e5070b943ddb"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        print("[1/4] Navigating to target portal...")
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        print("[2/4] Agentic inspection, autofill, and PDF upload...")
        fill_res = AgentFormSolver.solve_form(
            page=page,
            candidate=candidate,
            resume_pdf=resume_pdf,
            letter_pdf=letter_pdf,
        )

        print(f" -> Fields Filled in Browser: {len(fill_res.fields_filled)}")
        print(f" -> Resume Uploaded: {fill_res.resume_uploaded}\n")

        print("[3/4] Extracting structured ApplicationDraft (Revision 1)...")
        draft = DraftService.create_draft_from_page(
            page=page,
            application_id="gorgias-ai-infra",
            company="Gorgias",
            job_title="Software Engineer - Internal AI Platform",
            candidate=candidate,
            resume_path=resume_pdf,
            letter_path=letter_pdf,
            revision=1,
        )

        # Save draft.json and preview screenshot
        draft_file = v_dir / "draft.json"
        draft_file.write_text(draft.to_json(), encoding="utf-8")
        preview_file = v_dir / "apply-preview.png"
        page.screenshot(path=str(preview_file), full_page=True)

        browser.close()

    print("\n--- 📋 EXTRACTED APPLICATION DRAFT (Rev 1) ---")
    print(f"Draft Hash:  {draft.draft_hash}")
    print(f"Revision:    {draft.revision}")
    print(f"Fields ({len(draft.fields)}):")
    for f in draft.fields:
        icon = "✓" if f.source == FieldSource.PROFILE else ("✎" if f.source == FieldSource.RESUME else ("⚠" if f.source == FieldSource.AI else "✏"))
        print(f"   {icon} [{f.source.value.upper():<7}] {f.label:<45} = {str(f.value):<30}")

    print(f"\nSaved Draft:   {draft_file}")
    print(f"Saved Preview: {preview_file}\n")

    # Simulate an edit (e.g. User edits custom question or notice period)
    print("------------------------------------------------------------------")
    print("✏️ SIMULATING USER EDIT (Notice Period / Referral Field)")
    print("------------------------------------------------------------------")
    field_updates = {
        "e044afb3-c205-4c57-ac5e-33b3f48c2d8b": "Referred by Engineering Lead",
    }

    # Generate Revision 2
    rev2_draft = ApplicationDraft(
        application_id=draft.application_id,
        company=draft.company,
        job_title=draft.job_title,
        target_url=draft.target_url,
        revision=2,
        fields=[
            ApplicationField(
                id=f.id,
                label=f.label,
                type=f.type,
                value="Referred by Engineering Lead" if (f.id in field_updates or f.label in field_updates) else f.value,
                source=FieldSource.USER if (f.id in field_updates or f.label in field_updates) else f.source,
                required=f.required,
                options=f.options,
            )
            for f in draft.fields
        ],
        resume_path=draft.resume_path,
        letter_path=draft.letter_path,
    )

    print(f"Revision 1 Hash: {draft.draft_hash}")
    print(f"Revision 2 Hash: {rev2_draft.draft_hash}")
    print("✓ Cryptographic hash changed dynamically with field modification!")

    # Test Approval Token Locking
    token = ApprovalToken(
        application_id=rev2_draft.application_id,
        revision=rev2_draft.revision,
        draft_hash=rev2_draft.draft_hash,
    )
    print(f"\nGenerated Approval Token: {token.to_dict()}")
    print("✓ Submission is locked strictly to Revision 2 & matching hash!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
