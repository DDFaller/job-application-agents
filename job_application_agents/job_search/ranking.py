"""Deterministic ranking helpers shared by ingestion and shortlist skills."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Iterable

from ..auto_apply.matcher import JobMatchScorer


def canonical_job_key(job: dict[str, Any]) -> str:
    """Return a stable deduplication key without trusting display text alone."""
    url = job.get("canonical_url") or job.get("source_url") or job.get("job_url")
    source_id = job.get("source_job_id") or job.get("job_id")
    if url:
        return f"url:{str(url).strip().lower().rstrip('/')}"
    if source_id:
        return "id:" + str(source_id).strip().lower()
    company = str(job.get("company") or "").strip().lower()
    role = str(job.get("role") or job.get("job_title") or "").strip().lower()
    return f"text:{company}:{role}"


def _job_payload(item: dict[str, Any]) -> dict[str, Any]:
    nested = item.get("job_data")
    return dict(nested) if isinstance(nested, dict) else dict(item)


def rank_jobs(
    jobs: Iterable[dict[str, Any]],
    candidate: dict[str, Any] | None = None,
    tracked_keys: set[str] | None = None,
    top: int = 5,
    min_score: int = 0,
) -> list[dict[str, Any]]:
    """Score and deduplicate jobs, returning JSON-ready triage records.

    Semantic interpretation remains the responsibility of the application
    agents. This helper only applies the existing deterministic scorer and
    records enough provenance for a later review.
    """
    if top < 1:
        raise ValueError("top must be positive")
    if not 0 <= min_score <= 100:
        raise ValueError("min_score must be between 0 and 100")

    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    excluded = tracked_keys or set()
    for original in jobs:
        item = dict(original)
        payload = _job_payload(item)
        key = canonical_job_key(payload)
        if key in seen or key in excluded:
            continue
        seen.add(key)
        status = str(item.get("status") or payload.get("extraction_status") or "new").lower()
        if status in {"expired", "rejected", "withdrawn", "applied", "blocked", "partial"}:
            continue
        score = JobMatchScorer.score_job(payload, candidate=candidate)
        if score.total_score < min_score:
            continue
        ranked.append(
            {
                "job_key": key,
                "company": payload.get("company"),
                "role": payload.get("role") or payload.get("job_title"),
                "location": payload.get("location"),
                "source": payload.get("source"),
                "canonical_url": payload.get("canonical_url") or payload.get("source_url"),
                "source_job_id": payload.get("source_job_id"),
                "score": score.total_score,
                "rating": score.rating,
                "match_breakdown": asdict(score),
                "triage_only": True,
            }
        )
    ranked.sort(key=lambda row: (-int(row["score"]), str(row.get("company") or "").lower(), str(row.get("role") or "").lower()))
    return ranked[:top]


def load_json_jobs(root: Path) -> list[dict[str, Any]]:
    """Load normalized jobs from a directory, ignoring malformed files."""
    jobs: list[dict[str, Any]] = []
    if root.is_file():
        candidates = [root]
    else:
        candidates = sorted(root.rglob("job.json")) if root.exists() else []
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            value.setdefault("_source_path", str(path.resolve()))
            jobs.append(value)
    return jobs
