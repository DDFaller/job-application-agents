#!/usr/bin/env python3
"""Validate readiness output and rerun the live candidate-evidence validator."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SUBPROCESS_TIMEOUT_SECONDS = 60

from validate_master_sources import PROFILE_PHOTOS, read_facts, source_hashes

TOP = {"schema_version", "status", "source_version", "source_dir", "source_hashes", "candidate_evidence", "role_profiles", "hard_blockers", "quality_gaps", "coverage", "generated_at"}
CANDIDATE = {"path", "sha256", "validator_path", "validator_exit"}
ROLE_PROFILES = {"status", "state_root", "resolver_path", "resolver_exit", "catalog_path", "catalog_sha256"}
COVERAGE_KEYS = {"identity", "contact", "profile", "experience", "projects", "education", "skills", "languages", "certifications"}
COVERAGE_VALUES = {"covered", "partial", "missing", "not_applicable"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def aware(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def validate_objects(value: Any, keys: set[str], label: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != keys:
            errors.append(f"{label}.{index} must contain exactly {sorted(keys)}")
        elif any(not nonempty(item.get(key)) for key in keys):
            errors.append(f"{label}.{index} values must be non-empty strings")


def validate(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(report) != TOP:
        errors.append("report fields do not match the readiness template")
    if report.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if report.get("status") not in {"ready", "needs_input", "blocked"}:
        errors.append("status must be ready, needs_input, or blocked")
    if not nonempty(report.get("source_version")):
        errors.append("source_version is required")
    if not aware(report.get("generated_at")):
        errors.append("generated_at must be a timezone-aware ISO-8601 timestamp")

    try:
        source = Path(report.get("source_dir", "")).expanduser().resolve()
        source_errors, _ = read_facts(source)
        errors.extend(f"source: {item}" for item in source_errors)
        actual_hashes = source_hashes(source)
        if report.get("source_hashes") != actual_hashes:
            errors.append("source_hashes must exactly match canonical files")
    except TypeError:
        source = Path("/__invalid__")
        actual_hashes = {}
        errors.append("source_dir must be a path string")

    evidence_view = report.get("candidate_evidence")
    validator_exit: int | None = None
    evidence: dict[str, Any] = {}
    if not isinstance(evidence_view, dict) or set(evidence_view) != CANDIDATE:
        errors.append("candidate_evidence must match the readiness template")
    else:
        try:
            evidence_path = Path(evidence_view["path"]).expanduser().resolve()
            validator = Path(evidence_view["validator_path"]).expanduser().resolve()
            if not evidence_path.is_file() or digest(evidence_path) != evidence_view.get("sha256"):
                errors.append("candidate evidence path or hash is invalid")
            else:
                evidence = load(evidence_path)
            if not validator.is_file():
                errors.append("candidate evidence validator does not exist")
            else:
                result = subprocess.run([sys.executable, str(validator), "--evidence", str(evidence_path)], capture_output=True, text=True, check=False, timeout=SUBPROCESS_TIMEOUT_SECONDS)
                validator_exit = result.returncode
                if validator_exit not in {0, 1, 2}:
                    errors.append(f"candidate validator returned unexpected exit {validator_exit}")
                if evidence_view.get("validator_exit") != validator_exit:
                    errors.append("reported validator_exit does not match live validator")
        except (OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            errors.append(f"cannot verify candidate evidence: {exc}")

    if evidence:
        indexed = {str(Path(item.get("path", "")).expanduser().resolve()) for item in evidence.get("sources", []) if isinstance(item, dict)}
        expected = {str((source / name).resolve()) for name in actual_hashes if name not in PROFILE_PHOTOS}
        if indexed != expected:
            errors.append("candidate evidence must index exactly the canonical source files")

    profiles_view = report.get("role_profiles")
    if not isinstance(profiles_view, dict) or set(profiles_view) != ROLE_PROFILES:
        errors.append("role_profiles must match the readiness template")
    else:
        profile_status = profiles_view.get("status")
        if profile_status not in {"ready", "missing", "stale"}:
            errors.append("role_profiles.status must be ready, missing, or stale")
        try:
            state_root = Path(profiles_view["state_root"]).expanduser().resolve()
            resolver = Path(profiles_view["resolver_path"]).expanduser().resolve()
            if not resolver.is_file():
                errors.append("role profile resolver does not exist")
            else:
                result = subprocess.run(
                    [sys.executable, str(resolver), "--state-root", str(state_root)],
                    capture_output=True, text=True, check=False, timeout=SUBPROCESS_TIMEOUT_SECONDS,
                )
                if result.returncode not in {0, 2} or profiles_view.get("resolver_exit") != result.returncode:
                    errors.append("reported role profile resolver exit does not match live resolver")
                if result.returncode == 0:
                    resolved = json.loads(result.stdout)
                    catalog = Path(resolved["catalog"]).expanduser().resolve()
                    if profile_status != "ready":
                        errors.append("role_profiles.status must be ready when resolver succeeds")
                    if str(catalog) != profiles_view.get("catalog_path") or digest(catalog) != profiles_view.get("catalog_sha256"):
                        errors.append("role profile catalog path or hash does not match resolver output")
                elif profile_status == "ready":
                    errors.append("role_profiles.status cannot be ready when resolver fails")
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            errors.append(f"cannot verify role profiles: {exc}")

    validate_objects(report.get("hard_blockers"), {"code", "message"}, "hard_blockers", errors)
    validate_objects(report.get("quality_gaps"), {"category", "message", "question"}, "quality_gaps", errors)
    coverage = report.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != COVERAGE_KEYS:
        errors.append("coverage must contain exactly the readiness categories")
    else:
        for key, value in coverage.items():
            if value not in COVERAGE_VALUES:
                errors.append(f"coverage.{key} has an invalid value")
        if coverage.get("identity") == "not_applicable" or coverage.get("contact") == "not_applicable":
            errors.append("identity and contact cannot be not_applicable")

    blockers = report.get("hard_blockers") if isinstance(report.get("hard_blockers"), list) else []
    expected_status = None
    if validator_exit == 0:
        expected_status = "blocked" if blockers else "ready"
    elif validator_exit == 2:
        expected_status = "needs_input"
    elif validator_exit == 1:
        expected_status = "blocked"
    if expected_status is not None and report.get("status") != expected_status:
        errors.append(f"status must be {expected_status} for the live validator result")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load(args.report))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid readiness report: {args.report.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
