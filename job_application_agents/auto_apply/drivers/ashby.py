from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from .base import BaseFormDriver
from ..interaction import form_input
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
        inputs = form_input(page)
        fields_filled: list[str] = []
        resume_uploaded = False
        letter_uploaded = False

        # If on overview page, click Apply button
        apply_btn = page.locator('button:has-text("Apply for this job"), a:has-text("Apply for this job")').first
        if apply_btn.is_visible():
            apply_btn.click()
            page.wait_for_timeout(2000)

        # 1. Resume File Upload
        file_input = page.locator('input#_systemfield_resume').first
        if file_input.count() == 0:
            file_input = page.locator('input[type="file"]').first
        if file_input.count() > 0 and resume_pdf.is_file():
            inputs.upload("file_input", file_input, resume_pdf)
            resume_uploaded = True
            fields_filled.append("resume_file")
            page.wait_for_timeout(1500)

        # Optional Cover Letter File Upload
        if letter_pdf and letter_pdf.is_file():
            other_file_inputs = page.locator('input[type="file"]').all()
            for ofi in other_file_inputs:
                ofi_id = ofi.get_attribute("id") or ""
                if ofi_id != "_systemfield_resume" and ofi.is_visible():
                    inputs.upload("letter_file", ofi, letter_pdf)
                    letter_uploaded = True
                    fields_filled.append("letter_file")
                    page.wait_for_timeout(1000)
                    break

        # 2. Standard System Fields (Name, Email, Phone)
        name_input = page.locator('input#_systemfield_name, input[name="_systemfield_name"], input[autocomplete="name"]').first
        if name_input.count() > 0 and name_input.is_visible():
            inputs.text("name_input", name_input, candidate.full_name)
            fields_filled.append("name")

        email_input = page.locator('input#_systemfield_email, input[name="_systemfield_email"], input[type="email"]').first
        if email_input.count() > 0 and email_input.is_visible():
            inputs.text("email_input", email_input, candidate.email)
            fields_filled.append("email")

        phone_input = page.locator('input#_systemfield_phoneNumber, input[name*="phone" i], input[type="tel"]').first
        if phone_input.count() > 0 and phone_input.is_visible():
            inputs.text("phone_input", phone_input, candidate.phone)
            fields_filled.append("phone")

        # 3. Dynamic Question & Label Solver for Custom / UUID Fields
        # Ashby renders questions in field entry containers with title labels
        question_locators = page.locator(
            '[class*="fieldEntry"], [class*="ashby-application-form-field-entry"], '
            '[class*="ashby-application-form-question"], [class*="_question_"]'
        )
        count = question_locators.count()

        for idx in range(count):
            q = question_locators.nth(idx)
            title_loc = q.locator('.ashby-application-form-question-title, label, h3, [class*="_heading_"]').first
            if not title_loc.count() or not title_loc.is_visible():
                continue

            title_text = title_loc.inner_text().strip().lower()

            # Check LinkedIn
            if "linkedin" in title_text:
                inp = q.locator('input[type="text"]').first
                if inp.count() > 0 and inp.is_visible() and candidate.linkedin_url:
                    inputs.text(title_text, inp, candidate.linkedin_url)
                    fields_filled.append("linkedin_url")

            # Check GitHub
            elif "github" in title_text and "other links" not in title_text:
                inp = q.locator('input[type="text"]').first
                if inp.count() > 0 and inp.is_visible() and candidate.github_url:
                    inputs.text(title_text, inp, candidate.github_url)
                    fields_filled.append("github_url")

            # Check Portfolio / Website / Other links
            elif "portfolio" in title_text or "website" in title_text or "other links" in title_text:
                inp = q.locator('input[type="text"]').first
                if inp.count() > 0 and inp.is_visible():
                    links = []
                    if candidate.github_url:
                        links.append(candidate.github_url)
                    if candidate.portfolio_url:
                        links.append(candidate.portfolio_url)
                    combined_links = " | ".join(links) if links else (candidate.github_url or candidate.portfolio_url or "")
                    if combined_links:
                        inputs.text(title_text, inp, combined_links)
                        fields_filled.append("other_links")

            # Check Language proficiency checkboxes
            elif "languages" in title_text:
                for lang in ("English", "Portuguese"):
                    chk = q.locator(f'label:has-text("{lang}"), [name*="{lang}" i]').first
                    if chk.count() and chk.is_visible():
                        inputs.click(f"language_{lang.lower()}", chk)
                        fields_filled.append(f"language_{lang.lower()}")

            # Sensitive commitments are never guessed from default values.
            # Only an explicitly supplied answer to this exact question is used.
            else:
                matched_answer = None
                if title_text in candidate.custom_answers:
                    matched_answer = str(candidate.custom_answers[title_text])
                else:
                    for custom_q, custom_a in candidate.custom_answers.items():
                        if custom_q.lower() in title_text or title_text in custom_q.lower():
                            matched_answer = str(custom_a)
                            break

                if matched_answer and matched_answer.lower() in {"yes", "no"}:
                    ans_lower = matched_answer.lower()
                    btn = q.locator(f'button[data-option="{ans_lower}"]').first
                    if btn.count() and btn.is_visible():
                        inputs.click(title_text, btn)
                        fields_filled.append(title_text)
                    else:
                        choice = q.get_by_text(matched_answer, exact=True).first
                        if choice.count() and choice.is_visible():
                            inputs.click(title_text, choice)
                            fields_filled.append(title_text)

        # 4. Data consent acknowledgment if present
        consent_btn = page.locator('label:has-text("I agree"), input[name*="consent" i]').first
        if consent_btn.count() and consent_btn.is_visible():
            inputs.click("data_consent", consent_btn)
            fields_filled.append("data_consent")

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

        try:
            submit_btn.click()
        except Exception:
            submit_btn.click(force=True)
        page.wait_for_timeout(5000)

        confirmation_text = ""
        success_el = page.locator(
            'h3:has-text("Application Submitted"), div:has-text("Thank you"), '
            'div:has-text("submitted"), div:has-text("received"), '
            'h1:has-text("Application Submitted"), h2:has-text("Application Submitted")'
        ).first
        if success_el.count() and success_el.is_visible():
            confirmation_text = success_el.inner_text()

        return SubmissionReceipt(
            success=True,
            driver_name=self.name,
            job_url=job_url,
            applied_at=datetime.now(timezone.utc).isoformat(),
            confirmation_text=confirmation_text or "Application submitted",
        )
