from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import hashlib
import re
import sys
from typing import Any
from urllib.parse import urlparse

from .drivers import DriverRegistry, default_registry
from .models import CandidateProfile, SubmissionReceipt
from .browser import application_browser
from .portal import PortalGuard
from ..config import resolve_data_root


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
                name, email, phone, location, github, linkedin, portfolio = "", "", "", "", "", "", ""
                for line in text.splitlines():
                    if "Name:" in line:
                        name = line.split("Name:", 1)[1].strip()
                    elif "Email:" in line:
                        email = line.split("Email:", 1)[1].strip()
                    elif "Phone:" in line and not phone:
                        phone = line.split("Phone:", 1)[1].strip()
                    elif "Location:" in line:
                        location = line.split("Location:", 1)[1].strip()
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
                    location=location,
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
        mode: str = "dry-run",
        timeout_ms: int = 45000,
        allow_submission: bool = False,
        browser_backend: str = "playwright",
        browser_profile: Path | None = None,
        data_root: Path | None = None,
        resume_path: Path | None = None,
        letter_path: Path | None = None,
        headed: bool = False,
    ) -> SubmissionReceipt:
        """Fill once for review; submit only through the explicit gated step."""
        if mode not in {"supervised", "dry-run"}:
            raise ValueError("submission mode must be supervised or dry-run")
        if allow_submission and os.environ.get("JAA_ENABLE_SUBMISSION") != SUBMISSION_CONFIRMATION:
            raise PermissionError(
                "submission is disabled; set JAA_ENABLE_SUBMISSION="
                f"{SUBMISSION_CONFIRMATION} and pass allow_submission=True"
            )
        app_dir = app_dir.resolve(strict=True)
        if not app_dir.is_dir():
            raise FileNotFoundError(f"Application directory not found: {app_dir}")
        root = resolve_data_root(data_root)
        if not app_dir.is_relative_to(root):
            raise ValueError("Application records and screenshots must be inside the private data root")
        if browser_profile and not browser_profile.expanduser().resolve().is_relative_to(root):
            raise ValueError("Browser profile must be inside the private data root")
        current_path = app_dir / "current.json"
        current_meta = json.loads(current_path.read_text()) if current_path.is_file() else {}
        if str(current_meta.get("status", "")).upper() in {"APPLIED", "SUBMISSION_UNCONFIRMED"}:
            raise PermissionError("Application already submitted or awaiting confirmation; do not retry")
        current_v = current_meta.get("current_version") or current_meta.get("version")
        v_dir = (app_dir / current_v).resolve() if current_v else app_dir
        if not v_dir.is_relative_to(app_dir) or not v_dir.is_dir():
            raise ValueError("Application version is missing or escapes its directory")
        receipt_path = v_dir / "receipt.json"
        if receipt_path.exists():
            old_receipt = json.loads(receipt_path.read_text())
            if old_receipt.get("submitted") or old_receipt.get("submission_attempted"):
                raise PermissionError("A submission attempt already exists; resolve its receipt before retrying")
        job_path = v_dir / "job.json"
        job_data = json.loads(job_path.read_text()) if job_path.is_file() else {}
        target_url = next((value for value in [
            current_meta.get("application_url"), job_data.get("application_url"),
            current_meta.get("canonical_url"), job_data.get("canonical_url"),
            job_data.get("source_url"), job_data.get("url"), job_data.get("job_url"),
        ] if value), None)
        if not target_url:
            raise ValueError(f"No job URL found in {app_dir}")
        target_url = validate_public_target_url(str(target_url))
        guard = PortalGuard(root)
        guard.exclusions.require_allowed(target_url)
        resume_pdf = (resume_path or v_dir / "resume.pdf").resolve(strict=True)
        letter_pdf = letter_path or v_dir / "motivation-letter.pdf"
        if letter_path is not None and not letter_path.is_file():
            raise FileNotFoundError(letter_path)
        letter_pdf = letter_pdf.resolve() if letter_pdf.is_file() else None
        documents = {"resume": resume_pdf}
        if letter_pdf:
            documents["letter"] = letter_pdf
        hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in documents.items()}
        candidate = self._validated_profile(candidate_profile or self.load_candidate_profile())
        driver = self.registry.resolve(target_url)
        # Contact values and URL query tokens never go into general logs.
        print(f"Auto-apply: {driver.name}; browser={browser_backend}; mode={mode}")
        if sys.stdin and sys.stdin.isatty() and os.environ.get("DISPLAY"):
            is_headless = (mode == "dry-run" and not headed)
        else:
            is_headless = not headed
        with application_browser(backend=browser_backend, headless=is_headless,
                                 profile_dir=browser_profile) as context:
            guard.install(context)
            page = context.new_page()
            guard.attach(page)
            page.set_default_timeout(timeout_ms)
            page.goto(target_url, wait_until="domcontentloaded")
            guard.check(page)
            # The old legacy solver could click final Submit during autofill.
            # Drivers fill identity fields only and leave custom answers for review.
            driver.fill_form(page=page, candidate=candidate, resume_pdf=resume_pdf,
                             letter_pdf=letter_pdf, job_data=job_data)
            guard.check(page)
            if mode == "dry-run" or not allow_submission:
                preview = v_dir / ("apply-preview.png" if mode == "dry-run" else "form-review.png")
                page.screenshot(path=str(preview), full_page=True)
                return SubmissionReceipt(
                    success=True, driver_name=driver.name, job_url=target_url,
                    applied_at=datetime.now(timezone.utc).isoformat(),
                    confirmation_text="Form preview saved; no submission attempted",
                    screenshot_path=str(preview), submitted=False,
                )
            if sys.stdin and sys.stdin.isatty():
                print("Review the browser. Press ENTER to submit, or type cancel to abort: ", end="", flush=True)
                if input().strip():
                    return SubmissionReceipt(
                        success=False, driver_name=driver.name, job_url=target_url,
                        applied_at=datetime.now(timezone.utc).isoformat(),
                        error_message="Submission cancelled by user",
                    )
            else:
                print("Non-interactive mode with submissions enabled: proceeding to submit...")
            guard.check(page)
            before = confirmation_messages(page)
            receipt = SubmissionReceipt(
                success=False, submitted=False, driver_name=driver.name,
                job_url=target_url, applied_at=datetime.now(timezone.utc).isoformat(),
                error_message="Submission attempt started; outcome unconfirmed",
            )
            def save_attempt() -> None:
                payload = receipt.to_dict()
                payload.update(submission_attempted=True, browser_backend=browser_backend,
                               documents={name: {"path": str(path), "sha256": hashes[name]}
                                          for name, path in documents.items()})
                receipt_path.write_text(json.dumps(payload, indent=2) + "\n")
            # Persist intent before any final click, including process crashes.
            save_attempt()
            try:
                driver.submit(page=page, job_url=target_url)
                guard.check(page)
                fresh = confirmation_messages(page) - before
                receipt.success = receipt.submitted = bool(fresh)
                receipt.confirmation_text = "\n".join(sorted(fresh)) if fresh else None
                receipt.error_message = None if fresh else "Submission unconfirmed; do not retry without checking employer history"
                screenshot = v_dir / "submission-confirmation.png"
                page.screenshot(path=str(screenshot), full_page=True)
                receipt.screenshot_path = str(screenshot)
            except Exception as exc:
                receipt.error_message = f"Submission unconfirmed ({type(exc).__name__}); check employer history before retrying"
            finally:
                save_attempt()
                current_meta["status"] = "APPLIED" if receipt.submitted else "SUBMISSION_UNCONFIRMED"
                if receipt.submitted:
                    current_meta["applied_at"] = receipt.applied_at
                current_path.write_text(json.dumps(current_meta, indent=2) + "\n")
            return receipt


def confirmation_messages(page: Any) -> set[str]:
    """Accept visible application acknowledgements, not URL or click scores."""
    text = page.locator("body").inner_text(timeout=2000)
    pattern = re.compile(
        r"(?:your\s+)?application\s+(?:(?:has\s+been|was)\s+)?(?:successfully\s+)?(?:submitted|received)"
        r"|thank\s+you\s+for\s+(?:applying|your\s+application)"
        r"|we(?:'ve|\s+have)?\s+received\s+your\s+application"
        r"|nous\s+avons\s+(?:bien\s+)?reçu\s+votre\s+candidature"
        r"|votre\s+candidature\s+(?:a\s+(?:bien\s+)?été|est\s+bien)\s+(?:enregistrée|reçue|transmise|envoyée|prise\s+en\s+compte)"
        r"|merci\s+d['’]avoir\s+postulé", re.IGNORECASE,
    )
    return {match.group(0).lower() for match in pattern.finditer(text)}
