#!/usr/bin/env python3
"""Run a durable Playwright application review session for a phone browser.

The service binds locally by default.  For a private Tailscale connection use
``--host 0.0.0.0`` and publish the chosen port with ``tailscale serve``.
"""

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

from job_application_agents.auto_apply.draft_models import ApplicationDraft, ApplicationField, ApplicationState
from job_application_agents.auto_apply.local_review_server import LocalReviewServer
from job_application_agents.auto_apply.review_session import (
    EncryptedCheckpointStore,
    PlaywrightReviewSession,
)
from job_application_agents.auto_apply.service import AutoApplyService, validate_public_target_url


def _application_paths(app_dir: Path) -> tuple[dict, Path]:
    current = {}
    current_path = app_dir / "current.json"
    if current_path.is_file():
        current = json.loads(current_path.read_text(encoding="utf-8"))
    version = current.get("current_version") or current.get("version") or "v001"
    version_dir = app_dir / version
    if not version_dir.is_dir():
        candidates = sorted(p for p in app_dir.iterdir() if p.is_dir() and p.name.startswith("v"))
        version_dir = candidates[-1] if candidates else app_dir
    return current, version_dir


def _target_url(current: dict, version_dir: Path) -> str:
    job_data = {}
    job_path = version_dir / "job.json"
    if job_path.is_file():
        job_data = json.loads(job_path.read_text(encoding="utf-8"))
    value = (
        current.get("canonical_url")
        or job_data.get("canonical_url")
        or job_data.get("source_url")
        or job_data.get("url")
        or job_data.get("job_url")
    )
    if not value:
        raise ValueError(f"No job URL found in {version_dir}")
    return validate_public_target_url(str(value))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a phone-accessible durable Playwright review session.")
    parser.add_argument("--app-dir", type=Path, required=True, help="Tailored application package directory")
    parser.add_argument("--profile", type=Path, help="Optional candidate_profile.json")
    parser.add_argument("--data-dir", type=Path, help="Local encrypted review data directory")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; use 0.0.0.0 for Tailscale access")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", help="Review token; otherwise generated and printed once")
    parser.add_argument("--allow-submit", action="store_true", help="Allow final submit only with the explicit environment gate")
    parser.add_argument("--headless", action="store_true", help="Run Chromium without a visible desktop window")
    args = parser.parse_args()

    app_dir = args.app_dir.expanduser().resolve()
    if not app_dir.is_dir():
        parser.error(f"Application directory not found: {app_dir}")
    current, version_dir = _application_paths(app_dir)
    target_url = _target_url(current, version_dir)
    service = AutoApplyService()
    candidate = service.load_candidate_profile(args.profile)
    resume = version_dir / "resume.pdf"
    if not resume.is_file():
        pdfs = sorted(version_dir.glob("*.pdf"))
        if pdfs:
            resume = pdfs[0]
    letter = version_dir / "motivation-letter.pdf"
    letter_path = letter if letter.is_file() else None
    app_id = str(current.get("application_id") or app_dir.name)
    data_dir = (args.data_dir or (app_dir / ".review")).expanduser().resolve()
    store = EncryptedCheckpointStore(data_dir)
    checkpoint = store.load()

    if checkpoint and checkpoint.state in {ApplicationState.SUBMITTED_CONFIRMED.value, ApplicationState.SKIPPED.value}:
        print(f"A terminal review checkpoint already exists: {checkpoint.state}")
        return 0

    from playwright.sync_api import sync_playwright

    profile_dir = data_dir / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=args.headless,
            args=["--no-sandbox"],
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="Europe/Paris",
        )
        try:
            page = browser.pages[0] if browser.pages else browser.new_page()
            resume_url = checkpoint.page_url if checkpoint and checkpoint.page_url else target_url
            page.goto(resume_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            if checkpoint:
                draft = ApplicationDraft(
                    application_id=checkpoint.application_id,
                    company=checkpoint.company,
                    job_title=checkpoint.job_title,
                    target_url=checkpoint.target_url,
                    revision=checkpoint.revision,
                    fields=[ApplicationField.from_dict(f) for f in checkpoint.fields],
                    resume_path=checkpoint.resume_path,
                    letter_path=checkpoint.letter_path,
                    state=ApplicationState.REVIEW_READY,
                )
                step_index = checkpoint.step_index
            else:
                draft = ApplicationDraft(
                    application_id=app_id,
                    company=str(current.get("company") or current.get("company_name") or "Unknown company"),
                    job_title=str(current.get("role") or current.get("job_title") or "Software Engineer"),
                    target_url=target_url,
                    revision=1,
                    fields=[],
                    resume_path=str(resume.resolve()),
                    letter_path=str(letter_path.resolve()) if letter_path else None,
                )
                step_index = 1

            session = PlaywrightReviewSession(
                page=page,
                draft=draft,
                candidate=candidate,
                store=store,
                browser_profile_dir=profile_dir,
                allow_submission=args.allow_submit,
            )
            session.step_index = step_index
            if checkpoint:
                session.visible_field_ids = list(checkpoint.visible_field_ids)
            session.prepare_current_step()
            server = LocalReviewServer(session, host=args.host, port=args.port, token=args.token)
            url = server.start()
            print("=== Phone Review Session ===")
            print(f"Review URL: {url}")
            print(f"Review token: {server.token}")
            if args.host == "0.0.0.0":
                print("Publish privately with: tailscale serve --https=443 http://127.0.0.1:%s" % server.port)
            print("The browser will remain open until the application is submitted, skipped, or stopped.")
            try:
                while session.state not in {
                    ApplicationState.SUBMITTED_CONFIRMED.value,
                    ApplicationState.SUBMISSION_UNCERTAIN.value,
                    ApplicationState.SKIPPED.value,
                    ApplicationState.FAILED.value,
                }:
                    time.sleep(0.5)
            finally:
                server.stop()
        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
