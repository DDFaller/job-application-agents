from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from .base import BaseFormDriver
from ..models import CandidateProfile, FormFillResult, SubmissionReceipt


class AshbyFormDriver(BaseFormDriver):
    """Automated form filler for Ashby HQ (jobs.ashbyhq.com)."""

    name = "ashby"
    priority = 100

    def can_handle(self, url: str) -> bool:
        return "ashbyhq.com" in url

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

        # If on overview page, click Apply button
        apply_btn = page.locator('button:has-text("Apply for this job"), a:has-text("Apply for this job")').first
        if apply_btn.is_visible():
            apply_btn.click()
            page.wait_for_timeout(2000)

        # 1. Resume File Upload
        file_input = page.locator('input#_systemfield_resume, input[type="file"]').first
        if file_input.count() > 0 and resume_pdf.is_file():
            file_input.set_input_files(str(resume_pdf.resolve()))
            resume_uploaded = True
            fields_filled.append("resume_file")
            page.wait_for_timeout(1500)

        # 2. Standard System Fields (Name, Email, Phone)
        name_input = page.locator('input#_systemfield_name, input[name="_systemfield_name"], input[autocomplete="name"]').first
        if name_input.count() > 0 and name_input.is_visible():
            name_input.fill(candidate.full_name)
            fields_filled.append("name")

        email_input = page.locator('input#_systemfield_email, input[name="_systemfield_email"], input[type="email"]').first
        if email_input.count() > 0 and email_input.is_visible():
            email_input.fill(candidate.email)
            fields_filled.append("email")

        phone_input = page.locator('input#_systemfield_phoneNumber, input[name*="phone" i], input[type="tel"]').first
        if phone_input.count() > 0 and phone_input.is_visible():
            phone_input.fill(candidate.phone)
            fields_filled.append("phone")

        # 3. Dynamic Question & Label Solver for Custom / UUID Fields
        # Ashby renders questions in containers with titles
        question_locators = page.locator('[class*="ashby-application-form-question"], [class*="_question_"]')
        count = question_locators.count()

        for idx in range(count):
            q = question_locators.nth(idx)
            title_loc = q.locator('.ashby-application-form-question-title, label, h3, [class*="_heading_"]').first
            if not title_loc.is_visible():
                continue

            title_text = title_loc.inner_text().strip().lower()

            # Check LinkedIn
            if "linkedin" in title_text:
                inp = q.locator('input[type="text"]').first
                if inp.count() > 0 and inp.is_visible() and candidate.linkedin_url:
                    inp.fill(candidate.linkedin_url)
                    fields_filled.append("linkedin_url")

            # Check GitHub
            elif "github" in title_text:
                inp = q.locator('input[type="text"]').first
                if inp.count() > 0 and inp.is_visible() and candidate.github_url:
                    inp.fill(candidate.github_url)
                    fields_filled.append("github_url")

            # Check Portfolio / Website
            elif "portfolio" in title_text or "website" in title_text:
                inp = q.locator('input[type="text"]').first
                if inp.count() > 0 and inp.is_visible() and candidate.portfolio_url:
                    inp.fill(candidate.portfolio_url)
                    fields_filled.append("portfolio_url")

            # Check Work Authorization
            elif "authorized to work" in title_text or "legal" in title_text and "authorization" in title_text:
                yes_opt = q.locator('label:has-text("Yes"), button:has-text("Yes"), span:has-text("Yes")').first
                if yes_opt.count() > 0 and yes_opt.is_visible():
                    yes_opt.click()
                    fields_filled.append("work_authorization")

            # Check Visa Sponsorship
            elif "visa" in title_text or "sponsorship" in title_text:
                target_choice = "Yes" if candidate.requires_sponsorship else "No"
                opt = q.locator(f'label:has-text("{target_choice}"), button:has-text("{target_choice}"), span:has-text("{target_choice}")').first
                if opt.count() > 0 and opt.is_visible():
                    opt.click()
                    fields_filled.append(f"sponsorship_{target_choice.lower()}")

            # Check Hybrid / Office Work
            elif "hybrid" in title_text or "office" in title_text:
                yes_opt = q.locator('label:has-text("Yes"), button:has-text("Yes"), span:has-text("Yes")').first
                if yes_opt.count() > 0 and yes_opt.is_visible():
                    yes_opt.click()
                    fields_filled.append("hybrid_commitment")

        return FormFillResult(
            driver_name=self.name,
            success=len(fields_filled) > 0,
            fields_filled=fields_filled,
            resume_uploaded=resume_uploaded,
            letter_uploaded=letter_uploaded,
        )

    def submit(self, page: Any, job_url: str) -> SubmissionReceipt:
        submit_btn = page.locator('button:has-text("Submit Application"), button[type="submit"]').first
        if not submit_btn.is_visible():
            return SubmissionReceipt(
                success=False,
                driver_name=self.name,
                job_url=job_url,
                applied_at=datetime.now(timezone.utc).isoformat(),
                error_message="Submit button not found on Ashby form",
            )

        submit_btn.click()
        page.wait_for_timeout(4000)

        confirmation_text = ""
        success_el = page.locator('h3:has-text("Application Submitted"), div:has-text("Thank you")').first
        if success_el.is_visible():
            confirmation_text = success_el.inner_text()

        return SubmissionReceipt(
            success=True,
            driver_name=self.name,
            job_url=job_url,
            applied_at=datetime.now(timezone.utc).isoformat(),
            confirmation_text=confirmation_text or "Application submitted",
        )
