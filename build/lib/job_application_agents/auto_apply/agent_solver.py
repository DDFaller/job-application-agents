from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import time
from typing import Any

from .draft_models import ApplicationDraft, ApplicationState, FieldType, VerificationScore
from .models import CandidateProfile, FormFillResult
from .verifier import SubmissionVerifier

logger = logging.getLogger(__name__)


class AgentFormSolver:
    """Agentic multi-step DOM solver that iteratively navigates, fills, and confirms ATS forms."""

    # Intermediate Step Progression Buttons (English & French)
    INTERMEDIATE_BUTTON_PATTERNS = [
        r"^(next|continue|continuer|suivant|étape\s+suivante|step\s+\d+|proceed|save\s+and\s+continue|review|vérifier|consulter)$",
        r"(next\s+step|continue\s+to\s+next|continuer\s+vers|étape\s+suivante)",
    ]

    # Final Submit Buttons (English & French)
    FINAL_SUBMIT_BUTTON_PATTERNS = [
        r"^(submit|submit\s+application|postuler|confirmer\s+ma\s+candidature|envoyer\s+ma\s+candidature|envoyer|complete\s+submission|confirmer)$",
        r"(submit\s+application|envoyer\s+la\s+candidature|confirmer\s+et\s+envoyer|valider\s+la\s+candidature)",
    ]

    @classmethod
    def solve_multistep_application(
        cls,
        page: Any,
        draft: ApplicationDraft,
        max_steps: int = 8,
    ) -> tuple[bool, VerificationScore, str | None, str | None]:
        """Execute iterative multi-step form solving, file attachments, and confirmation verification."""
        initial_url = page.url
        logger.info(f"🤖 Starting Agentic Multi-Step Form Solver for {draft.company} - {draft.job_title} ({draft.target_url})")

        # 1. Dismiss any blocking cookie consent dialogs
        cls._dismiss_cookie_banners(page)

        # 2. Check if vacancy has expired / closed on employer portal
        if cls.is_job_expired(page):
            logger.warning(f"⚠️ Job opening has EXPIRED / CLOSED on employer portal: {draft.target_url}")
            return False, VerificationScore(redirect_detected=False, success_text_found=False, confirmation_id=None, submit_button_gone=True, network_success=False), "EXPIRED", "Vacancy has expired on employer portal."

        # 3. Check if we need to click an initial "Apply" or "Postuler" CTA on a landing page
        cls._handle_initial_apply_cta(page)

        resume_uploaded = False
        letter_uploaded = False

        for step_idx in range(1, max_steps + 1):
            logger.info(f"--- [Step {step_idx}/{max_steps}] Analyzing active page DOM ---")
            page.wait_for_timeout(1000)

            # Check if authentication/login wall is present
            is_auth, auth_detail = cls.detect_auth_wall(page)
            if is_auth:
                logger.warning(f"🔒 Authentication Wall Detected on {draft.company}: {auth_detail} (URL: {page.url})")
                return False, VerificationScore(redirect_detected=False, success_text_found=False, confirmation_id=None, submit_button_gone=False, network_success=False), "AUTH_REQUIRED", auth_detail

            # Check if CAPTCHA / Cloudflare Turnstile challenge is present
            is_captcha, captcha_detail = cls.detect_captcha(page)
            if is_captcha:
                logger.warning(f"🧩 CAPTCHA Challenge Detected on {draft.company}: {captcha_detail} (URL: {page.url})")
                return False, VerificationScore(redirect_detected=False, success_text_found=False, confirmation_id=None, submit_button_gone=False, network_success=False), "CAPTCHA_DETECTED", captcha_detail

            # Check if confirmation screen was already reached
            score = SubmissionVerifier.evaluate(page, initial_url=initial_url)
            if score.total_score >= 60:
                logger.info(f"🎉 Confirmation detected on Step {step_idx}! (Score: {score.total_score})")
                return True, score, None, None

            # A. Populate all visible fields on current step
            cls._fill_visible_step_fields(page, draft)

            # B. Upload Resume & Motivation Letter if file inputs are visible on this step
            if not resume_uploaded and draft.resume_path and Path(draft.resume_path).is_file():
                resume_uploaded = cls._upload_file(page, draft.resume_path, "resume")

            if not letter_uploaded and draft.letter_path and Path(draft.letter_path).is_file():
                letter_uploaded = cls._upload_file(page, draft.letter_path, "letter")

            # C. Check required agreement/consent checkboxes (terms & privacy)
            cls._check_consent_boxes(page)

            # D. Evaluate Navigation Controls (Intermediate vs Final Submit)
            action_taken = cls._advance_or_submit(page)

            if action_taken == "final_submit":
                logger.info("🚀 Clicked final submit button. Waiting and polling for true confirmation...")
                # Poll for up to 15 seconds for confirmation signals
                for _ in range(15):
                    page.wait_for_timeout(1000)
                    score = SubmissionVerifier.evaluate(page, initial_url=initial_url)
                    if score.total_score >= 60:
                        logger.info(f"✅ Verified submission confirmation! Score: {score.total_score} (ID: {score.confirmation_id})")
                        return True, score, None, None
                # Return whatever score was achieved
                final_score = SubmissionVerifier.evaluate(page, initial_url=initial_url)
                if final_score.total_score < 60:
                    val_errs = cls.detect_validation_errors(page)
                    if val_errs:
                        return False, final_score, "VALIDATION_ERROR", f"Validation errors on submit: {'; '.join(val_errs)}"
                return final_score.total_score >= 60, final_score, None, None

            elif action_taken == "intermediate_next":
                logger.info("➡️ Advanced to next form step. Waiting for DOM transition...")
                try:
                    page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    page.wait_for_timeout(2000)
                val_errs = cls.detect_validation_errors(page)
                if val_errs:
                    logger.warning(f"Validation warnings on step {step_idx}: {val_errs}")

            elif action_taken == "none":
                logger.info("No explicit next/submit button detected on this step. Checking for confirmation...")
                score = SubmissionVerifier.evaluate(page, initial_url=initial_url)
                if score.total_score >= 60:
                    return True, score, None, None
                val_errs = cls.detect_validation_errors(page)
                if val_errs:
                    return False, score, "VALIDATION_ERROR", f"Form validation errors: {'; '.join(val_errs)}"
                break

        final_score = SubmissionVerifier.evaluate(page, initial_url=initial_url)
        return final_score.total_score >= 60, final_score, None, None



    @classmethod
    def _dismiss_cookie_banners(cls, page: Any) -> None:
        """Dismisses GDPR/cookie consent overlays if present."""
        cookie_selectors = [
            "#onetrust-accept-btn-handler",
            'button:has-text("Accept all cookies")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
            'button:has-text("Allow All")',
            'button:has-text("Tout accepter")',
            'button:has-text("Accepter")',
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
        ]
        for sel in cookie_selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    logger.info(f"Dismissing cookie consent banner: {sel}")
                    loc.click()
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass


    @classmethod
    def is_job_expired(cls, page: Any) -> bool:
        """Detects if job opening is marked as expired, closed, or no longer available."""
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=2000).lower()
        except Exception:
            return False

        expired_patterns = [
            "this vacancy has now expired",
            "this job is no longer available",
            "this position has been filled",
            "job has expired",
            "cette offre n'est plus disponible",
            "ce poste est pourvu",
            "l'offre a expiré",
            "l'offre d'emploi est clôturée",
        ]
        return any(pat in body_text for pat in expired_patterns)

    @classmethod
    def detect_auth_wall(cls, page: Any) -> tuple[bool, str]:
        """Detects if the page is an authentication / login / candidate registration wall."""
        url = page.url.lower()

        # Check URL patterns
        auth_url_patterns = [
            "/login",
            "/signin",
            "/auth",
            "/espacecandidat",
            "/account/login",
            "/session/new",
        ]
        if any(pat in url for pat in auth_url_patterns):
            return True, f"Navigated to authentication URL ({page.url})"

        # Check for password inputs
        try:
            password_inputs = page.locator('input[type="password"]')
            if password_inputs.count() > 0 and password_inputs.first.is_visible():
                return True, "Platform requires password authentication or account registration."
        except Exception:
            pass

        # Check for explicit candidate login/create account forms
        auth_btn_selectors = [
            'button:has-text("Se connecter")',
            'input[value*="Connexion"]',
            'button:has-text("Créer un compte")',
            'input[value*="CreateAccount"]',
            'input[id*="btnCreateAccount"]',
            'input[id*="btnConnexion"]',
            'a:has-text("FranceConnect")',
            'button:has-text("Sign in with")',
        ]
        for sel in auth_btn_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    return True, f"Authentication/Registration button detected: {sel}"
            except Exception:
                pass

        return False, ""

    @classmethod
    def detect_captcha(cls, page: Any) -> tuple[bool, str]:
        """Detects interactive CAPTCHAs or Cloudflare Turnstile challenges."""
        captcha_selectors = [
            'iframe[src*="recaptcha"]',
            'iframe[src*="hcaptcha"]',
            'iframe[src*="cloudflare"]',
            'iframe[src*="turnstile"]',
            'div.cf-turnstile',
            'div.g-recaptcha',
            'div.h-captcha',
            '[id*="captcha"]',
            '[class*="captcha"]',
        ]
        for sel in captcha_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    return True, f"Interactive verification challenge detected ({sel})"
            except Exception:
                pass
        return False, ""

    @classmethod
    def detect_validation_errors(cls, page: Any) -> list[str]:
        """Inspects DOM for visible inline form validation error messages."""
        error_selectors = [
            '[class*="error"]:not(:empty)',
            '[role="alert"]:not(:empty)',
            '[aria-invalid="true"]',
            '.field-validation-error',
            '.invalid-feedback',
            '.error-message',
        ]
        found_errors = []
        for sel in error_selectors:
            try:
                elements = page.locator(sel).all()
                for el in elements:
                    if el.is_visible():
                        txt = el.inner_text().strip()
                        if txt and len(txt) < 200 and txt not in found_errors:
                            found_errors.append(txt)
            except Exception:
                pass
        return found_errors

    @classmethod
    def _handle_initial_apply_cta(cls, page: Any) -> None:

        """Clicks landing page Apply/Postuler buttons or navigates to external ATS portal URLs."""
        apply_selectors = [
            'a:has-text("Postuler")',
            'button:has-text("Postuler")',
            'a:has-text("Candidater")',
            'button:has-text("Candidater")',
            'button:has-text("Apply for this job")',
            'a:has-text("Apply for this job")',
            'button:has-text("Apply Now")',
            'a:has-text("Apply Now")',
            'a[href*="/apply"]',
            'a[href*="jobapplication"]',
            'button:has-text("Apply")',
        ]
        for sel in apply_selectors:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                try:
                    href = loc.get_attribute("href")
                    if href and href.startswith("http"):
                        logger.info(f"Navigating directly to application portal target: {href}")
                        page.goto(href, wait_until="domcontentloaded")
                        page.wait_for_timeout(2500)
                        cls._dismiss_cookie_banners(page)
                        break
                    else:
                        logger.info(f"Opening application form via CTA: {sel}")
                        loc.click()
                        page.wait_for_timeout(2000)
                        break
                except Exception as e:
                    logger.warning(f"Could not activate CTA {sel}: {e}")


    @classmethod
    def _fill_visible_step_fields(cls, page: Any, draft: ApplicationDraft) -> None:
        """Discovers visible form controls and maps values from preprocessed draft fields."""
        fields_map = {f.id.lower(): f.value for f in draft.fields}

        js_extract = """
        () => {
            const controls = [];
            const elements = document.querySelectorAll('input:not([type="hidden"]), select, textarea');
            for (const el of elements) {
                if (el.style.display === 'none' || el.style.visibility === 'hidden' || el.type === 'submit' || el.type === 'button') {
                    continue;
                }
                let labelText = '';
                if (el.labels && el.labels.length > 0) labelText = el.labels[0].innerText;
                if (!labelText) {
                    const container = el.closest('div[class*="question"], div[class*="field"], div[class*="form-group"], [role="group"]') || el.parentElement;
                    if (container) {
                        const titleEl = container.querySelector('label, h3, h4, [class*="title"], [class*="label"]');
                        if (titleEl) labelText = titleEl.innerText;
                    }
                }
                controls.push({
                    tag: el.tagName.toLowerCase(),
                    type: (el.type || '').toLowerCase(),
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    label: (labelText || el.placeholder || el.getAttribute('aria-label') || '').trim(),
                    value: el.value || '',
                });
            }
            return controls;
        }
        """
        try:
            controls = page.evaluate(js_extract)
        except Exception:
            controls = []

        for c in controls:
            tag = c.get("tag")
            inp_type = c.get("type", "")
            label = c.get("label", "").lower()
            name = c.get("name", "").lower()
            elem_id = c.get("id", "")

            if inp_type in ("file", "checkbox", "radio"):
                continue

            target_sel = f'[id="{elem_id}"]' if elem_id else (f'{tag}[name="{c.get("name")}"]' if name else None)
            if not target_sel:
                continue

            loc = page.locator(target_sel).first
            if loc.count() == 0 or not loc.is_visible():
                continue

            # Resolve value to fill
            val = cls._match_candidate_value(c, draft, fields_map)
            if val:
                try:
                    if tag == "select":
                        loc.select_option(label=str(val))
                    else:
                        loc.fill(str(val))
                except Exception:
                    pass

    @classmethod
    def _match_candidate_value(cls, control: dict[str, Any], draft: ApplicationDraft, fields_map: dict[str, Any]) -> str | None:
        """Intelligently matches a visible control to candidate facts."""
        label = control.get("label", "").lower()
        name = control.get("name", "").lower()
        elem_id = control.get("id", "").lower()

        # Check explicit ID match
        if elem_id in fields_map:
            return fields_map[elem_id]
        if name in fields_map:
            return fields_map[name]

        # Name
        if ("name" in label or "nom" in label or "prénom" in label) and "company" not in label and "referrer" not in label and "user" not in label:
            candidate_name = fields_map.get("name")
            if not candidate_name:
                return None
            if "first" in label or "prénom" in label or "prenom" in label:
                return str(candidate_name).split(" ")[0]
            elif "last" in label or "nom de famille" in label:
                return str(candidate_name).split(" ")[-1]
            return str(candidate_name)

        # Email
        if control.get("type") == "email" or "email" in label or "courriel" in label or "e-mail" in label:
            return fields_map.get("email")

        # Phone
        if control.get("type") == "tel" or "phone" in label or "téléphone" in label or "telephone" in label or "mobile" in label:
            return fields_map.get("phone")

        # LinkedIn
        if "linkedin" in label or "linkedin" in name or "linkedin" in elem_id:
            return fields_map.get("linkedin")

        # GitHub
        if "github" in label or "github" in name or "github" in elem_id:
            return fields_map.get("github")

        # Portfolio / Website
        if "portfolio" in label or "website" in label or "site web" in label:
            return fields_map.get("portfolio")

        # Location / City
        if "location" in label or "ville" in label or "city" in label or "adresse" in label:
            return fields_map.get("location")

        # Custom fields search in draft
        for f in draft.fields:
            if f.label.lower() in label or label in f.label.lower():
                return f.value

        return None

    @classmethod
    def _upload_file(cls, page: Any, file_path: str, doc_type: str) -> bool:
        """Uploads a file to visible file inputs."""
        try:
            file_inputs = page.locator('input[type="file"]')
            count = file_inputs.count()
            if count > 0:
                for i in range(count):
                    fi = file_inputs.nth(i)
                    if fi.is_visible() or count == 1:
                        fi.set_input_files(str(Path(file_path).resolve()))
                        logger.info(f"Uploaded {doc_type} ({file_path}) to file input #{i+1}")
                        page.wait_for_timeout(1500)
                        return True
        except Exception as e:
            logger.warning(f"Could not upload {doc_type}: {e}")
        return False

    @classmethod
    def _check_consent_boxes(cls, page: Any) -> None:
        """Checks required policy and consent checkboxes."""
        try:
            checkboxes = page.locator('input[type="checkbox"]')
            for i in range(checkboxes.count()):
                cb = checkboxes.nth(i)
                if cb.is_visible() and not cb.is_checked():
                    cb.check()
                    logger.info(f"Checked consent checkbox #{i+1}")
        except Exception:
            pass

    @classmethod
    def _advance_or_submit(cls, page: Any) -> str:
        """Classifies buttons on the active step and clicks the appropriate navigation/submit button."""
        buttons = page.locator('button, input[type="submit"], input[type="button"], a[role="button"]')
        count = buttons.count()

        final_submit_candidate = None
        intermediate_candidate = None

        for i in range(count):
            btn = buttons.nth(i)
            if not btn.is_visible():
                continue
            text = (btn.inner_text() or btn.get_attribute("value") or "").strip().lower()
            btn_type = (btn.get_attribute("type") or "").lower()

            # Check final submit patterns
            for pat in cls.FINAL_SUBMIT_BUTTON_PATTERNS:
                if re.search(pat, text, re.IGNORECASE) or (btn_type == "submit" and "next" not in text and "suivant" not in text):
                    final_submit_candidate = btn
                    break

            if final_submit_candidate:
                break

            # Check intermediate step patterns
            for pat in cls.INTERMEDIATE_BUTTON_PATTERNS:
                if re.search(pat, text, re.IGNORECASE):
                    intermediate_candidate = btn
                    break

        if final_submit_candidate:
            final_submit_candidate.click()
            return "final_submit"

        if intermediate_candidate:
            intermediate_candidate.click()
            return "intermediate_next"

        return "none"


    # Legacy helper for single-step backward compatibility
    @staticmethod
    def solve_form(
        page: Any,
        candidate: CandidateProfile,
        resume_pdf: Path,
        letter_pdf: Path | None = None,
    ) -> FormFillResult:
        draft = ApplicationDraft(
            application_id="legacy",
            company="Legacy",
            job_title="Legacy",
            target_url=page.url,
            revision=1,
            resume_path=str(resume_pdf),
            letter_path=str(letter_pdf) if letter_pdf else None,
            fields=[],
        )
        success, score = AgentFormSolver.solve_multistep_application(page, draft)
        return FormFillResult(
            driver_name="agent-multistep-solver",
            success=success,
            fields_filled=["multistep_completed"],
            resume_uploaded=True,
            letter_uploaded=bool(letter_pdf),
        )
