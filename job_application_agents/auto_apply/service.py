from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlparse

from .drivers import DriverRegistry, default_registry
from .models import CandidateProfile, FormFillResult, SubmissionReceipt


SUBMISSION_CONFIRMATION = "I_UNDERSTAND_SUBMISSION"


def validate_public_target_url(value: str) -> str:
    """Allow only ordinary public HTTP(S) job URLs in browser automation."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("target URL must be an absolute http(s) URL")
    return value


class AutoApplyService:
    """Service that coordinates Playwright browser automation to apply for jobs."""

    def __init__(self, registry: DriverRegistry | None = None):
        self.registry = registry or default_registry

    def load_candidate_profile(self, profile_path: Path | None = None) -> CandidateProfile:
        """Load candidate identity details without inventing a candidate."""
        if profile_path and profile_path.is_file():
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            return self._validated_profile(CandidateProfile.from_dict(data))

        # Look in default locations
        default_paths = [
            Path("job-search/candidate_profile.json"),
            Path.home() / "Documents" / "job-search" / "candidate_profile.json",
        ]
        for p in default_paths:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                return self._validated_profile(CandidateProfile.from_dict(data))

        # Check sources/identity.md
        identity_paths = [
            Path("job-search/sources/identity.md"),
            Path.home() / "Documents" / "job-search" / "sources" / "identity.md",
        ]
        for ip in identity_paths:
            if ip.is_file():
                text = ip.read_text(encoding="utf-8")
                name, email, phone, github, linkedin, portfolio = "", "", "", "", "", ""
                for line in text.splitlines():
                    if "Name:" in line:
                        name = line.split("Name:", 1)[1].strip()
                    elif "Email:" in line:
                        email = line.split("Email:", 1)[1].strip()
                    elif "Phone:" in line and not phone:
                        phone = line.split("Phone:", 1)[1].strip()
                    elif "GitHub:" in line:
                        github = line.split("GitHub:", 1)[1].strip()
                    elif "LinkedIn:" in line:
                        linkedin = line.split("LinkedIn:", 1)[1].strip()
                    elif "Portfolio:" in line:
                        portfolio = line.split("Portfolio:", 1)[1].strip()

                parts = name.split(" ", 1)
                first = parts[0] if parts and parts[0] else ""
                last = parts[1] if len(parts) > 1 else ""
                return self._validated_profile(CandidateProfile(
                    first_name=first,
                    last_name=last,
                    email=email,
                    phone=phone,
                    location="",
                    linkedin_url=linkedin,
                    github_url=github,
                    portfolio_url=portfolio,
                ))

        raise FileNotFoundError(
            "No candidate profile found. Provide --profile or configure "
            "sources/identity.md under the private data root."
        )

    @staticmethod
    def _validated_profile(profile: CandidateProfile) -> CandidateProfile:
        missing = [
            field for field in ("first_name", "last_name", "email", "phone", "location")
            if not getattr(profile, field).strip()
        ]
        if missing:
            raise ValueError(
                "candidate profile is incomplete; supply real values for: "
                + ", ".join(missing)
            )
        return profile


    def apply(
        self,
        app_dir: Path,
        candidate_profile: CandidateProfile | None = None,
        mode: str = "dry-run",  # "supervised" or "dry-run"
        timeout_ms: int = 45000,
        allow_submission: bool = False,
    ) -> SubmissionReceipt:
        """Fill a form for review, or produce a dry-run preview.

        Submission is disabled by default. Supervised mode fills the form and
        captures a review screenshot unless both ``allow_submission=True`` and
        the explicit ``JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION`` gate are
        present. The cloud worker has a separate approval-token flow, protected
        by the same deployment gate.
        """
        if mode not in {"supervised", "dry-run"}:
            raise ValueError("submission mode must be supervised or dry-run")
        if allow_submission and os.environ.get("JAA_ENABLE_SUBMISSION") != SUBMISSION_CONFIRMATION:
            raise PermissionError(
                "submission is disabled; set JAA_ENABLE_SUBMISSION="
                f"{SUBMISSION_CONFIRMATION} and pass allow_submission=True"
            )

        from playwright.sync_api import sync_playwright

        if not app_dir.is_dir():
            raise FileNotFoundError(f"Application directory not found: {app_dir}")

        # 1. Resolve current version & documents
        current_meta = {}
        if (app_dir / "current.json").is_file():
            current_meta = json.loads((app_dir / "current.json").read_text(encoding="utf-8"))

        current_v = current_meta.get("current_version") or current_meta.get("version") or "v001"
        v_dir = app_dir / current_v
        if not v_dir.is_dir():
            # Fallback to highest v directory
            v_dirs = sorted([d for d in app_dir.iterdir() if d.is_dir() and d.name.startswith("v")])
            if v_dirs:
                v_dir = v_dirs[-1]
            else:
                v_dir = app_dir


        job_data = {}
        if (v_dir / "job.json").is_file():
            job_data = json.loads((v_dir / "job.json").read_text(encoding="utf-8"))

        target_url = (
            current_meta.get("canonical_url")
            or job_data.get("canonical_url")
            or job_data.get("source_url")
            or job_data.get("url")
            or job_data.get("job_url")
        )
        if not target_url:
            raise ValueError(f"No job URL found in {app_dir}")
        target_url = validate_public_target_url(str(target_url))


        resume_pdf = v_dir / "resume.pdf"
        if not resume_pdf.is_file():
            # Search for any PDF
            pdfs = list(v_dir.glob("*.pdf"))
            if pdfs:
                resume_pdf = pdfs[0]

        letter_pdf = v_dir / "motivation-letter.pdf"
        if not letter_pdf.is_file():
            letter_pdf = None

        candidate = candidate_profile or self.load_candidate_profile()
        driver = self.registry.resolve(target_url)

        print(f"=== Auto-Apply Session ===")
        print(f"Target URL:        {target_url}")
        print(f"ATS Driver:        {driver.name}")
        print(f"Candidate:         {candidate.full_name} ({candidate.email})")
        print(f"Resume PDF:        file://{resume_pdf.resolve() if resume_pdf.is_file() else 'None'}")
        if letter_pdf and letter_pdf.is_file():
            print(f"Motivation Letter: file://{letter_pdf.resolve()}")
        print(f"Execution Mode:    {mode.upper()}\n")


        headless = mode == "dry-run"

        # Keep browser behavior ordinary and transparent. Do not attempt to
        # evade bot detection or bypass a portal's access controls.
        launch_args = ["--no-sandbox"]

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=launch_args,
                slow_mo=50 if not headless else 0,
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="Europe/Paris",
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)


            try:
                print(f"[1/4] Navigating to {target_url}...")
                page.goto(target_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                print(f"[2/4] Agentic inspection and autofill using '{driver.name}' driver...")
                from .agent_solver import AgentFormSolver
                fill_res = AgentFormSolver.solve_form(
                    page=page,
                    candidate=candidate,
                    resume_pdf=resume_pdf,
                    letter_pdf=letter_pdf,
                )
                # Also run driver-specific post-adjustments if any
                driver_res = driver.fill_form(
                    page=page,
                    candidate=candidate,
                    resume_pdf=resume_pdf,
                    letter_pdf=letter_pdf,
                    job_data=job_data,
                )
                all_fields = list(dict.fromkeys(fill_res.fields_filled + driver_res.fields_filled))
                print(f" -> All Fields Filled ({len(all_fields)}): {', '.join(all_fields) if all_fields else 'None'}")
                print(f" -> Resume Uploaded: {fill_res.resume_uploaded or driver_res.resume_uploaded}")


                # Dry-run and the default supervised mode stop before any
                # submit control is reached.
                if mode == "dry-run" or not allow_submission:
                    screenshot_file = v_dir / (
                        "apply-preview.png" if mode == "dry-run" else "form-review.png"
                    )
                    page.screenshot(path=str(screenshot_file), full_page=True)
                    print(f"\n[3/4] Form review saved: {screenshot_file}")
                    return SubmissionReceipt(
                        success=True,
                        driver_name=driver.name,
                        job_url=target_url,
                        applied_at=datetime.now(timezone.utc).isoformat(),
                        confirmation_text=(
                            "Dry-run completed successfully"
                            if mode == "dry-run"
                            else "Supervised form fill completed; submission is disabled by default"
                        ),
                        screenshot_path=str(screenshot_file),
                        submitted=False,
                    )

                # If Supervised Mode: Pause for review
                if mode == "supervised":
                    print("\n[3/4] SUPERVISED MODE: Review the filled form in the browser window.")
                    print("Press ENTER in the terminal to submit, or type 'cancel' to abort: ", end="")
                    user_resp = input().strip().lower()
                    if user_resp == "cancel":
                        print(" -> Aborted by user.")
                        return SubmissionReceipt(
                            success=False,
                            driver_name=driver.name,
                            job_url=target_url,
                            applied_at=datetime.now(timezone.utc).isoformat(),
                            error_message="Submission cancelled by user",
                        )

                # Submit Form
                print(f"[4/4] Submitting application...")
                receipt = driver.submit(page=page, job_url=target_url)
                receipt.submitted = bool(receipt.success)

                # Capture confirmation screenshot
                receipt_screenshot = v_dir / "submission-confirmation.png"
                page.screenshot(path=str(receipt_screenshot))
                receipt.screenshot_path = str(receipt_screenshot)

                # Record receipt in version directory
                receipt_path = v_dir / "receipt.json"
                receipt_path.write_text(json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")

                if receipt.success:
                    # Update current.json status to APPLIED
                    if current_meta:
                        current_meta["status"] = "APPLIED"
                        current_meta["applied_at"] = receipt.applied_at
                        (app_dir / "current.json").write_text(json.dumps(current_meta, indent=2), encoding="utf-8")
                    print(f"\nSUCCESS: Application submitted! Status set to APPLIED.")
                    print(f"Receipt saved: {receipt_path}")
                else:
                    print(f"\nWARNING: Submission could not be confirmed: {receipt.error_message}")

                return receipt

            finally:
                browser.close()
