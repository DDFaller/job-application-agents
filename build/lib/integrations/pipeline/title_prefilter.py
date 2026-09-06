"""Zero-token heuristic title prefilter for job openings."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_TITLE_PATTERNS = [
    r"\b(?:chef|cheffe|chef\.fe|chef\(fe\)|chef-fe|chefs)\b",
    r"\b(?:manager|managers|management|managing)\b",
]


@dataclass(slots=True)
class TitleFilterDecision:
    """Result of evaluating a job title against exclusion criteria."""

    passed: bool
    reason: str
    matched_pattern: str | None = None
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "matched_pattern": self.matched_pattern,
            "title": self.title,
        }


class JobTitlePrefilter:
    """Zero-token heuristic gate filtering out jobs matching excluded title keywords (e.g. chef, manager)."""

    def __init__(
        self,
        excluded_patterns: list[str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.excluded_patterns = (
            list(excluded_patterns)
            if excluded_patterns is not None
            else list(DEFAULT_EXCLUDED_TITLE_PATTERNS)
        )
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.excluded_patterns
        ]

    def evaluate(self, title: str | None) -> TitleFilterDecision:
        """Evaluate a job title against excluded patterns."""
        if not self.enabled or not self.excluded_patterns:
            return TitleFilterDecision(
                passed=True,
                reason="Title filter is disabled; passed by default",
                title=title,
            )

        if not title or not isinstance(title, str) or not title.strip():
            return TitleFilterDecision(
                passed=True,
                reason="No title provided; passed by default",
                title=title,
            )

        clean_title = title.strip()

        for pattern, compiled in zip(self.excluded_patterns, self._compiled_patterns):
            match = compiled.search(clean_title)
            if match:
                matched_text = match.group(0)
                reason = (
                    f"Job title '{clean_title}' matches excluded keyword/pattern '{matched_text}' (pattern: {pattern})"
                )
                logger.debug("JobTitlePrefilter rejected: %s", reason)
                return TitleFilterDecision(
                    passed=False,
                    reason=reason,
                    matched_pattern=matched_text,
                    title=clean_title,
                )

        return TitleFilterDecision(
            passed=True,
            reason=f"Job title '{clean_title}' passed title exclusion filter",
            title=clean_title,
        )

    def evaluate_job(self, job: Any) -> TitleFilterDecision:
        """Evaluate a NormalizedJobPosting, dict, or object with a title/role."""
        title = None
        if isinstance(job, dict):
            title = job.get("role") or job.get("title")
        else:
            title = getattr(job, "role", None) or getattr(job, "title", None)

        return self.evaluate(title)


def filter_job_by_title(
    job: Any,
    excluded_patterns: list[str] | None = None,
    enabled: bool = True,
) -> TitleFilterDecision:
    """Convenience function to evaluate job against excluded title patterns (default: chef, manager)."""
    prefilter = JobTitlePrefilter(
        excluded_patterns=excluded_patterns,
        enabled=enabled,
    )
    return prefilter.evaluate_job(job)
