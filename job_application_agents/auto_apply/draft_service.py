from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from .draft_models import (
    ApplicationDraft,
    ApplicationField,
    ApplicationState,
    ApprovalToken,
    FieldSource,
    FieldType,
    VerificationScore,
)
from .models import CandidateProfile
from .preprocessor import FormDOMPreprocessor, FormFieldNode
from .verifier import SubmissionVerifier


class DraftService:
    """Manages ApplicationDraft extraction, revision incrementing, and hash-locked submission."""

    @classmethod
    def create_draft_from_page(
        cls,
        page: Any,
        application_id: str,
        company: str,
        job_title: str,
        candidate: CandidateProfile,
        resume_path: Path,
        letter_path: Path | None = None,
        revision: int = 1,
    ) -> ApplicationDraft:
        """Extract a structured ApplicationDraft from the live browser DOM."""
        tree = FormDOMPreprocessor.extract_from_page(page)
        fields: list[ApplicationField] = []

        for node in tree.fields:
            field_type = FieldType.TEXT
            node_type = (node.type or node.tag).lower()
            if node_type in ("textarea", "select", "radio", "checkbox", "file", "number"):
                field_type = FieldType(node_type)

            # Determine initial value and source attribution
            label_lower = node.label.lower()
            name_lower = node.name.lower()
            val: Any = ""
            source = FieldSource.PROFILE

            if ("name" in label_lower or "name" in name_lower) and "company" not in label_lower and "referrer" not in label_lower:
                if "first" in label_lower or "first" in name_lower:
                    val = candidate.first_name
                elif "last" in label_lower or "last" in name_lower:
                    val = candidate.last_name
                else:
                    val = candidate.full_name
                source = FieldSource.PROFILE

            elif node_type == "email" or "email" in label_lower or "email" in name_lower:
                val = candidate.email
                source = FieldSource.PROFILE

            elif node_type == "tel" or "phone" in label_lower or "phone" in name_lower:
                val = candidate.phone
                source = FieldSource.PROFILE

            elif "linkedin" in label_lower or "linkedin" in name_lower:
                val = candidate.linkedin_url
                source = FieldSource.PROFILE

            elif "github" in label_lower or "github" in name_lower:
                val = candidate.github_url
                source = FieldSource.PROFILE

            elif "portfolio" in label_lower or "website" in label_lower:
                val = candidate.portfolio_url or candidate.github_url
                source = FieldSource.PROFILE

            elif field_type == FieldType.FILE:
                val = str(resume_path.name)
                source = FieldSource.RESUME

            elif "authorized to work" in label_lower or "legal" in label_lower and "authorization" in label_lower:
                val = "Yes"
                source = FieldSource.PROFILE

            elif "sponsorship" in label_lower or "visa" in label_lower:
                val = "Yes" if candidate.requires_sponsorship else "No"
                source = FieldSource.PROFILE

            elif "hybrid" in label_lower or "office" in label_lower or "onsite" in label_lower:
                val = "Yes"
                source = FieldSource.PROFILE

            else:
                # Custom question or open-ended textarea
                if node.id in candidate.custom_answers:
                    val = candidate.custom_answers[node.id]
                    source = FieldSource.USER
                elif node.name in candidate.custom_answers:
                    val = candidate.custom_answers[node.name]
                    source = FieldSource.USER
                else:
                    val = ""
                    source = FieldSource.AI

            fields.append(
                ApplicationField(
                    id=node.id or node.name,
                    label=node.label or node.name,
                    type=field_type,
                    value=val,
                    options=node.options,
                    required=node.required,
                    source=source,
                )
            )

        draft = ApplicationDraft(
            application_id=application_id,
            company=company,
            job_title=job_title,
            target_url=tree.url,
            revision=revision,
            fields=fields,
            resume_path=str(resume_path.resolve()),
            letter_path=str(letter_path.resolve()) if letter_path else None,
            state=ApplicationState.REVIEW_READY,
        )

        return draft

    @classmethod
    def apply_edits_and_increment(
        cls,
        draft: ApplicationDraft,
        page: Any,
        field_updates: dict[str, Any],
    ) -> ApplicationDraft:
        """Apply user field updates to the DOM, re-extract, and produce an incremented revision."""
        updated_fields: list[ApplicationField] = []

        for f in draft.fields:
            key = f.id or f.label
            if key in field_updates:
                new_val = field_updates[key]
                # Apply change in browser DOM
                target_sel = f'[id="{f.id}"]' if f.id else f'[name="{f.id}"]'
                loc = page.locator(target_sel).first
                if loc.count() > 0:
                    input_type = (loc.get_attribute("type") or "").lower()
                    if input_type != "file" and f.type != FieldType.FILE and loc.is_visible():
                        if f.type == FieldType.CHECKBOX or f.type == FieldType.RADIO:
                            opt_loc = page.locator(f'label:has-text("{new_val}"), input[value="{new_val}"]').first
                            if opt_loc.count() > 0:
                                opt_loc.click()
                        else:
                            loc.fill(str(new_val))


                updated_fields.append(
                    ApplicationField(
                        id=f.id,
                        label=f.label,
                        type=f.type,
                        value=new_val,
                        options=f.options,
                        required=f.required,
                        source=FieldSource.USER,
                    )
                )
            else:
                updated_fields.append(f)

        new_draft = ApplicationDraft(
            application_id=draft.application_id,
            company=draft.company,
            job_title=draft.job_title,
            target_url=draft.target_url,
            revision=draft.revision + 1,
            fields=updated_fields,
            resume_path=draft.resume_path,
            letter_path=draft.letter_path,
            state=ApplicationState.READY_TO_APPROVE,
        )
        return new_draft

    @classmethod
    def execute_locked_submission(
        cls,
        page: Any,
        current_draft: ApplicationDraft,
        approval_token: ApprovalToken,
        version_dir: Path,
    ) -> tuple[ApplicationState, VerificationScore, str | None]:
        """Verify the cryptographic approval token, capture pre/post proof, and submit."""
        # 1. Cryptographic Lock Verification
        if approval_token.revision != current_draft.revision:
            raise ValueError(
                f"Approval revision mismatch: Approved Rev {approval_token.revision}, but current is Rev {current_draft.revision}"
            )
        if approval_token.draft_hash != current_draft.draft_hash:
            raise ValueError(
                f"Approval hash mismatch! Live form values have diverged from approved state."
            )

        # 2. Capture Pre-Submit Evidence Screenshot
        pre_submit_path = version_dir / "pre-submit.png"
        page.screenshot(path=str(pre_submit_path), full_page=True)

        # 3. Trigger Single Submission Action
        submit_btn = page.locator(
            'button:has-text("Submit Application"), button[type="submit"], input[type="submit"], button:has-text("Submit")'
        ).first
        if not submit_btn.is_visible():
            raise RuntimeError("Submit button is not visible or disabled on form.")

        submit_btn.click()
        page.wait_for_timeout(4000)

        # 4. Multi-Signal Verification
        score = SubmissionVerifier.evaluate(page, initial_url=current_draft.target_url)
        verdict = score.verdict

        # 5. Capture Post-Submit Proof Screenshot
        post_submit_name = "submission-success.png" if verdict == ApplicationState.SUBMITTED_CONFIRMED else "submission-uncertain.png"
        post_submit_path = version_dir / post_submit_name
        page.screenshot(path=str(post_submit_path), full_page=True)

        # 6. Archive Proof Metadata Package
        proof_package = {
            "application_id": current_draft.application_id,
            "company": current_draft.company,
            "job_title": current_draft.job_title,
            "target_url": current_draft.target_url,
            "approved_revision": approval_token.revision,
            "approved_hash": approval_token.draft_hash,
            "verdict": verdict.value,
            "verification_score": score.to_dict(),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "pre_submit_screenshot": str(pre_submit_path),
            "post_submit_screenshot": str(post_submit_path),
            "submitted_fields": [f.to_dict() for f in current_draft.fields],
        }

        (version_dir / "proof-package.json").write_text(
            json.dumps(proof_package, indent=2), encoding="utf-8"
        )

        return verdict, score, str(post_submit_path)
