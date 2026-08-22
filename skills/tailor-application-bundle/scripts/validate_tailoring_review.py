#!/usr/bin/env python3
"""Validate an independent semantic review of a tailored application bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def load_bytes(data: bytes, path: Path) -> dict[str, Any]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def load(path: Path) -> dict[str, Any]:
    """Load one JSON object from *path* for the public CLI."""
    return load_bytes(path.read_bytes(), path)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate(review: dict[str, Any], template: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(review) != set(template):
        errors.append("review fields must match the template")
    if review.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    inputs = review.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != set(template["inputs"]):
        errors.append("inputs must match the template")
        return errors
    artifacts: dict[str, dict[str, Any]] = {}
    pairs = (
        ("job_json", "job_sha256"),
        ("candidate_evidence_json", "candidate_evidence_sha256"),
        ("role_profiles_json", "role_profiles_sha256"),
        ("bundle_json", "bundle_sha256"),
    )
    for path_key, hash_key in pairs:
        try:
            path = Path(inputs[path_key]).expanduser().resolve()
            if not path.is_file():
                errors.append(f"{path_key} does not exist")
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != inputs[hash_key]:
                errors.append(f"{hash_key} does not match {path_key}")
                continue
            artifacts[path_key] = load_bytes(data, path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"cannot verify {path_key}: {exc}")
    if set(artifacts) != {"job_json", "candidate_evidence_json", "role_profiles_json", "bundle_json"}:
        return errors

    bundle_inputs = artifacts["bundle_json"].get("inputs")
    if not isinstance(bundle_inputs, dict):
        errors.append("bundle inputs are missing or invalid")
    else:
        for path_key, hash_key in (
            ("job_json", "job_sha256"),
            ("candidate_evidence_json", "candidate_evidence_sha256"),
            ("role_profiles_json", "role_profiles_sha256"),
        ):
            try:
                review_path = str(Path(inputs[path_key]).expanduser().resolve())
                bundle_path = str(Path(bundle_inputs[path_key]).expanduser().resolve())
            except (KeyError, TypeError, ValueError):
                errors.append(f"bundle {path_key} input is missing or invalid")
                continue
            if review_path != bundle_path:
                errors.append(f"review {path_key} does not match the bundle input path")
            if inputs.get(hash_key) != bundle_inputs.get(hash_key):
                errors.append(f"review {hash_key} does not match the bundle input hash")

    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(template["checks"]):
        errors.append("checks must match the template")
        checks = {}
    for name in template["checks"]:
        if not isinstance(checks.get(name), bool):
            errors.append(f"checks.{name} must be boolean")

    candidate_ids = {
        fact.get("id")
        for fact in artifacts["candidate_evidence_json"].get("facts", [])
        if isinstance(fact, dict) and nonempty(fact.get("id"))
    }
    job_keys = set(artifacts["job_json"].get("field_evidence", {}))
    findings = review.get("findings")
    error_findings = 0
    if not isinstance(findings, list):
        errors.append("findings must be an array")
    else:
        for index, finding in enumerate(findings):
            label = f"findings.{index}"
            expected = {"severity", "code", "message", "candidate_evidence_ids", "job_evidence_keys"}
            if not isinstance(finding, dict) or set(finding) != expected:
                errors.append(f"{label} has an invalid shape")
                continue
            if finding.get("severity") not in {"error", "warning"}:
                errors.append(f"{label}.severity must be error or warning")
            elif finding["severity"] == "error":
                error_findings += 1
            if not nonempty(finding.get("code")) or not nonempty(finding.get("message")):
                errors.append(f"{label}.code and message are required")
            for field, known in (("candidate_evidence_ids", candidate_ids), ("job_evidence_keys", job_keys)):
                value = finding.get(field)
                if not isinstance(value, list) or any(not nonempty(item) for item in value):
                    errors.append(f"{label}.{field} must be a string array")
                elif set(value) - known:
                    errors.append(f"{label}.{field} contains unknown references")

    verdict = review.get("verdict")
    if verdict not in {"accept", "revise"}:
        errors.append("verdict must be accept or revise")
    if verdict == "accept" and (error_findings or any(value is not True for value in checks.values())):
        errors.append("accept requires every check true and no error findings")
    if verdict == "revise" and not error_findings and all(value is True for value in checks.values()):
        errors.append("revise requires a failed check or error finding")
    try:
        stamp = str(review.get("reviewed_at"))
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if "T" not in stamp or parsed.utcoffset() is None:
            raise ValueError
    except ValueError:
        errors.append("reviewed_at must be a timezone-aware ISO-8601 timestamp")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "tailoring-review-template.json",
    )
    args = parser.parse_args()
    try:
        errors = validate(load(args.review), load(args.template))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid and ready: {args.review}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
