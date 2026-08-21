#!/usr/bin/env python3
"""Validate an evidence-backed profile proposal produced after a no-match."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from validate_role_profiles import PROFILE_FIELDS, SENIORITY, load, nonempty, string_list


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: Any) -> bool:
    try:
        return nonempty(value) and "T" in value and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def validate(record: dict[str, Any], template: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(record) != set(template) or record.get("schema_version") != 1:
        errors.append("proposal must match schema version 1 template")
    inputs = record.get("inputs")
    expected_inputs = set(template["inputs"])
    artifacts: dict[str, dict[str, Any]] = {}
    if not isinstance(inputs, dict) or set(inputs) != expected_inputs:
        errors.append("proposal inputs must match the template")
    else:
        for path_key, hash_key in (
            ("catalog_json", "catalog_sha256"), ("job_json", "job_sha256"),
            ("candidate_evidence_json", "candidate_evidence_sha256"),
        ):
            try:
                path = Path(inputs[path_key]).expanduser().resolve()
                if not path.is_file() or digest(path) != inputs.get(hash_key):
                    errors.append(f"{path_key} is missing or its hash does not match")
                else:
                    artifacts[path_key] = load(path)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"cannot verify {path_key}: {exc}")
    if not nonempty(record.get("reason")):
        errors.append("reason is required")
    if record.get("requested_profile") is not None and not nonempty(record.get("requested_profile")):
        errors.append("requested_profile must be null or non-empty")
    if not string_list(record.get("gaps")):
        errors.append("gaps must be a string array")
    if not timestamp(record.get("generated_at")):
        errors.append("generated_at must be timezone-aware ISO-8601")
    profile = record.get("proposed_profile")
    if not isinstance(profile, dict) or set(profile) != PROFILE_FIELDS:
        errors.append("proposed_profile fields are invalid")
        return errors
    if not nonempty(profile.get("id")) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile["id"]):
        errors.append("proposed_profile.id must be a lower-case slug")
    if profile.get("seniority_ceiling") not in SENIORITY:
        errors.append("proposed_profile.seniority_ceiling is invalid")
    for field, minimum in (("anchor_fact_ids", 1), ("supporting_fact_ids", 2), ("target_roles", 1)):
        if not string_list(profile.get(field), minimum=minimum):
            errors.append(f"proposed_profile.{field} is insufficient")
    for field in ("technology_fact_ids", "allowed_positioning_fact_ids", "prohibited_claims", "risk_notes"):
        if not string_list(profile.get(field)):
            errors.append(f"proposed_profile.{field} must be a unique string array")
    for field in ("label", "narrative", "canonical_headline"):
        if not nonempty(profile.get(field)):
            errors.append(f"proposed_profile.{field} is required")
    candidate = artifacts.get("candidate_evidence_json", {})
    known_source_facts = {
        source_id for fact in candidate.get("facts", []) if isinstance(fact, dict)
        for source_id in fact.get("source_fact_ids", [])
    }
    cited = set(profile.get("anchor_fact_ids", [])) | set(profile.get("supporting_fact_ids", []))
    cited |= set(profile.get("technology_fact_ids", [])) | set(profile.get("allowed_positioning_fact_ids", []))
    if cited - known_source_facts:
        errors.append("proposed_profile references facts absent from candidate evidence")
    anchors = set(profile.get("anchor_fact_ids", []))
    supports = set(profile.get("supporting_fact_ids", []))
    allowed = set(profile.get("allowed_positioning_fact_ids", []))
    required = anchors | supports | set(profile.get("technology_fact_ids", []))
    if anchors & supports:
        errors.append("proposed profile anchor and supporting facts must be distinct")
    if any(not re.fullmatch(r"MC-(?:EXP|PROJ|EDU)-\d{3,}", item) for item in anchors):
        errors.append("proposed profile anchors must come from experience, project, or education")
    if not required <= allowed:
        errors.append("proposed profile allowed facts must include anchors, supports, and technologies")
    existing = {item.get("id") for item in artifacts.get("catalog_json", {}).get("profiles", []) if isinstance(item, dict)}
    if profile.get("id") in existing:
        errors.append("proposed profile ID already exists; revise the existing profile instead")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True, type=Path)
    parser.add_argument(
        "--template", type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "profile-proposal-template.json",
    )
    args = parser.parse_args()
    try:
        errors = validate(load(args.proposal), load(args.template))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid profile proposal: {args.proposal.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
