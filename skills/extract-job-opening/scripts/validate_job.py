#!/usr/bin/env python3
"""Validate agent-extracted job JSON and its field-level source evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 2
STATUSES = {"complete", "partial", "blocked"}
SOURCES = {"LinkedIn", "Personio", "Other ATS", "Pasted text", "Saved HTML"}
WORK_MODELS = {"On-site", "Hybrid", "Remote", "Unspecified"}
ARRAY_FIELDS = (
    "responsibilities",
    "requirements",
    "preferred_skills",
    "technologies",
    "application_instructions",
)
NULLABLE_STRINGS = (
    "source",
    "source_url",
    "canonical_url",
    "source_job_id",
    "company",
    "role",
    "location",
    "employment_type",
    "seniority",
    "language",
    "posted_at",
    "closes_at",
    "source_document",
    "source_sha256",
    "extracted_at",
)
EVIDENCED_SCALARS = (
    "source_job_id",
    "company",
    "role",
    "location",
    "employment_type",
    "seniority",
    "language",
    "posted_at",
    "closes_at",
)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def expected_fields(template: dict[str, Any]) -> set[str]:
    return set(template)


def valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def valid_iso_datetime(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "T" in value and parsed.utcoffset() is not None
    except ValueError:
        return False


def valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def evidence_keys(job: dict[str, Any]) -> list[str]:
    keys = [field for field in EVIDENCED_SCALARS if job.get(field) is not None]
    if job.get("work_model") != "Unspecified":
        keys.append("work_model")
    for field in ARRAY_FIELDS:
        keys.extend(f"{field}.{index}" for index, _ in enumerate(job.get(field, [])))
    return keys


def validate(job: dict[str, Any], template: dict[str, Any], job_path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    fields = expected_fields(template)
    missing = sorted(fields - set(job))
    unexpected = sorted(set(job) - fields)
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if unexpected:
        errors.append("unexpected fields: " + ", ".join(unexpected))
    if job.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    status = job.get("extraction_status")
    if status not in STATUSES:
        errors.append("extraction_status must be complete, partial, or blocked")
    for field in NULLABLE_STRINGS:
        value = job.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"{field} must be null or a non-empty string")
        if field != "extracted_at" and value == "Unspecified":
            errors.append(f"{field} must be null rather than the string Unspecified")
    for field in ARRAY_FIELDS + ("missing_fields", "warnings"):
        value = job.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            errors.append(f"{field} must be an array of non-empty strings")
    if job.get("work_model") not in WORK_MODELS:
        errors.append("work_model must be On-site, Hybrid, Remote, or Unspecified")
    if job.get("source") is not None and job.get("source") not in SOURCES:
        errors.append("source must be LinkedIn, Personio, Other ATS, Pasted text, Saved HTML, or null")
    for field in ("source_url", "canonical_url"):
        value = job.get(field)
        if value is not None and not valid_url(value):
            errors.append(f"{field} must be an HTTP(S) URL or null")
    for field in ("posted_at", "closes_at"):
        value = job.get(field)
        if value is not None and not valid_iso_date(value):
            errors.append(f"{field} must use YYYY-MM-DD or be null")
    extracted_at = job.get("extracted_at")
    if extracted_at is not None and not valid_iso_datetime(extracted_at):
        errors.append("extracted_at must be an ISO-8601 timestamp or null")

    evidence = job.get("field_evidence")
    if not isinstance(evidence, dict):
        errors.append("field_evidence must be an object")
        evidence = {}
    else:
        for key, quotes in evidence.items():
            if not isinstance(key, str) or not isinstance(quotes, list) or not quotes or any(
                not isinstance(quote, str) or not quote.strip() for quote in quotes
            ):
                errors.append(f"field_evidence[{key!r}] must be a non-empty string array")

    source_path: Path | None = None
    if job.get("source_document"):
        source_path = Path(job["source_document"]).expanduser()
        if not source_path.is_absolute():
            source_path = (job_path.parent / source_path).resolve()
        try:
            source_bytes = source_path.read_bytes()
        except OSError as exc:
            errors.append(f"cannot read source_document: {exc}")
        if source_bytes is not None:
            actual_hash = hashlib.sha256(source_bytes).hexdigest()
            if job.get("source_sha256") != actual_hash:
                errors.append("source_sha256 does not match source_document")
    elif status != "blocked":
        errors.append("source_document is required unless extraction_status is blocked")
    if status != "blocked" and not job.get("source_sha256"):
        errors.append("source_sha256 is required unless extraction_status is blocked")

    for key in evidence_keys(job):
        if not evidence.get(key):
            errors.append(f"missing evidence for {key}")

    if status == "complete":
        required = ["source", "company", "role", "extracted_at"]
        if job.get("source") != "Pasted text":
            required.extend(("source_url", "canonical_url"))
        for field in required:
            if not job.get(field):
                errors.append(f"{field} is required when extraction_status is complete")
        if not job.get("responsibilities") and not job.get("requirements"):
            errors.append("a complete extraction needs responsibilities or requirements")
        if job.get("missing_fields"):
            errors.append("missing_fields must be empty when extraction_status is complete")
    else:
        warnings.append(f"extraction is {status}; it is not ready for tailoring")
    if status == "partial" and not job.get("missing_fields"):
        errors.append("partial extraction must identify missing_fields")
    if status == "blocked" and not job.get("warnings"):
        errors.append("blocked extraction must explain the failure in warnings")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "job-template.json",
    )
    args = parser.parse_args()
    try:
        job = load_object(args.job)
        template = load_object(args.template)
        errors, warnings = validate(job, template, args.job)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"validation warning: {warning}", file=sys.stderr)
    if job["extraction_status"] != "complete":
        return 2
    print(f"valid and ready: {args.job}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
