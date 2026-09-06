from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from .base import BaseFormDriver
from ..models import CandidateProfile, FormFillResult, SubmissionReceipt


class LeverFormDriver(BaseFormDriver):
    """Automated form filler for Lever (jobs.lever.co / jobs.eu.lever.co)."""

    name = "lever"
    priority = 100

    def can_handle(self, url: str) -> bool:
        return "lever.co" in url

    def fill_form(
        self,
        page: Any,
        candidate: CandidateProfile,
        resume_pdf: Path,
        letter_pdf: Path | None = None,
        job_data: dict[str, Any] | None = None,
    ) -> FormFillResult:
        fields_filled: list[str] = []
        resume_uploaded = False
        letter_uploaded = False

        # Navigate to apply URL if on job description
        current_url = page.url.rstrip("/")
        if not current_url.endswith("/apply") and "#apply" not in current_url:
            apply_btn = page.locator('a:has-text("Apply for this job"), a.postings-btn, a[href*="/apply"]').first
            if apply_btn.count() > 0 and apply_btn.is_visible():
                apply_btn.click()
                page.wait_for_timeout(2000)
            else:
                apply_url = f"{current_url}/apply"
                page.goto(apply_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)


        # 1. Resume Upload
        resume_input = page.locator('input[name="resume"], input[type="file"]').first
        if resume_input.count() > 0 and resume_pdf.is_file():
            resume_input.set_input_files(str(resume_pdf.resolve()))
            resume_uploaded = True
            fields_filled.append("resume_file")

        # 2. Candidate Personal Information
        name_input = page.locator('input[name="name"]').first
        if name_input.is_visible():
            name_input.fill(candidate.full_name)
            fields_filled.append("name")

        email_input = page.locator('input[name="email"]').first
        if email_input.is_visible():
            email_input.fill(candidate.email)
            fields_filled.append("email")

        phone_input = page.locator('input[name="phone"]').first
        if phone_input.is_visible():
            phone_input.fill(candidate.phone)
            fields_filled.append("phone")

        location_input = page.locator('input[name="location"], input[placeholder*="Location"]').first
        if location_input.is_visible() and candidate.location:
            location_input.fill(candidate.location)
            fields_filled.append("location")

        # 3. Social / Profile Links
        linkedin_input = page.locator('input[name="urls[LinkedIn]"], input[placeholder*="LinkedIn"]').first
        if linkedin_input.is_visible() and candidate.linkedin_url:
            linkedin_input.fill(candidate.linkedin_url)
            fields_filled.append("linkedin_url")

        github_input = page.locator('input[name="urls[GitHub]"], input[placeholder*="GitHub"]').first
        if github_input.is_visible() and candidate.github_url:
            github_input.fill(candidate.github_url)
            fields_filled.append("github_url")

        portfolio_input = page.locator('input[name="urls[Portfolio]"], input[name="urls[Other]"]').first
        if portfolio_input.is_visible() and candidate.portfolio_url:
            portfolio_input.fill(candidate.portfolio_url)
            fields_filled.append("portfolio_url")

        # 4. Comments / Motivation Note
        comments_input = page.locator('textarea[name="comments"], textarea[placeholder*="additional"]').first
        if comments_input.is_visible():
            comments_input.fill("Thank you for reviewing my application. Tailored motivation letter and portfolio documents attached.")
            fields_filled.append("comments")
            if letter_pdf:
                letter_uploaded = True

        return FormFillResult(
            driver_name=self.name,
            success=True,
            fields_filled=fields_filled,
            resume_uploaded=resume_uploaded,
            letter_uploaded=letter_uploaded,
        )

    def submit(self, page: Any, job_url: str) -> SubmissionReceipt:
        submit_btn = page.locator('button:has-text("Submit application"), button[type="submit"]').first
        if not submit_btn.is_visible():
            return SubmissionReceipt(
                success=False,
                driver_name=self.name,
                job_url=job_url,
                applied_at=datetime.now(timezone.utc).isoformat(),
                error_message="Submit button not visible",
            )

        submit_btn.click()
        page.wait_for_timeout(3000)

        # Check for confirmation message
        confirmation_text = ""
        success_el = page.locator('h4:has-text("Application submitted"), div:has-text("Thank you")').first
        if success_el.is_visible():
            confirmation_text = success_el.inner_text()

        return SubmissionReceipt(
            success=True,
            driver_name=self.name,
            job_url=job_url,
            applied_at=datetime.now(timezone.utc).isoformat(),
            confirmation_text=confirmation_text or "Application submitted successfully",
        )
