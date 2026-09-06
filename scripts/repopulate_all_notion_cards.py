from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.plugins.notion.client import NotionClient
from job_application_agents.plugins.notion.models import NotionCardPayload


TOKEN = os.environ.get("NOTION_TOKEN")
DB_ID = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"


def find_app_dirs(base_dir: Path) -> list[Path]:
    results: list[Path] = []
    if not base_dir.is_dir():
        return results
    for p in base_dir.glob("*/*/*"):
        if p.is_dir() and (p / "current.json").is_file():
            results.append(p)
    return sorted(results)


def populate_all():
    if not TOKEN:
        raise RuntimeError("NOTION_TOKEN environment variable is required")
    client = NotionClient(token=TOKEN)
    base_dir = Path("job-search/applications")
    app_dirs = find_app_dirs(base_dir)

    print(f"Found {len(app_dirs)} application packages in {base_dir}")
    print(f"Target Notion Database: {DB_ID}\n")

    created_count = 0
    updated_count = 0

    for idx, app_dir in enumerate(app_dirs, start=1):
        try:
            with open(app_dir / "current.json", "r", encoding="utf-8") as f:
                current_meta = json.load(f)

            current_v_name = current_meta.get("current_version", "v001")
            v_dir = app_dir / current_v_name
            if not v_dir.is_dir():
                print(f"[{idx}/{len(app_dirs)}] Skipping {app_dir.name}: {current_v_name} not found")
                continue

            # Load job.json
            job_data = {}
            if (v_dir / "job.json").is_file():
                with open(v_dir / "job.json", "r", encoding="utf-8") as f:
                    job_data = json.load(f)

            # Load match analysis
            match_analysis_text = ""
            if (v_dir / "match-analysis.md").is_file():
                match_analysis_text = (v_dir / "match-analysis.md").read_text(encoding="utf-8")

            company = current_meta.get("company") or job_data.get("company") or app_dir.parent.parent.name
            role = current_meta.get("role") or job_data.get("role") or app_dir.parent.name
            title = f"{company} - {role}"
            status = current_meta.get("status") or "TO_APPLY"
            application_url = (
                current_meta.get("application_url")
                or job_data.get("application_url")
                or current_meta.get("canonical_url")
                or job_data.get("canonical_url")
                or job_data.get("url")
                or job_data.get("job_url")
                or ""
            )
            source_url = current_meta.get("source_url") or job_data.get("source_url") or ""

            print(f"[{idx}/{len(app_dirs)}] Processing: {title} ({current_v_name})...")

            # Compute 100-point Match Score
            from job_application_agents.auto_apply.matcher import JobMatchScorer
            scorer_result = JobMatchScorer.score_job(job_data)
            match_score = scorer_result.total_score
            match_breakdown = scorer_result.to_dict()

            # 1. Upload files if present
            resume_fid = None
            letter_fid = None
            zip_fid = None
            screenshot_fid = None

            r_pdf = v_dir / "resume.pdf"
            if r_pdf.is_file():
                r_bytes = r_pdf.read_bytes()
                resume_fid = client.upload_file(f"{company.lower()}-resume-{current_v_name}.pdf", "application/pdf", r_bytes)

            m_pdf = v_dir / "motivation-letter.pdf"
            if m_pdf.is_file():
                m_bytes = m_pdf.read_bytes()
                letter_fid = client.upload_file(f"{company.lower()}-letter-{current_v_name}.pdf", "application/pdf", m_bytes)

            # Check for screenshot
            for s_name in ("submission-success.png", "apply-preview.png", "test_pre_submit.png", "pre-submit.png"):
                s_file = v_dir / s_name
                if s_file.is_file():
                    s_bytes = s_file.read_bytes()
                    screenshot_fid = client.upload_file(f"{company.lower()}-screenshot-{current_v_name}.png", "image/png", s_bytes)
                    break

            # Build source ZIP
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in sorted(v_dir.iterdir()):
                    if item.is_file() and item.suffix in (".tex", ".cls", ".md", ".json", ".jpg", ".png") and not item.name.endswith(".zip"):
                        zf.write(item, arcname=item.name)
            zip_bytes = zip_buf.getvalue()
            if zip_bytes:
                zip_fid = client.upload_file(f"{company.lower()}-{current_v_name}-sources.zip", "application/zip", zip_bytes)

            # 2. Build Notion payload
            reqs = job_data.get("requirements", [])
            reqs_text = "\n".join(reqs) if isinstance(reqs, list) else str(reqs)
            gaps = current_meta.get("gaps", [])
            gaps_text = "\n".join(gaps) if isinstance(gaps, list) else str(gaps)

            payload = NotionCardPayload(
                application_title=title,
                company=company,
                role=role,
                status=status,
                location=job_data.get("location", ""),
                work_model=job_data.get("work_model", "Unspecified"),
                source=job_data.get("source", "Other ATS"),
                job_url=application_url,
                source_url=source_url or None,
                application_url=application_url or None,
                source_job_id=job_data.get("job_id") or app_dir.name,
                current_version=current_v_name,
                generated_at=current_meta.get("generated_at"),
                applied_at=current_meta.get("applied_at"),
                next_action_at=current_meta.get("next_action_at"),
                local_bundle_path=str(app_dir.resolve()),
                match_summary=current_meta.get("match_summary") or scorer_result.rating,
                match_score=match_score,
                match_breakdown=match_breakdown,
                notes=current_meta.get("notes"),
                job_summary_text=job_data.get("summary", ""),
                requirements_text=reqs_text,
                match_analysis_text=match_analysis_text or scorer_result.analysis,
                gaps_text=gaps_text,
            )

            # Check if card already exists
            existing_page = None
            if job_url:
                existing_page = client.find_card_by_job_url(DB_ID, job_url)

            if existing_page:
                page_id = existing_page.get("id")
                client.update_card_properties(page_id, payload)
                client.update_card_documents(
                    page_id=page_id,
                    version=current_v_name,
                    resume_file_id=resume_fid,
                    letter_file_id=letter_fid,
                    zip_file_id=zip_fid,
                    zip_filename=f"{company.lower()}-{current_v_name}-sources.zip",
                    screenshot_file_id=screenshot_fid,
                )
                print(f"    -> Updated card ID: {page_id} (Score: {match_score}/100)")
                updated_count += 1
            else:
                page = client.create_card(
                    database_id=DB_ID,
                    payload=payload,
                    resume_file_id=resume_fid,
                    letter_file_id=letter_fid,
                    zip_file_id=zip_fid,
                    zip_filename=f"{company.lower()}-{current_v_name}-sources.zip",
                    screenshot_file_id=screenshot_fid,
                )
                page_id = page.get("id")
                print(f"    -> Created card ID: {page_id} (Score: {match_score}/100)")
                created_count += 1

        except Exception as exc:
            print(f"    -> ERROR processing {app_dir.name}: {exc}")

    print(f"\n=======================================================")
    print(f"Repopulation Complete: {created_count} created, {updated_count} updated")
    print(f"View Board: https://app.notion.com/p/{DB_ID.replace('-', '')}")
    print(f"=======================================================")


if __name__ == "__main__":
    populate_all()
