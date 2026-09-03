from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..models import CandidateProfile, FormFillResult, SubmissionReceipt


class BaseFormDriver(ABC):
    """Abstract interface for ATS application form drivers."""

    name: str = "base"
    priority: int = 50

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this driver can navigate and fill the given job URL."""
        raise NotImplementedError

    @abstractmethod
    def fill_form(
        self,
        page: Any,  # playwright.sync_api.Page
        candidate: CandidateProfile,
        resume_pdf: Path,
        letter_pdf: Path | None = None,
        job_data: dict[str, Any] | None = None,
    ) -> FormFillResult:
        """Fill in form fields and upload candidate documents."""
        raise NotImplementedError

    @abstractmethod
    def submit(
        self,
        page: Any,  # playwright.sync_api.Page
        job_url: str,
    ) -> SubmissionReceipt:
        """Click submit and capture confirmation receipt."""
        raise NotImplementedError
