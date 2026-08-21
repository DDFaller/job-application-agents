#!/usr/bin/env python3
"""Validate the independent semantic review of a role-profile catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


CHECKS = {
    "source_grounded", "anchors_and_support_sufficient", "seniority_supported",
    "positioning_coherent", "risks_explicit",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def timestamp(value: Any) -> bool:
    try:
        return isinstance(value, str) and "T" in value and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def validate(review: dict[str, Any], template: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(review) != set(template) or review.get("schema_version") != 1:
        errors.append("review must match schema version 1 template")
    inputs = review.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {"catalog_json", "catalog_sha256"}:
        errors.append("inputs must contain catalog_json and catalog_sha256")
    else:
        try:
            catalog = Path(inputs["catalog_json"]).expanduser().resolve()
            if not catalog.is_file() or digest(catalog) != inputs.get("catalog_sha256"):
                errors.append("reviewed catalog is missing or its hash does not match")
        except (OSError, TypeError, ValueError) as exc:
            errors.append(f"cannot verify reviewed catalog: {exc}")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != CHECKS or any(value not in {True, False} for value in checks.values()):
        errors.append("checks must contain all required booleans")
        checks = {}
    findings = review.get("findings")
    if not isinstance(findings, list) or any(not isinstance(item, str) or not item.strip() for item in findings):
        errors.append("findings must be a string array")
    verdict = review.get("verdict")
    if verdict not in {"accept", "revise", "reject"}:
        errors.append("verdict must be accept, revise, or reject")
    if verdict == "accept" and (not all(checks.values()) or findings):
        errors.append("accepted review requires all checks true and no findings")
    if verdict != "accept" and checks and all(checks.values()) and not findings:
        errors.append("non-accepted review requires a failed check or finding")
    if not timestamp(review.get("reviewed_at")):
        errors.append("reviewed_at must be timezone-aware ISO-8601")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument(
        "--template", type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "profile-review-template.json",
    )
    args = parser.parse_args()
    try:
        errors = validate(load(args.review), load(args.template))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid profile review: {args.review.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
