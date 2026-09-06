from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.auto_apply.matcher import JobMatchScorer
from job_application_agents.plugins.notion.client import NotionClient
from job_application_agents.plugins.notion.models import NotionCardPayload
from job_application_agents.auto_apply.firestore import FirestoreDraftRepository


TOKEN = os.environ.get("NOTION_TOKEN")
DB_ID = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"
USER_ID = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur_apps_googleusercontent_com"


def find_app_dirs(base_dir: Path) -> dict[str, Path]:
    """Index local applications by company / role keywords and job URL."""
    apps = {}
    if not base_dir.is_dir():
        return apps
    for p in base_dir.glob("*/*/*"):
        if p.is_dir() and (p / "current.json").is_file():
            apps[p.name] = p
    return apps


def normalize_str(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def reconcile():
    if not TOKEN:
        raise RuntimeError("NOTION_TOKEN environment variable is required")
    client = NotionClient(token=TOKEN)
    client.ensure_database_properties(DB_ID)
    repo = FirestoreDraftRepository(project_id="tinder-jobs-4bf1b")
    base_dir = Path("job-search/applications")
    local_apps = find_app_dirs(base_dir)

    print("==================================================================")
    print("🔄 RECONCILING NOTION BOARD & CLOUD FIRESTORE WITH SOURCE OF TRUTH")
    print("==================================================================")

    # 1. Fetch all cards from Notion
    res = client._request("POST", f"databases/{DB_ID}/query", data={"page_size": 100})
    raw_cards = res.get("results", [])
    print(f"Total cards retrieved from Notion: {len(raw_cards)}\n")

    # Separate cards by created_time (Old canonical cards were created ~2026-08-25)
    # Group cards by normalized company+role or job_url
    grouped: dict[str, list[dict]] = {}
    for c in raw_cards:
        props = c.get("properties", {})
        title_prop = props.get("Application") or props.get("Name") or {}
        title = "".join(t.get("plain_text", "") for t in title_prop.get("title", []))
        company = "".join(t.get("plain_text", "") for t in props.get("Company", {}).get("rich_text", []))
        role = "".join(t.get("plain_text", "") for t in props.get("Role", {}).get("rich_text", []))
        job_url = props.get("Job URL", {}).get("url") or ""

        # Deduplication key
        norm_key = normalize_str(f"{company}_{role}") if (company and role) else normalize_str(title)
        if not norm_key:
            norm_key = normalize_str(job_url) if job_url else c.get("id")

        grouped.setdefault(norm_key, []).append(c)

    print(f"Grouped into {len(grouped)} distinct application entities.")

    for key, cards in grouped.items():
        # Sort cards: oldest first (canonical), newest last (duplicates)
        cards.sort(key=lambda x: x.get("created_time", ""))
        canonical_card = cards[0]
        duplicate_cards = cards[1:]

        # Extract truth properties from canonical card
        c_props = canonical_card.get("properties", {})
        title_prop = c_props.get("Application") or c_props.get("Name") or {}
        title = "".join(t.get("plain_text", "") for t in title_prop.get("title", []))
        company = "".join(t.get("plain_text", "") for t in c_props.get("Company", {}).get("rich_text", []))
        role = "".join(t.get("plain_text", "") for t in c_props.get("Role", {}).get("rich_text", []))

        status_prop = c_props.get("Status") or {}
        status = status_prop.get("select", {}).get("name") if status_prop.get("type") == "select" else status_prop.get("status", {}).get("name")
        if not status:
            status = "TO_APPLY"

        job_url = c_props.get("Job URL", {}).get("url") or ""
        source_url = c_props.get("Source URL", {}).get("url") or ""
        application_url = c_props.get("Application URL", {}).get("url") or job_url
        source_job_id = "".join(t.get("plain_text", "") for t in c_props.get("Source Job ID", {}).get("rich_text", []))
        version = "".join(t.get("plain_text", "") for t in c_props.get("Current Version", {}).get("rich_text", [])) or "v001"
        applied_at = c_props.get("Applied At", {}).get("date", {}).get("start") if c_props.get("Applied At", {}).get("date") else None
        generated_at = c_props.get("Generated At", {}).get("date", {}).get("start") if c_props.get("Generated At", {}).get("date") else None
        next_action_at = c_props.get("Next Action At", {}).get("date", {}).get("start") if c_props.get("Next Action At", {}).get("date") else None
        notes = "".join(t.get("plain_text", "") for t in c_props.get("Notes", {}).get("rich_text", []))
        location = "".join(t.get("plain_text", "") for t in c_props.get("Location", {}).get("rich_text", []))
        work_model = c_props.get("Work Model", {}).get("select", {}).get("name") or "Unspecified"
        source = c_props.get("Source", {}).get("select", {}).get("name") or "Other ATS"

        # Locate corresponding local bundle directory
        matched_dir: Path | None = None
        for app_id, app_path in local_apps.items():
            if source_job_id and source_job_id in app_id:
                matched_dir = app_path
                break
            if normalize_str(app_path.parent.name) in normalize_str(role) and normalize_str(app_path.parent.parent.name) in normalize_str(company):
                matched_dir = app_path
                break

        # Fallback search by company
        if not matched_dir:
            for app_id, app_path in local_apps.items():
                if normalize_str(app_path.parent.parent.name) in normalize_str(company) or normalize_str(company) in normalize_str(app_path.parent.parent.name):
                    matched_dir = app_path
                    break

        v_dir: Path | None = None
        job_data = {}
        if matched_dir:
            # Check if requested version exists, else latest
            if (matched_dir / version).is_dir():
                v_dir = matched_dir / version
            else:
                versions = sorted([d for d in matched_dir.iterdir() if d.is_dir() and re.match(r"^v\d+$", d.name)])
                if versions:
                    v_dir = versions[-1]
                    version = v_dir.name

            if v_dir and (v_dir / "job.json").is_file():
                with open(v_dir / "job.json", "r", encoding="utf-8") as f:
                    job_data = json.load(f)

        # Compute 100-Point Match Score
        if not job_data:
            job_data = {
                "company": company,
                "role": role,
                "location": location,
                "work_model": work_model,
                "url": job_url,
            }

        scorer_result = JobMatchScorer.score_job(job_data)
        match_score = scorer_result.total_score
        match_breakdown = scorer_result.to_dict()

        print(f"👉 Application: {title}")
        print(f"   Status:      {status}")
        print(f"   Version:     {version}")
        print(f"   Score:       {match_score} / 100 ({scorer_result.rating})")
        print(f"   Notion ID:   {canonical_card.get('id')}")

        # 2. Archive duplicates
        for dup in duplicate_cards:
            dup_id = dup.get("id")
            print(f"   🗑️  Archiving duplicate card: {dup_id}")
            client.archive_card(dup_id)

        # 3. Upload documents for canonical card
        resume_fid = None
        letter_fid = None
        zip_fid = None
        screenshot_fid = None

        if v_dir:
            r_pdf = v_dir / "resume.pdf"
            if r_pdf.is_file():
                resume_fid = client.upload_file(f"{company.lower()}-resume-{version}.pdf", "application/pdf", r_pdf.read_bytes())

            m_pdf = v_dir / "motivation-letter.pdf"
            if m_pdf.is_file():
                letter_fid = client.upload_file(f"{company.lower()}-letter-{version}.pdf", "application/pdf", m_pdf.read_bytes())

            for s_name in ("submission-success.png", "apply-preview.png", "test_pre_submit.png", "pre-submit.png"):
                s_file = v_dir / s_name
                if s_file.is_file():
                    screenshot_fid = client.upload_file(f"{company.lower()}-screenshot-{version}.png", "image/png", s_file.read_bytes())
                    break

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in sorted(v_dir.iterdir()):
                    if item.is_file() and item.suffix in (".tex", ".cls", ".md", ".json", ".jpg", ".png") and not item.name.endswith(".zip"):
                        zf.write(item, arcname=item.name)
            zip_bytes = zip_buf.getvalue()
            if zip_bytes:
                zip_fid = client.upload_file(f"{company.lower()}-{version}-sources.zip", "application/zip", zip_bytes)

        # 4. Update canonical card in Notion
        payload = NotionCardPayload(
            application_title=title,
            company=company,
            role=role,
            status=status,
            location=location,
            work_model=work_model,
            source=source,
            job_url=job_data.get("application_url") or application_url or job_url,
            source_url=job_data.get("source_url") or source_url or None,
            application_url=job_data.get("application_url") or application_url or job_url or None,
            source_job_id=source_job_id,
            current_version=version,
            generated_at=generated_at,
            applied_at=applied_at,
            next_action_at=next_action_at,
            local_bundle_path=str(matched_dir.resolve()) if matched_dir else None,
            match_summary=scorer_result.rating,
            match_score=match_score,
            match_breakdown=match_breakdown,
            notes=notes,
            job_summary_text=job_data.get("summary", ""),
            requirements_text="\n".join(job_data.get("requirements", [])) if isinstance(job_data.get("requirements"), list) else "",
            match_analysis_text=scorer_result.analysis,
        )

        client.update_card_properties(canonical_card.get("id"), payload)
        client.update_card_documents(
            page_id=canonical_card.get("id"),
            version=version,
            resume_file_id=resume_fid,
            letter_file_id=letter_fid,
            zip_file_id=zip_fid,
            zip_filename=f"{company.lower()}-{version}-sources.zip",
            screenshot_file_id=screenshot_fid,
        )
        print("   ✅ Notion card updated with truth status, documents & score.")

        # 5. Sync to Cloud Firestore
        app_doc_id = source_job_id or (matched_dir.name if matched_dir else normalize_str(title))
        app_ref = repo.client.collection("users").document(USER_ID).collection("applications").document(app_doc_id)
        app_ref.set(
            {
                "id": app_doc_id,
                "title": title,
                "company": company,
                "role": role,
                "status": status,
                "current_version": version,
                "applied_at": applied_at,
                "generated_at": generated_at,
                "next_action_at": next_action_at,
                "notion_page_id": canonical_card.get("id"),
                "notion_url": canonical_card.get("url"),
                "match_score": match_score,
                "match_breakdown": match_breakdown,
                "local_path": str(matched_dir.resolve()) if matched_dir else None,
                "job": {
                    "company": company,
                    "role": role,
                    "location": location,
                    "work_model": work_model,
                    "url": job_url,
                    "summary": job_data.get("summary", ""),
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            merge=True,
        )
        print(f"   🔥 Firestore synced: applications/{app_doc_id}")

        # 6. Update local current.json if matched
        if matched_dir and (matched_dir / "current.json").is_file():
            try:
                with open(matched_dir / "current.json", "r", encoding="utf-8") as f:
                    cm = json.load(f)
                cm["status"] = status
                cm["match_score"] = match_score
                cm["match_breakdown"] = match_breakdown
                cm["notion_page_id"] = canonical_card.get("id")
                if applied_at:
                    cm["applied_at"] = applied_at
                with open(matched_dir / "current.json", "w", encoding="utf-8") as f:
                    json.dump(cm, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        print("-" * 60)

    print("\n==================================================================")
    print("🎉 FULL RECONCILIATION COMPLETE: NOTION & FIRESTORE ARE IN SYNC!")
    print(f"View Notion: https://app.notion.com/p/{DB_ID.replace('-', '')}")
    print("==================================================================")


if __name__ == "__main__":
    reconcile()
