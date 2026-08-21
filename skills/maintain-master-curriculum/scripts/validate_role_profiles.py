#!/usr/bin/env python3
"""Validate an evidence-backed role-profile catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_master_sources import read_facts  # noqa: E402


PROFILE_FIELDS = {
    "id", "label", "narrative", "target_roles", "canonical_headline",
    "seniority_ceiling", "anchor_fact_ids", "supporting_fact_ids",
    "technology_fact_ids", "allowed_positioning_fact_ids",
    "prohibited_claims", "risk_notes",
}
SENIORITY = {"entry", "junior", "mid", "senior", "lead"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(source_hashes: Any) -> str:
    payload = json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_list(value: Any, *, minimum: int = 0) -> bool:
    return (
        isinstance(value, list) and len(value) >= minimum
        and all(nonempty(item) for item in value)
        and len(set(value)) == len(value)
    )


def aware_timestamp(value: Any) -> bool:
    if not nonempty(value) or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def validate(record: dict[str, Any], template: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(record) != set(template):
        errors.append("catalog fields must match the template")
    if record.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if record.get("catalog_status") not in {"staged", "approved"}:
        errors.append("catalog_status must be staged or approved")
    if not aware_timestamp(record.get("generated_at")):
        errors.append("generated_at must be timezone-aware ISO-8601")

    source = record.get("source_manifest")
    facts: set[str] = set()
    if not isinstance(source, dict) or set(source) != {"path", "sha256", "fingerprint"}:
        errors.append("source_manifest must contain path, sha256, and fingerprint")
    else:
        try:
            manifest_path = Path(source["path"]).expanduser().resolve()
            if not manifest_path.is_file() or digest(manifest_path) != source.get("sha256"):
                errors.append("source manifest is missing or its hash does not match")
            else:
                manifest = load(manifest_path)
                hashes = manifest.get("source_hashes")
                if not isinstance(hashes, dict) or source.get("fingerprint") != fingerprint(hashes):
                    errors.append("source manifest fingerprint does not match")
                source_dir = Path(manifest.get("source_dir", "")).expanduser().resolve()
                source_errors, source_facts = read_facts(source_dir)
                if source_errors:
                    errors.extend(f"canonical source invalid: {item}" for item in source_errors)
                elif any(hashes.get(name) != digest(source_dir / name) for name in hashes):
                    errors.append("canonical source hashes no longer match the source manifest")
                else:
                    facts = set(source_facts)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"cannot verify source manifest: {exc}")

    profiles = record.get("profiles")
    if not isinstance(profiles, list):
        errors.append("profiles must be an array")
        profiles = []
    seen: set[str] = set()
    for index, profile in enumerate(profiles):
        label = f"profiles.{index}"
        if not isinstance(profile, dict) or set(profile) != PROFILE_FIELDS:
            errors.append(f"{label} fields are invalid")
            continue
        profile_id = profile.get("id")
        if not nonempty(profile_id) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile_id):
            errors.append(f"{label}.id must be a lower-case slug")
        elif profile_id in seen:
            errors.append(f"duplicate profile id: {profile_id}")
        else:
            seen.add(profile_id)
        for field in ("label", "narrative", "canonical_headline"):
            if not nonempty(profile.get(field)):
                errors.append(f"{label}.{field} is required")
        if profile.get("seniority_ceiling") not in SENIORITY:
            errors.append(f"{label}.seniority_ceiling is invalid")
        minimums = {"target_roles": 1, "anchor_fact_ids": 1, "supporting_fact_ids": 2}
        for field in (
            "target_roles", "anchor_fact_ids", "supporting_fact_ids",
            "technology_fact_ids", "allowed_positioning_fact_ids",
            "prohibited_claims", "risk_notes",
        ):
            if not string_list(profile.get(field), minimum=minimums.get(field, 0)):
                errors.append(f"{label}.{field} must be a unique string array")
        anchors = set(profile.get("anchor_fact_ids", []))
        supports = set(profile.get("supporting_fact_ids", []))
        technologies = set(profile.get("technology_fact_ids", []))
        allowed = set(profile.get("allowed_positioning_fact_ids", []))
        if anchors & supports:
            errors.append(f"{label} anchor and supporting facts must be distinct")
        if any(not re.fullmatch(r"MC-(?:EXP|PROJ|EDU)-\d{3,}", item) for item in anchors):
            errors.append(f"{label}.anchor_fact_ids must come from experience, project, or education facts")
        required = anchors | supports | technologies
        if not required <= allowed:
            errors.append(f"{label}.allowed_positioning_fact_ids must include anchor, supporting, and technology facts")
        unknown = (required | allowed) - facts
        if unknown:
            errors.append(f"{label} references unknown facts: {', '.join(sorted(unknown))}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument(
        "--template", type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "role-profiles-template.json",
    )
    args = parser.parse_args()
    try:
        errors = validate(load(args.catalog), load(args.template))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid role profiles: {args.catalog.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
