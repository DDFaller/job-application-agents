"""Application lifecycle rules shared by outcome and email-sync skills."""

from __future__ import annotations

from datetime import date, datetime, timedelta


FINAL_STATUSES = {"OFFER", "REJECTED", "WITHDRAWN", "HIRED", "OFFER_DECLINED"}
KNOWN_STATUSES = {
    "TO_APPLY",
    "APPLIED",
    "REAPPLY",
    "INTERVIEW",
    "FINAL_INTERVIEW",
    "OFFER",
    "REJECTED",
    "WITHDRAWN",
    "HIRED",
    "OFFER_DECLINED",
    "HUMAN_REVIEW",
    "SUBMISSION_UNCERTAIN",
    "DROPPED",
}


def normalize_status(status: str) -> str:
    return str(status or "").strip().upper().replace(" ", "_")


def validate_transition(previous: str, current: str) -> tuple[bool, str]:
    """Validate a requested lifecycle change without enforcing product intent."""
    old = normalize_status(previous)
    new = normalize_status(current)
    if new not in KNOWN_STATUSES:
        return False, f"unknown target status: {current}"
    if old == new:
        return True, "no-op"
    if old in FINAL_STATUSES and new not in FINAL_STATUSES:
        return False, f"cannot reopen final status {old} without explicit correction"
    return True, "accepted"


def parse_local_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def followup_due(
    generated_at: str | date | datetime | None,
    threshold_days: int = 14,
    *,
    today: date | None = None,
) -> bool:
    """Return whether a non-future application has reached its follow-up age."""
    if threshold_days < 0:
        raise ValueError("threshold_days must not be negative")
    start = parse_local_date(generated_at)
    if start is None:
        return False
    current = today or date.today()
    age = (current - start).days
    return age >= threshold_days if age >= 0 else False
