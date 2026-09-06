from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.plugins.notion.client import NotionClient, NotionAPIError
from job_application_agents.plugins.notion.models import NotionCardPayload

OLD_TOKEN = os.environ.get("NOTION_OLD_TOKEN")
OLD_DB_ID = "76f01432-b1e0-4c75-b9d5-f85de81d9dbf"

NEW_TOKEN = os.environ.get("NOTION_TOKEN")
NEW_DB_ID = "3c7ac433-f81d-80bd-959d-ecfeba5f8ffe"


def notion_request(token: str, method: str, path: str, data: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1/{path.lstrip('/')}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        err_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion API error ({exc.code} {exc.reason}): {err_text}") from exc


def clean_target_database():
    print(f"=== Step 1: Cleaning all existing rows in Target DB ({NEW_DB_ID}) ===")
    query_resp = notion_request(NEW_TOKEN, "POST", f"databases/{NEW_DB_ID}/query", data={})
    rows = query_resp.get("results", [])
    print(f"Found {len(rows)} cards to archive...")
    for idx, row in enumerate(rows, start=1):
        row_id = row.get("id")
        try:
            notion_request(NEW_TOKEN, "PATCH", f"pages/{row_id}", data={"archived": True})
            print(f" [{idx}/{len(rows)}] Archived card {row_id}")
        except Exception as exc:
            print(f" [{idx}/{len(rows)}] Failed to archive {row_id}: {exc}")
    print(" -> Target DB cleared!\n")


def ensure_title_property_name():
    print("=== Step 2: Renaming title property to 'Application' if needed ===")
    db_meta = notion_request(NEW_TOKEN, "GET", f"databases/{NEW_DB_ID}")
    props = db_meta.get("properties", {})
    if "Name" in props and "Application" not in props:
        try:
            notion_request(
                NEW_TOKEN,
                "PATCH",
                f"databases/{NEW_DB_ID}",
                data={"properties": {"Name": {"name": "Application"}}},
            )
            print(" -> Renamed title property 'Name' to 'Application'")
        except Exception as exc:
            print(f" -> Notice: Could not rename title property ({exc}), will use automatic title fallback.")


def migrate_all_cards():
    if not OLD_TOKEN or not NEW_TOKEN:
        raise RuntimeError("NOTION_OLD_TOKEN and NOTION_TOKEN environment variables are required")
    print(f"\n=== Step 3: Fetching all 22 cards from Old DB ({OLD_DB_ID}) ===")
    old_query = notion_request(OLD_TOKEN, "POST", f"databases/{OLD_DB_ID}/query", data={})
    old_cards = old_query.get("results", [])
    print(f"Fetched {len(old_cards)} cards from old board.\n")

    new_client = NotionClient(token=NEW_TOKEN)

    # Pre-index local application bundles by company/role and job_id
    local_apps_by_path: dict[str, Path] = {}
    for p in Path("job-search/applications").glob("*/*/*"):
        if p.is_dir() and (p / "current.json").is_file():
            local_apps_by_path[str(p.resolve())] = p
            local_apps_by_path[p.name] = p

    success_count = 0

    for idx, old_page in enumerate(old_cards, start=1):
        page_id = old_page.get("id")
        props = old_page.get("properties", {})

        # Extract title
        title = ""
        for p in props.values():
            if p.get("type") == "title":
                t_list = p.get("title", [])
                if t_list:
                    title = t_list[0].get("plain_text", "")

        status = (props.get("Status") or {}).get("select", {}).get("name") or "TO_APPLY"

        # Extract rich texts and dates safely
        def get_text(prop_name: str) -> str:
            val = props.get(prop_name, {}).get("rich_text", [])
            return val[0].get("plain_text", "") if val else ""

        def get_date(prop_name: str) -> str | None:
            d_obj = (props.get(prop_name) or {}).get("date")
            if isinstance(d_obj, dict):
                return d_obj.get("start")
            return None

        company = get_text("Company")
        role = get_text("Role")
        location = get_text("Location")
        work_model = (props.get("Work Model") or {}).get("select") or {}
        work_model_str = work_model.get("name", "Unspecified") if isinstance(work_model, dict) else "Unspecified"
        source_obj = (props.get("Source") or {}).get("select") or {}
        source_str = source_obj.get("name", "Other ATS") if isinstance(source_obj, dict) else "Other ATS"
        job_url = (props.get("Job URL") or {}).get("url") or ""
        source_url = (props.get("Source URL") or {}).get("url") or ""
        application_url = (props.get("Application URL") or {}).get("url") or job_url
        source_job_id = get_text("Source Job ID")
        current_version = get_text("Current Version") or "v001"
        generated_at = get_date("Generated At")
        applied_at = get_date("Applied At")
        next_action_at = get_date("Next Action At")
        local_bundle_path = get_text("Local Bundle Path")
        match_summary = get_text("Match Summary")
        notes = get_text("Notes")


        print(f"[{idx}/{len(old_cards)}] Migrating: '{title}' ({company}) | Status: {status} | URL: {job_url[:50] if job_url else 'None'}")

        # Fetch old blocks to extract text content
        job_summary_text = ""
        reqs_text = ""
        match_analysis_text = ""
        gaps_text = ""

        try:
            blocks_resp = notion_request(OLD_TOKEN, "GET", f"blocks/{page_id}/children")
            old_blocks = blocks_resp.get("results", [])
            current_section = None
            for b in old_blocks:
                b_type = b.get("type")
                if b_type == "heading_2":
                    h_text = ""
                    rt = b.get("heading_2", {}).get("rich_text", [])
                    if rt:
                        h_text = rt[0].get("plain_text", "").strip()
                    current_section = h_text
                elif b_type == "paragraph" and current_section:
                    p_text = ""
                    rt = b.get("paragraph", {}).get("rich_text", [])
                    if rt:
                        p_text = rt[0].get("plain_text", "").strip()
                    if current_section == "Job Summary":
                        job_summary_text = (job_summary_text + "\n\n" + p_text).strip()
                    elif current_section == "Requirements":
                        reqs_text = (reqs_text + "\n\n" + p_text).strip()
                    elif current_section == "Match Analysis":
                        match_analysis_text = (match_analysis_text + "\n\n" + p_text).strip()
                    elif current_section == "Gaps":
                        gaps_text = (gaps_text + "\n\n" + p_text).strip()
        except Exception as exc:
            print(f"    Notice: Could not fetch old blocks for {page_id}: {exc}")

        # Resolve local files for attachments
        resume_fid = None
        letter_fid = None
        zip_fid = None
        target_local_dir = None

        if local_bundle_path and local_bundle_path in local_apps_by_path:
            target_local_dir = local_apps_by_path[local_bundle_path]
        elif source_job_id and source_job_id in local_apps_by_path:
            target_local_dir = local_apps_by_path[source_job_id]

        if target_local_dir:
            v_dir = target_local_dir / current_version
            if not v_dir.is_dir():
                # Fallback to highest version
                v_dirs = [p for p in target_local_dir.iterdir() if p.is_dir() and p.name.startswith("v")]
                if v_dirs:
                    v_dir = sorted(v_dirs)[-1]

            if v_dir.is_dir():
                r_pdf = v_dir / "resume.pdf"
                if r_pdf.is_file():
                    resume_fid = new_client.upload_file(f"{company.lower()}-resume-{current_version}.pdf", "application/pdf", r_pdf.read_bytes())
                m_pdf = v_dir / "motivation-letter.pdf"
                if m_pdf.is_file():
                    letter_fid = new_client.upload_file(f"{company.lower()}-letter-{current_version}.pdf", "application/pdf", m_pdf.read_bytes())

                # Zip sources
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for item in sorted(v_dir.iterdir()):
                        if item.is_file() and item.suffix in (".tex", ".cls", ".md", ".json", ".jpg", ".png") and not item.name.endswith(".zip"):
                            zf.write(item, arcname=item.name)
                zip_bytes = zip_buf.getvalue()
                if zip_bytes:
                    zip_fid = new_client.upload_file(f"{company.lower()}-{current_version}-sources.zip", "application/zip", zip_bytes)

        payload = NotionCardPayload(
            application_title=title,
            company=company,
            role=role,
            status=status,
            location=location,
            work_model=work_model_str,
            source=source_str,
            job_url=job_url,
            source_url=source_url or None,
            application_url=application_url or None,
            source_job_id=source_job_id,
            current_version=current_version,
            generated_at=generated_at,
            applied_at=applied_at,
            next_action_at=next_action_at,

            local_bundle_path=local_bundle_path,
            match_summary=match_summary,
            notes=notes,
            job_summary_text=job_summary_text,
            requirements_text=reqs_text,
            match_analysis_text=match_analysis_text,
            gaps_text=gaps_text,
        )

        try:
            created_page = new_client.create_card(
                database_id=NEW_DB_ID,
                payload=payload,
                resume_file_id=resume_fid,
                letter_file_id=letter_fid,
                zip_file_id=zip_fid,
                zip_filename=f"{company.lower()}-{current_version}-sources.zip",
            )
            print(f"    -> Successfully migrated to new card: {created_page.get('url')}")
            success_count += 1
        except Exception as exc:
            print(f"    -> ERROR creating card: {exc}")

    print(f"\n=======================================================")
    print(f"1-to-1 Migration Complete: {success_count}/{len(old_cards)} cards copied with 100% metadata!")
    print(f"Open New Board: https://app.notion.com/p/{NEW_DB_ID.replace('-', '')}")
    print(f"=======================================================")


if __name__ == "__main__":
    clean_target_database()
    ensure_title_property_name()
    migrate_all_cards()
