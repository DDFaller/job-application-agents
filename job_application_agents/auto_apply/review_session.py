"""Durable, local human-in-the-loop control for a Playwright application.

The cloud Firestore review path remains available for existing deployments.  This
module provides the computer-local alternative: a Playwright page is kept alive
by a worker, while a small authenticated web service can inspect and approve one
form step at a time from a phone on the user's private network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken

from .agent_solver import AgentFormSolver
from .draft_models import (
    ApplicationDraft,
    ApplicationField,
    ApplicationState,
    FieldSource,
    FieldType,
)
from .draft_service import DraftService
from .models import CandidateProfile
from .preprocessor import FormDOMPreprocessor


class ReviewSessionError(RuntimeError):
    """Base class for recoverable review-session errors."""


class ReviewConflictError(ReviewSessionError):
    """The phone attempted to operate on an old draft revision."""


class ReviewBlockedError(ReviewSessionError):
    """The browser cannot safely continue without human intervention."""


@dataclass
class ReviewCheckpoint:
    """Encrypted, restart-safe state for the active browser session."""

    application_id: str
    company: str
    job_title: str
    target_url: str
    revision: int
    fields: list[dict[str, Any]]
    resume_path: str
    letter_path: str | None
    step_index: int = 1
    step_key: str = ""
    page_url: str = ""
    state: str = ApplicationState.REVIEW_READY.value
    blocker: str | None = None
    browser_profile_dir: str | None = None
    visible_field_ids: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def draft_hash(self) -> str:
        draft = ApplicationDraft(
            application_id=self.application_id,
            company=self.company,
            job_title=self.job_title,
            target_url=self.target_url,
            revision=self.revision,
            fields=[ApplicationField.from_dict(f) for f in self.fields],
            resume_path=self.resume_path,
            letter_path=self.letter_path,
        )
        return draft.draft_hash

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["draft_hash"] = self.draft_hash
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewCheckpoint":
        fields = [dict(value) for value in data.get("fields", [])]
        known = {
            "application_id", "company", "job_title", "target_url", "revision",
            "resume_path", "letter_path", "step_index", "step_key", "page_url",
            "state", "blocker", "browser_profile_dir", "updated_at", "fields",
            "visible_field_ids",
        }
        values = {key: data[key] for key in known if key in data and key != "fields"}
        return cls(**values, fields=fields)


class EncryptedCheckpointStore:
    """Store checkpoint JSON encrypted with a local Fernet key.

    The key may be supplied by ``JAA_REVIEW_KEY`` (a Fernet key or a base64
    string) or is generated in a mode-0600 file under the local data directory.
    This makes the default safe for a single-user computer while still allowing
    a deployment to inject its key from an OS secret store.
    """

    def __init__(self, root: Path, key: bytes | None = None):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.key_path = self.root / "review.key"
        self.checkpoint_path = self.root / "checkpoint.enc"
        self._lock = threading.RLock()
        self._fernet = Fernet(key or self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        supplied = os.environ.get("JAA_REVIEW_KEY", "").strip()
        if supplied:
            try:
                key = supplied.encode("ascii")
                Fernet(key)
                return key
            except Exception as exc:
                raise ValueError("JAA_REVIEW_KEY must be a valid Fernet key") from exc

        if self.key_path.is_file():
            key = self.key_path.read_bytes().strip()
            try:
                Fernet(key)
            except Exception as exc:
                raise ValueError(f"Invalid review key at {self.key_path}") from exc
            return key

        key = Fernet.generate_key()
        self.key_path.write_bytes(key + b"\n")
        os.chmod(self.key_path, 0o600)
        return key

    def save(self, checkpoint: ReviewCheckpoint) -> None:
        payload = json.dumps(checkpoint.to_dict(), sort_keys=True).encode("utf-8")
        encrypted = self._fernet.encrypt(payload)
        tmp = self.checkpoint_path.with_suffix(".enc.tmp")
        with self._lock:
            tmp.write_bytes(encrypted)
            os.chmod(tmp, 0o600)
            tmp.replace(self.checkpoint_path)

    def load(self) -> ReviewCheckpoint | None:
        with self._lock:
            if not self.checkpoint_path.is_file():
                return None
            try:
                raw = self._fernet.decrypt(self.checkpoint_path.read_bytes())
                return ReviewCheckpoint.from_dict(json.loads(raw.decode("utf-8")))
            except (InvalidToken, json.JSONDecodeError, OSError) as exc:
                raise ReviewSessionError("Review checkpoint could not be decrypted or parsed") from exc

    def clear(self) -> None:
        with self._lock:
            self.checkpoint_path.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_step_key(page: Any) -> str:
    tree = FormDOMPreprocessor.extract_from_page(page)
    signature = "|".join(
        f"{field.id}:{field.name}:{field.label}:{field.type}"
        for field in tree.fields
    )
    return hashlib.sha256(f"{page.url}|{signature}".encode("utf-8")).hexdigest()[:16]


class PlaywrightReviewSession:
    """Own a Playwright page and expose safe step-level review operations."""

    def __init__(
        self,
        page: Any,
        draft: ApplicationDraft,
        candidate: CandidateProfile,
        store: EncryptedCheckpointStore,
        browser_profile_dir: Path | None = None,
        allow_submission: bool = False,
        on_change: Callable[[], None] | None = None,
    ):
        self.page = page
        self.draft = draft
        self.candidate = candidate
        self.store = store
        self.browser_profile_dir = str(browser_profile_dir) if browser_profile_dir else None
        self.allow_submission = allow_submission
        self.on_change = on_change
        self.step_index = 1
        self.step_key = ""
        self.state = ApplicationState.PREFILLING.value
        self.blocker: str | None = None
        self.visible_field_ids: list[str] = []
        self._lock = threading.RLock()

    def _notify(self) -> None:
        if self.on_change:
            self.on_change()

    def _checkpoint(self) -> None:
        checkpoint = ReviewCheckpoint(
            application_id=self.draft.application_id,
            company=self.draft.company,
            job_title=self.draft.job_title,
            target_url=self.draft.target_url,
            revision=self.draft.revision,
            fields=[field.to_dict() for field in self.draft.fields],
            resume_path=self.draft.resume_path,
            letter_path=self.draft.letter_path,
            step_index=self.step_index,
            step_key=self.step_key,
            page_url=self.page.url,
            state=self.state,
            blocker=self.blocker,
            browser_profile_dir=self.browser_profile_dir,
            visible_field_ids=list(self.visible_field_ids),
            updated_at=_now(),
        )
        self.store.save(checkpoint)
        self._notify()

    def _merge_visible_fields(self, visible: ApplicationDraft) -> None:
        # IDs/names are stable across reloads; labels may improve when the DOM
        # extractor replaces a generic input label with the real question.
        existing = {(field.id or field.label): field for field in self.draft.fields}
        for field in visible.fields:
            key = field.id or field.label
            if key in existing:
                current = existing[key]
                current.label = field.label
                current.value = field.value if not current.value else current.value
                current.required = field.required
                current.options = field.options
            else:
                self.draft.fields.append(field)

    def prepare_current_step(self) -> None:
        """Inspect and prefill the currently visible form step, then checkpoint."""
        with self._lock:
            self.state = ApplicationState.PREFILLING.value
            self.blocker = None
            AgentFormSolver._dismiss_cookie_banners(self.page)

            auth, auth_detail = AgentFormSolver.detect_auth_wall(self.page)
            captcha, captcha_detail = AgentFormSolver.detect_captcha(self.page)
            if auth or captcha:
                self.state = ApplicationState.BLOCKED.value
                self.blocker = auth_detail if auth else captcha_detail
                self.step_key = _stable_step_key(self.page)
                self.visible_field_ids = []
                self._checkpoint()
                return

            visible = DraftService.create_draft_from_page(
                page=self.page,
                application_id=self.draft.application_id,
                company=self.draft.company,
                job_title=self.draft.job_title,
                candidate=self.candidate,
                resume_path=Path(self.draft.resume_path),
                letter_path=Path(self.draft.letter_path) if self.draft.letter_path else None,
                revision=self.draft.revision,
            )
            self._merge_visible_fields(visible)
            self.draft.target_url = self.page.url
            self.step_key = _stable_step_key(self.page)
            self.visible_field_ids = [field.id or field.label for field in visible.fields]

            AgentFormSolver._fill_visible_step_fields(self.page, self.draft)
            if self.draft.resume_path and Path(self.draft.resume_path).is_file():
                AgentFormSolver._upload_file(self.page, self.draft.resume_path, "resume")
            if self.draft.letter_path and Path(self.draft.letter_path).is_file():
                AgentFormSolver._upload_file(self.page, self.draft.letter_path, "letter")
            AgentFormSolver._check_consent_boxes(self.page)
            self.state = ApplicationState.REVIEW_READY.value
            self._checkpoint()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            checkpoint = ReviewCheckpoint(
                application_id=self.draft.application_id,
                company=self.draft.company,
                job_title=self.draft.job_title,
                target_url=self.draft.target_url,
                revision=self.draft.revision,
                fields=[field.to_dict() for field in self.draft.fields],
                resume_path=self.draft.resume_path,
                letter_path=self.draft.letter_path,
                step_index=self.step_index,
                step_key=self.step_key,
                page_url=self.page.url,
                state=self.state,
                blocker=self.blocker,
                browser_profile_dir=self.browser_profile_dir,
                visible_field_ids=list(self.visible_field_ids),
            )
            snapshot = checkpoint.to_dict()
            if self.visible_field_ids:
                visible = set(self.visible_field_ids)
                snapshot["fields"] = [
                    field for field in snapshot["fields"]
                    if (field.get("id") or field.get("label")) in visible
                ]
            return snapshot

    def update_fields(self, expected_revision: int, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._assert_revision(expected_revision)
            changed = False
            for field in self.draft.fields:
                key = field.id or field.label
                if key not in updates:
                    continue
                value = updates[key]
                selector = f'[id="{field.id}"]' if field.id else f'[name="{key}"]'
                locator = self.page.locator(selector).first
                if locator.count() == 0 or not locator.is_visible():
                    raise ReviewSessionError(f"Field is not visible on the active step: {field.label}")
                if field.type == FieldType.FILE:
                    raise ReviewSessionError("File fields can only be changed by the computer worker")
                if field.type == FieldType.SELECT:
                    locator.select_option(label=str(value))
                elif field.type in {FieldType.CHECKBOX, FieldType.RADIO}:
                    locator.check()
                else:
                    locator.fill(str(value))
                field.value = value
                field.source = FieldSource.USER
                changed = True
            if not changed:
                raise ReviewSessionError("No editable fields matched the update")
            self.draft.revision += 1
            self.state = ApplicationState.USER_EDITING.value
            self._checkpoint()
            return self.snapshot()

    def approve_step(self, expected_revision: int, expected_hash: str) -> dict[str, Any]:
        with self._lock:
            self._assert_revision(expected_revision)
            if self.draft.draft_hash != expected_hash:
                raise ReviewConflictError("Draft hash does not match the active browser form")
            if self.state == ApplicationState.BLOCKED.value:
                raise ReviewBlockedError(self.blocker or "Browser session is blocked")

            self.state = ApplicationState.SYNCING_EDITS.value
            self._checkpoint()
            AgentFormSolver._check_consent_boxes(self.page)
            action = self._classify_navigation()

            if action == "none":
                errors = AgentFormSolver.detect_validation_errors(self.page)
                self.state = ApplicationState.BLOCKED.value
                self.blocker = "; ".join(errors) if errors else "No Next or Submit control was detected"
                self._checkpoint()
                raise ReviewBlockedError(self.blocker)

            if action == "final_submit":
                if not self.allow_submission or os.environ.get("JAA_ENABLE_SUBMISSION") != "I_UNDERSTAND_SUBMISSION":
                    self.state = ApplicationState.BLOCKED.value
                    self.blocker = "Final submission is disabled. Enable the explicit submission gate first."
                    self._checkpoint()
                    raise ReviewBlockedError(self.blocker)
                self.state = ApplicationState.SUBMITTING.value
                self._checkpoint()
                self._click_navigation(action)
                self.page.wait_for_timeout(3000)
                score = self._evaluate_submission()
                self.state = score.verdict.value
                self.blocker = None if score.total_score >= 60 else "Submission could not be confirmed"
                self._checkpoint()
                return self.snapshot()

            self._click_navigation(action)
            try:
                self.page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                self.page.wait_for_timeout(1200)
            self.step_index += 1
            self.draft.revision += 1
            self.prepare_current_step()
            return self.snapshot()

    def skip(self, expected_revision: int) -> dict[str, Any]:
        with self._lock:
            self._assert_revision(expected_revision)
            self.state = ApplicationState.SKIPPED.value
            self.blocker = "Skipped by user"
            self._checkpoint()
            return self.snapshot()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if self.state == ApplicationState.SKIPPED.value:
                raise ReviewSessionError("Skipped applications must be explicitly restarted")
            try:
                if self.page.url != self.draft.target_url:
                    self.page.goto(self.page.url or self.draft.target_url, wait_until="domcontentloaded")
            except Exception:
                self.page.goto(self.draft.target_url, wait_until="domcontentloaded")
            self.prepare_current_step()
            return self.snapshot()

    def _assert_revision(self, expected: int) -> None:
        if expected != self.draft.revision:
            raise ReviewConflictError(
                f"Revision mismatch: expected {expected}, active {self.draft.revision}"
            )

    def _classify_navigation(self) -> str:
        buttons = self.page.locator('button, input[type="submit"], input[type="button"], a[role="button"]')
        final_submit = None
        intermediate = None
        for index in range(buttons.count()):
            button = buttons.nth(index)
            try:
                if not button.is_visible():
                    continue
                text = (button.inner_text() or button.get_attribute("value") or "").strip().lower()
                button_type = (button.get_attribute("type") or "").lower()
                if any(re.search(pattern, text, re.IGNORECASE) for pattern in AgentFormSolver.FINAL_SUBMIT_BUTTON_PATTERNS) or (button_type == "submit" and "next" not in text and "suivant" not in text):
                    final_submit = button
                    break
                if any(re.search(pattern, text, re.IGNORECASE) for pattern in AgentFormSolver.INTERMEDIATE_BUTTON_PATTERNS):
                    intermediate = button
            except Exception:
                continue
        self._navigation_locator = final_submit or intermediate
        return "final_submit" if final_submit else ("intermediate_next" if intermediate else "none")

    def _click_navigation(self, action: str) -> None:
        locator = getattr(self, "_navigation_locator", None)
        if locator is None:
            raise ReviewSessionError(f"Navigation control unavailable for action {action}")
        locator.click()

    def _evaluate_submission(self) -> Any:
        from .verifier import SubmissionVerifier

        return SubmissionVerifier.evaluate(self.page, initial_url=self.draft.target_url)

    def take_screenshot(self) -> bytes:
        """Capture a live viewport screenshot of the current Playwright page."""
        with self._lock:
            try:
                return self.page.screenshot(type="jpeg", quality=85)
            except Exception as exc:
                raise ReviewSessionError(f"Failed to capture screenshot: {exc}") from exc


def public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Remove local filesystem paths before a snapshot is sent to the phone."""
    result = copy.deepcopy(snapshot)
    resume_path = result.pop("resume_path", None)
    letter_path = result.pop("letter_path", None)
    result.pop("browser_profile_dir", None)
    result["resume_name"] = Path(str(resume_path)).name if resume_path else ""
    result["letter_name"] = Path(str(letter_path)).name if letter_path else ""
    for field in result.get("fields", []):
        if field.get("type") == FieldType.FILE.value:
            value = field.get("value") or ""
            field["value"] = Path(str(value)).name
    return result
