from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from job_application_agents.plugins.notion.client import NotionClient
from job_application_agents.plugins.notion.models import NotionCardPayload

TOKEN = os.environ.get("NOTION_TOKEN")
PARENT_PAGE_ID = "76df576a-7316-4dd4-b4bc-8ce9b7685394"


def create_board_and_mock_tickets():
    if not TOKEN:
        print("NOTION_TOKEN environment variable is required")
        return 1
    client = NotionClient(token=TOKEN)

    print(f"Connecting to parent page {PARENT_PAGE_ID} with token {TOKEN[:10]}...")

    # 1. Verify parent page access
    try:
        page = client._request("GET", f"pages/{PARENT_PAGE_ID}")
        print(f"OK Parent page accessible: {page.get('url', PARENT_PAGE_ID)}")
    except Exception as exc:
        print(f"\nERROR: Parent page is not yet connected to 'Worker connection'.\nDetails: {exc}")
        print("\nPlease in Notion:")
        print("1. Open https://app.notion.com/p/76df576a73164dd4b4bc8ce9b7685394")
        print("2. Click '...' (top right) -> 'Connections' -> Add 'Worker connection'")
        return 1

    # 2. Check if database already exists inside page or create it
    print("\nCreating 'Job Applications' database schema...")
    db_schema = {
        "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
        "title": [{"type": "text", "text": {"content": "Job Applications"}}],
        "properties": {
            "Application": {"title": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "TO_APPLY", "color": "blue"},
                        {"name": "APPLIED", "color": "yellow"},
                        {"name": "INTERVIEW", "color": "purple"},
                        {"name": "OFFER", "color": "green"},
                        {"name": "REJECTED", "color": "red"},
                        {"name": "WITHDRAWN", "color": "gray"},
                        {"name": "REAPPLY", "color": "orange"},
                        {"name": "FINAL_INTERVIEW", "color": "purple"},
                        {"name": "HIRED", "color": "green"},
                        {"name": "OFFER_DECLINED", "color": "gray"},
                        {"name": "HUMAN_REVIEW", "color": "yellow"},
                        {"name": "SUBMISSION_UNCERTAIN", "color": "orange"},
                        {"name": "DROPPED", "color": "red"},
                    ]
                }
            },
            "Company": {"rich_text": {}},
            "Role": {"rich_text": {}},
            "Location": {"rich_text": {}},
            "Work Model": {
                "select": {
                    "options": [
                        {"name": "Remote", "color": "green"},
                        {"name": "Hybrid", "color": "blue"},
                        {"name": "On-site", "color": "orange"},
                        {"name": "Unspecified", "color": "gray"},
                    ]
                }
            },
            "Source": {
                "select": {
                    "options": [
                        {"name": "LinkedIn", "color": "blue"},
                        {"name": "Company Website", "color": "purple"},
                        {"name": "WTTJ", "color": "yellow"},
                        {"name": "Other ATS", "color": "gray"},
                    ]
                }
            },
            "Job URL": {"url": {}},
            "Source URL": {"url": {}},
            "Application URL": {"url": {}},
            "Source Job ID": {"rich_text": {}},
            "Application ID": {"rich_text": {}},
            "Current Version": {"rich_text": {}},
            "Generated At": {"date": {}},
            "Applied At": {"date": {}},
            "Next Action At": {"date": {}},
            "Local Bundle Path": {"rich_text": {}},
            "Match Summary": {"rich_text": {}},
            "Notes": {"rich_text": {}},
        }
    }

    try:
        db = client._request("POST", "databases", data=db_schema)
        db_id = db.get("id")
        db_url = db.get("url")
        print(f"OK Created Database! ID: {db_id} | URL: {db_url}")
    except Exception as exc:
        print(f"FAIL creating database: {exc}")
        return 1

    # 3. Create mock tickets with PDF uploads
    dummy_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000053 00000 n \n0000000102 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF"
    dummy_zip = b"PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    mock_apps = [
        {
            "payload": NotionCardPayload(
                application_title="DINUM - Développeur Fullstack Python / Cloud",
                company="DINUM",
                role="Développeur Fullstack Python / Cloud",
                status="TO_APPLY",
                location="Paris, France (Hybride)",
                work_model="Hybrid",
                source="LinkedIn",
                job_url="https://www.linkedin.com/jobs/view/dinum-fullstack-dev-4148",
                source_job_id="dinum-fullstack-4148",
                current_version="v006",
                generated_at="2026-08-25T22:00:00.000Z",
                match_summary="Strong match for public sector digital transformation with Python, API design, and container orchestration.",
                job_summary_text="Direction interministérielle du numérique (DINUM) is seeking a Senior Python / Cloud developer to modernize digital public services.",
                requirements_text="• 5+ years Python and modern API development\n• Cloud infrastructure (Scaleway / OVH / AWS)\n• Open-source ethos and public service dedication",
                match_analysis_text="Strong candidate alignment on Python API architecture, async frameworks, and DevOps automation.",
                gaps_text="French administrative procurement familiarity.",
            ),
            "prefix": "dinum"
        },
        {
            "payload": NotionCardPayload(
                application_title="Mistral AI - Senior AI Systems Engineer",
                company="Mistral AI",
                role="Senior AI Systems Engineer",
                status="APPLIED",
                location="Paris, France",
                work_model="On-site",
                source="Company Website",
                job_url="https://jobs.mistral.ai/senior-ai-systems-engineer",
                source_job_id="mistral-sys-882",
                current_version="v002",
                generated_at="2026-08-24T14:30:00.000Z",
                applied_at="2026-08-25T09:00:00.000Z",
                next_action_at="2026-09-01T09:00:00.000Z",
                match_summary="High score for high-throughput model serving pipelines and low-latency distributed systems.",
                job_summary_text="Build distributed inference infrastructure and optimized deployment pipelines for frontier open-weights models.",
                requirements_text="• Distributed systems in Python / C++ / CUDA\n• High-concurrency async servers\n• Performance profiling and latency minimization",
                match_analysis_text="Proven background in scalable systems design, automated testing, and cloud runtime optimization.",
                gaps_text="Direct vLLM kernel hacking experience.",
            ),
            "prefix": "mistral"
        },
        {
            "payload": NotionCardPayload(
                application_title="Hugging Face - Open Source Platform Engineer",
                company="Hugging Face",
                role="Open Source Platform Engineer",
                status="INTERVIEW",
                location="Remote",
                work_model="Remote",
                source="Company Website",
                job_url="https://apply.workable.com/huggingface/j/HF99812",
                source_job_id="hf-platform-998",
                current_version="v003",
                generated_at="2026-08-20T10:00:00.000Z",
                applied_at="2026-08-21T11:00:00.000Z",
                next_action_at="2026-08-28T15:00:00.000Z",
                match_summary="Exceptional alignment with open-source tools, documentation rigor, and collaborative developer tooling.",
                job_summary_text="Work with the Hub infrastructure team to build collaborative AI developer tools and dataset versioning.",
                requirements_text="• Python packaging and developer CLI tooling\n• Git-based versioning workflows\n• High test coverage and clear open-source docs",
                match_analysis_text="Candidate portfolio exhibits extensive open-source tooling, clear architecture, and clean reproducible CLI builds.",
                gaps_text="None identified.",
            ),
            "prefix": "hf"
        }
    ]

    for item in mock_apps:
        payload = item["payload"]
        pfx = item["prefix"]
        print(f"\nUploading files for {payload.company}...")
        r_fid = client.upload_file(f"{pfx}-resume.pdf", "application/pdf", dummy_pdf)
        l_fid = client.upload_file(f"{pfx}-motivation-letter.pdf", "application/pdf", dummy_pdf)
        z_fid = client.upload_file(f"{pfx}-sources.zip", "application/zip", dummy_zip)

        print(f"Creating card: {payload.application_title}...")
        page = client.create_card(
            database_id=db_id,
            payload=payload,
            resume_file_id=r_fid,
            letter_file_id=l_fid,
            zip_file_id=z_fid,
            zip_filename=f"{pfx}-sources.zip"
        )
        print(f" -> OK Created! URL: {page.get('url')}")

    print(f"\nSUCCESS! All mock tickets created on new database: {db_url}")
    return 0


if __name__ == "__main__":
    sys.exit(create_board_and_mock_tickets())
