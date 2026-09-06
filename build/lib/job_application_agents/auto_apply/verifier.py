from __future__ import annotations

import re
from typing import Any

from .draft_models import ApplicationState, VerificationScore


class SubmissionVerifier:
    """Evaluates submission outcomes using an expanded multi-signal scoring matrix (French & English)."""

    CONFIRMATION_URL_PATTERNS = [
        r"/thank[-_]?you",
        r"/confirmation",
        r"/success",
        r"/submitted",
        r"/application[-_]?received",
        r"/applied",
        r"/merci",
        r"/candidature[-_]?(transmise|validee|enregistree)",
        r"/complete",
        r"/status",
    ]

    SUCCESS_TEXT_PATTERNS = [
        r"application\s+(has\s+been\s+)?(successfully\s+)?(submitted|received|completed)",
        r"thank\s+you\s+for\s+(applying|your\s+application|your\s+interest)",
        r"we('ve|\s+have)\s+received\s+your\s+application",
        r"your\s+application\s+is\s+(now\s+)?complete",
        r"application\s+received",
        r"votre\s+candidature\s+(a\s+bien\s+été|est\s+bien|a\s+été)\s+(enregistrée|prise\s+en\s+compte|transmise|envoyée|validée|soumise)",
        r"candidature\s+(enregistrée|transmise|envoyée|validée|soumise|bien\s+reçue)",
        r"nous\s+avons\s+bien\s+reçu\s+votre\s+candidature",
        r"merci\s+(pour|de)\s+votre\s+(candidature|intérêt)",
        r"merci\s+d['’]avoir\s+postulé",
        r"dossier\s+de\s+candidature\s+transmis",
    ]

    CONFIRMATION_ID_PATTERNS = [
        r"(?:confirmation|application|reference|candidate|numéro\s+de\s+dossier|référence)\s*(?:id|number|#|ref|n°)?\s*[:\-#]\s*([A-Za-z0-9\-]{5,30})",
        r"(?:ref|id|n°)\s*[:#]\s*([A-Za-z0-9\-]{5,20})",
    ]

    @classmethod
    def evaluate(
        cls,
        page: Any,
        initial_url: str,
        network_status_200: bool = False,
    ) -> VerificationScore:
        """Run multi-signal verification against the live browser state."""
        current_url = page.url.lower()
        clean_initial = initial_url.lower().rstrip("/")

        # 1. URL Redirect Analysis
        redirect_detected = False
        for pattern in cls.CONFIRMATION_URL_PATTERNS:
            if re.search(pattern, current_url):
                redirect_detected = True
                break
        if not redirect_detected and clean_initial.endswith("/apply") and not current_url.endswith("/apply"):
            redirect_detected = True

        # 2. DOM Success Text Analysis
        dom_text_raw = ""
        try:
            dom_text_raw = page.locator("body").inner_text(timeout=2000)
        except Exception:
            pass

        dom_text = dom_text_raw.lower()

        success_text_found = False
        for pattern in cls.SUCCESS_TEXT_PATTERNS:
            if re.search(pattern, dom_text, re.IGNORECASE):
                success_text_found = True
                break

        # Check explicit confirmation heading tags if not matched in body
        if not success_text_found:
            try:
                headers = page.locator("h1, h2, h3, [role='alert'], [class*='success'], [class*='confirmation'], [class*='merci']").all_inner_texts()
                combined_headers = " ".join(headers).lower()
                for pattern in cls.SUCCESS_TEXT_PATTERNS:
                    if re.search(pattern, combined_headers, re.IGNORECASE):
                        success_text_found = True
                        break
            except Exception:
                pass

        # 3. Confirmation / Reference ID Detection
        confirmation_id = None
        for pattern in cls.CONFIRMATION_ID_PATTERNS:
            match = re.search(pattern, dom_text_raw, re.IGNORECASE)
            if match:
                confirmation_id = match.group(1).strip()
                break

        # 4. Submit Button State Analysis
        submit_button_gone = True
        try:
            submit_btn = page.locator('button[type="submit"], input[type="submit"], button:has-text("Submit"), button:has-text("Postuler"), button:has-text("Confirmer")').first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                submit_button_gone = False
        except Exception:
            submit_button_gone = True

        return VerificationScore(
            redirect_detected=redirect_detected,
            success_text_found=success_text_found,
            confirmation_id=confirmation_id,
            submit_button_gone=submit_button_gone,
            network_success=network_status_200,
        )
