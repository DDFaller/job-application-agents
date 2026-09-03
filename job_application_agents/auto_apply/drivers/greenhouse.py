from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BaseFormDriver
from ..models import CandidateProfile, FormFillResult, SubmissionReceipt


class GreenhouseFormDriver(BaseFormDriver):
    """Automated form filler for Greenhouse (boards.greenhouse.io)."""

    name = "greenhouse"
    priority = 100

    def can_handle(self, url: str) -> bool:
        return "greenhouse.io" in url

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

        # First Name / Last Name
        first_name_input = page.locator('#first_name, input[name="first_name"]').first
        if first_name_input.is_visible():
            first_name_input.fill(candidate.first_name)
            fields_filled.append("first_name")

        last_name_input = page.locator('#last_name, input[name="last_name"]').first
        if last_name_input.is_visible():
            last_name_input.fill(candidate.last_name)
            fields_filled.append("last_name")

        email_input = page.locator('#email, input[name="email"]').first
        if email_input.is_visible():
            email_input.fill(candidate.email)
            fields_filled.append("email")

        phone_input = page.locator('#phone, input[name="phone"]').first
        if phone_input.is_visible():
            phone_input.fill(candidate.phone)
            fields_filled.append("phone")

        # Resume Upload
        resume_input = page.locator('input[type="file"][data-field="resume"], input#resume').first
        if resume_input.count() > 0 and resume_pdf.is_file():
            resume_input.set_input_files(str(resume_pdf.resolve()))
            resume_uploaded = True
            fields_filled.append("resume_file")

        # Cover Letter Upload
        letter_input = page.locator('input[type="file"][data-field="cover_letter"], input#cover_letter').first
        if letter_input.count() > 0 and letter_pdf and letter_pdf.is_file():
            letter_input.set_input_files(str(letter_pdf.resolve()))
            letter_uploaded = True
            fields_filled.append("cover_letter_file")

        # LinkedIn & Website
        linkedin_input = page.locator('input[id*="linkedin"], input[name*="linkedin"]').first
        if linkedin_input.is_visible() and candidate.linkedin_url:
            linkedin_input.fill(candidate.linkedin_url)
            fields_filled.append("linkedin_url")

        website_input = page.locator('input[id*="website"], input[name*="website"]').first
        if website_input.is_visible() and (candidate.github_url or candidate.portfolio_url):
            website_input.fill(candidate.portfolio_url or candidate.github_url)
            fields_filled.append("website_url")

        return FormFillResult(
            driver_name=self.name,
            success=True,
            fields_filled=fields_filled,
            resume_uploaded=resume_uploaded,
            letter_uploaded=letter_uploaded,
        )

    def submit(self, page: Any, job_url: str) -> SubmissionReceipt:
        submit_btn = page.locator('#submit_app, button[type="submit"]:has-text("Submit Application")').first
        if not submit_btn.is_visible():
            return SubmissionReceipt(
                success=False,
                driver_name=self.name,
                job_url=job_url,
                applied_at=datetime.now(timezone.utc).isoformat(),
                error_message="Submit button not visible on Greenhouse form",
            )

        submit_btn.click()
        page.wait_for_timeout(3000)

        confirmation_text = ""
        success_el = page.locator('#application_confirmation, h1:has-text("Thank you")').first
        if success_el.is_visible():
            confirmation_text = success_el.inner_text()

        return SubmissionReceipt(
            success=True,
            driver_name=self.name,
            job_url=job_url,
            applied_at=datetime.now(timezone.utc).isoformat(),
            confirmation_text=confirmation_text or "Application submitted",
        )
