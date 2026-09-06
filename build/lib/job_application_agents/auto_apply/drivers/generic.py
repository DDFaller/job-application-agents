from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import BaseFormDriver
from ..models import CandidateProfile, FormFillResult, SubmissionReceipt


class GenericFormDriver(BaseFormDriver):
    """Fallback form driver for generic employer career pages and unknown ATS systems."""

    name = "generic"
    priority = 10

    def can_handle(self, url: str) -> bool:
        return True  # Fallback for any URL

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

        # Attempt to find common input fields by type, autocomplete, or placeholder
        # 1. Name
        name_input = page.locator('input[autocomplete="name"], input[name*="name"], input[placeholder*="Name"]').first
        if name_input.count() > 0 and name_input.is_visible():
            name_input.fill(candidate.full_name)
            fields_filled.append("name")

        # 2. Email
        email_input = page.locator('input[type="email"], input[name*="email"], input[placeholder*="email" i]').first
        if email_input.count() > 0 and email_input.is_visible():
            email_input.fill(candidate.email)
            fields_filled.append("email")

        # 3. Phone
        phone_input = page.locator('input[type="tel"], input[name*="phone"], input[placeholder*="phone" i]').first
        if phone_input.count() > 0 and phone_input.is_visible():
            phone_input.fill(candidate.phone)
            fields_filled.append("phone")

        # 4. Resume File Upload
        file_input = page.locator('input[type="file"]').first
        if file_input.count() > 0 and resume_pdf.is_file():
            file_input.set_input_files(str(resume_pdf.resolve()))
            resume_uploaded = True
            fields_filled.append("resume_file")

        # 5. LinkedIn / Social
        linkedin_input = page.locator('input[name*="linkedin" i], input[placeholder*="linkedin" i]').first
        if linkedin_input.count() > 0 and linkedin_input.is_visible() and candidate.linkedin_url:
            linkedin_input.fill(candidate.linkedin_url)
            fields_filled.append("linkedin_url")

        return FormFillResult(
            driver_name=self.name,
            success=len(fields_filled) > 0,
            fields_filled=fields_filled,
            resume_uploaded=resume_uploaded,
            letter_uploaded=letter_uploaded,
        )

    def submit(self, page: Any, job_url: str) -> SubmissionReceipt:
        submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Submit")').first
        if not submit_btn.is_visible():
            return SubmissionReceipt(
                success=False,
                driver_name=self.name,
                job_url=job_url,
                applied_at=datetime.now(timezone.utc).isoformat(),
                error_message="Submit button not found",
            )

        submit_btn.click()
        page.wait_for_timeout(3000)

        return SubmissionReceipt(
            success=True,
            driver_name=self.name,
            job_url=job_url,
            applied_at=datetime.now(timezone.utc).isoformat(),
            confirmation_text="Submitted via generic driver",
        )
