#!/usr/bin/env python3
"""Run a live Playwright review session accessible from a phone over LAN/Tailscale."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if __name__ == "__main__" and VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from playwright.sync_api import sync_playwright
from job_application_agents.auto_apply.draft_models import ApplicationDraft
from job_application_agents.auto_apply.local_review_server import LocalReviewServer
from job_application_agents.auto_apply.review_session import (
    EncryptedCheckpointStore,
    PlaywrightReviewSession,
)
from job_application_agents.auto_apply.service import AutoApplyService


def main() -> int:
    parser = argparse.ArgumentParser(description="Start interactive phone review session with Playwright.")
    parser.add_argument(
        "--app-dir",
        type=Path,
        required=True,
        help="Path to the tailored application package directory",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host address to bind review server (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind review server (default: 8080)",
    )
    parser.add_argument(
        "--token",
        default="demo123",
        help="Review token for mobile auth (default: demo123)",
    )
    parser.add_argument(
        "--allow-submit",
        action="store_true",
        help="Allow the phone to trigger final submission",
    )
    args = parser.parse_args()

    app_dir = args.app_dir.resolve()
    v_dir = app_dir / "v001"
    if not v_dir.is_dir():
        candidates = sorted([d for d in app_dir.glob("v*") if d.is_dir()])
        v_dir = candidates[-1] if candidates else app_dir

    job_file = app_dir / "job.json"
    if not job_file.is_file():
        print(f"Error: job.json not found in {app_dir}", file=sys.stderr)
        return 1

    job_data = json.loads(job_file.read_text(encoding="utf-8"))
    title = job_data.get("role") or job_data.get("title") or "Role"
    company = job_data.get("company", "Company")
    target_url = (
        job_data.get("application_url")
        or job_data.get("canonical_url")
        or job_data.get("source_url")
        or job_data.get("url")
    )

    if not target_url:
        print(f"Error: Could not resolve target URL from {job_file}", file=sys.stderr)
        return 1

    service = AutoApplyService()
    candidate = service.load_candidate_profile()

    resume_pdf = v_dir / "resume.pdf"
    if not resume_pdf.is_file():
        pdfs = list(v_dir.glob("*.pdf"))
        resume_pdf = pdfs[0] if pdfs else v_dir / "resume.pdf"

    letter_pdf = v_dir / "motivation-letter.pdf"
    if not letter_pdf.is_file():
        letter_pdf = None

    store_dir = app_dir / ".review_store"
    store = EncryptedCheckpointStore(store_dir)

    print("\n" + "=" * 60)
    print(" PLAYWRIGHT PHONE-CONTROLLED REVIEW SESSION")
    print("=" * 60)
    print(f"Opening:   {title} at {company}")
    print(f"URL:       {target_url}")
    print(f"Candidate: {candidate.full_name}")
    print("=" * 60 + "\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="Europe/Paris",
        )
        page = context.new_page()

        print(f"Navigating browser to {target_url}...")
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # Build initial draft
        initial_draft = ApplicationDraft(
            application_id=app_dir.name,
            company=company,
            job_title=title,
            target_url=target_url,
            revision=1,
            fields=[],
            resume_path=str(resume_pdf.resolve()),
            letter_path=str(letter_pdf.resolve()) if letter_pdf else None,
        )

        session = PlaywrightReviewSession(
            page=page,
            draft=initial_draft,
            candidate=candidate,
            store=store,
            allow_submission=args.allow_submit,
        )

        # Initialize the first form step (inspects and prefills)
        print("Inspecting and prefilling step 1...")
        session.prepare_current_step()

        # Start review server
        token = args.token
        server = LocalReviewServer(
            session=session,
            host=args.host,
            port=args.port,
            token=token,
        )
        base_url = server.start()

        print("\n" + "*" * 60)
        print(" REVIEW SERVER READY!")
        print(f" Access on Phone (Wi-Fi):     http://10.123.204.144:{args.port}/")
        print(f" Access on Phone (Tailscale): http://100.109.205.45:{args.port}/")
        print(f" Review Token:                {token}")
        print("*" * 60 + "\n")
        print("Open the link on your phone, type the Review Token, and you will see:")
        print(" - Prefilled inputs")
        print(" - Resume / motivation letter links")
        print(" - 'Approve step' button to tell Playwright to proceed to the next step\n")
        print("Press Ctrl+C in terminal to stop the session.")

        try:
            while True:
                time.sleep(1)
                if session.state in {"SUBMITTED_CONFIRMED", "SKIPPED"}:
                    print(f"Session finished with state: {session.state}")
                    break
        except KeyboardInterrupt:
            print("\nShutting down review server...")
        finally:
            server.stop()
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
