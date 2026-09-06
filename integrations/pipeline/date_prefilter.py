"""Zero-token heuristic date prefilter for job openings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DateFilterDecision:
    """Result of evaluating a job against date criteria."""

    passed: bool
    reason: str
    age_days: int | None = None
    days_until_deadline: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "age_days": self.age_days,
            "days_until_deadline": self.days_until_deadline,
        }


def parse_date_to_date_obj(date_val: str | date | datetime | None) -> date | None:
    """Normalize various date inputs to standard datetime.date object."""
    if date_val is None:
        return None
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, date):
        return date_val

    clean = str(date_val).strip()
    if not clean:
        return None

    # Try ISO YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}", clean):
        try:
            return date.fromisoformat(clean[:10])
        except ValueError:
            pass

    # Try DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", clean)
    if m:
        d, mth, y = m.groups()
        try:
            return date(int(y), int(mth), int(d))
        except ValueError:
            pass

    return None


class JobDatePrefilter:
    """Zero-token heuristic gate filtering out stale and expired job postings before LLM calls."""

    def __init__(
        self,
        max_posting_age_days: int | None = 7,
        reject_expired_deadlines: bool = True,
        reject_future_postings: bool = True,
        reference_date: date | None = None,
    ) -> None:
        self.max_posting_age_days = max_posting_age_days
        self.reject_expired_deadlines = reject_expired_deadlines
        self.reject_future_postings = reject_future_postings
        self._reference_date = reference_date

    @property
    def reference_date(self) -> date:
        if self._reference_date is not None:
            return self._reference_date
        return datetime.now(timezone.utc).date()

    def evaluate(
        self,
        posted_at: str | date | datetime | None = None,
        closes_at: str | date | datetime | None = None,
        max_posting_age_days: int | None = None,
    ) -> DateFilterDecision:
        """Evaluate posted date and deadline against policy rules."""
        ref = self.reference_date
        deadline_dt = parse_date_to_date_obj(closes_at)
        posted_dt = parse_date_to_date_obj(posted_at)
        effective_max_age = (
            max_posting_age_days if max_posting_age_days is not None else self.max_posting_age_days
        )

        # 1. Evaluate application deadline (closes_at)
        days_until_deadline: int | None = None
        if deadline_dt is not None:
            days_until_deadline = (deadline_dt - ref).days
            if self.reject_expired_deadlines and deadline_dt < ref:
                days_overdue = (ref - deadline_dt).days
                reason = f"Application deadline expired {days_overdue} day{'s' if days_overdue != 1 else ''} ago (closes_at: {deadline_dt.isoformat()}, ref: {ref.isoformat()})"
                logger.debug("JobDatePrefilter rejected: %s", reason)
                return DateFilterDecision(
                    passed=False,
                    reason=reason,
                    days_until_deadline=days_until_deadline,
                )

        # 2. Evaluate publication age (posted_at)
        age_days: int | None = None
        if posted_dt is not None:
            age_days = (ref - posted_dt).days

            # Future post date check
            if self.reject_future_postings and age_days < -1:
                reason = f"Anomalous future post date: {posted_dt.isoformat()} is ahead of reference date {ref.isoformat()}"
                logger.debug("JobDatePrefilter rejected: %s", reason)
                return DateFilterDecision(
                    passed=False,
                    reason=reason,
                    age_days=age_days,
                    days_until_deadline=days_until_deadline,
                )

            # Stale posting age check
            if effective_max_age is not None and effective_max_age > 0:
                if age_days > effective_max_age:
                    reason = f"Posting is stale: published {age_days} days ago ({posted_dt.isoformat()}), exceeding max age of {effective_max_age} days"
                    logger.debug("JobDatePrefilter rejected: %s", reason)
                    return DateFilterDecision(
                        passed=False,
                        reason=reason,
                        age_days=age_days,
                        days_until_deadline=days_until_deadline,
                    )

            return DateFilterDecision(
                passed=True,
                reason=f"Posting date is valid ({age_days} days old, deadline in {days_until_deadline} days)" if days_until_deadline is not None else f"Posting date is valid ({age_days} days old)",
                age_days=age_days,
                days_until_deadline=days_until_deadline,
            )

        # 3. If no posted date was found, but deadline is valid
        if deadline_dt is not None and days_until_deadline is not None and days_until_deadline >= 0:
            return DateFilterDecision(
                passed=True,
                reason=f"Valid deadline in {days_until_deadline} days (posted_at not specified)",
                days_until_deadline=days_until_deadline,
            )

        # 4. If no dates could be extracted, pass by default
        return DateFilterDecision(
            passed=True,
            reason="No date constraints found to filter on; passed by default",
        )

    def evaluate_job(
        self,
        job: Any,
        max_posting_age_days: int | None = None,
    ) -> DateFilterDecision:
        """Evaluate a NormalizedJobPosting, dict, or object with posted_at/closes_at."""
        if isinstance(job, dict):
            posted = job.get("posted_at") or job.get("date_posted")
            closes = job.get("closes_at") or job.get("deadline")
        else:
            posted = getattr(job, "posted_at", None) or getattr(job, "date_posted", None)
            closes = getattr(job, "closes_at", None) or getattr(job, "deadline", None)
        return self.evaluate(
            posted_at=posted,
            closes_at=closes,
            max_posting_age_days=max_posting_age_days,
        )


def filter_job_by_date(
    job: Any,
    max_posting_age_days: int | None = 7,
    reject_expired_deadlines: bool = True,
    reject_future_postings: bool = True,
    reference_date: date | None = None,
) -> DateFilterDecision:
    """Convenience function to evaluate job freshness with configurable age limit (default: last 7 days).

    Args:
        job: NormalizedJobPosting instance, dict with job fields, or object with date fields.
        max_posting_age_days: Max age in days for posting before rejection (default: 7 days). None disables.
        reject_expired_deadlines: Whether to reject jobs whose deadline is in the past.
        reject_future_postings: Whether to reject anomalous future post dates.
        reference_date: Reference date (defaults to today UTC).

    Returns:
        DateFilterDecision containing pass/fail, rejection reason, and computed age.
    """
    prefilter = JobDatePrefilter(
        max_posting_age_days=max_posting_age_days,
        reject_expired_deadlines=reject_expired_deadlines,
        reject_future_postings=reject_future_postings,
        reference_date=reference_date,
    )
    return prefilter.evaluate_job(job)
