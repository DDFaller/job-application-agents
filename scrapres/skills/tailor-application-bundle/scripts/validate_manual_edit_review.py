#!/usr/bin/env python3
"""Validate an agent-authored review of manually edited LaTeX documents."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


CHECKS = {
    "claims_supported", "job_alignment_preserved", "candidate_identity_preserved",
    "unsupported_claims_absent", "documents_coherent",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(review: dict, version_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = version_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"could not load manifest: {exc}"]
    if review.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if Path(review.get("version_directory", "")).expanduser().resolve() != version_dir.resolve():
        errors.append("version_directory does not match the reviewed version")
    if review.get("document_revision") != manifest.get("document_revision"):
        errors.append("document_revision does not match the manifest")
    if review.get("document_text_sha256") != manifest.get("document_text_sha256"):
        errors.append("document text hashes do not match the current PDFs")
    inputs = review.get("inputs", {})
    for key, snapshot in (("job", "job.json"), ("candidate_evidence", "candidate-evidence.json")):
        path_key = key + "_json"
        hash_key = key + "_sha256"
        expected_path = (version_dir / snapshot).resolve()
        if Path(inputs.get(path_key, "")).expanduser().resolve() != expected_path:
            errors.append(f"inputs.{path_key} must reference {snapshot}")
        elif not expected_path.is_file() or inputs.get(hash_key) != sha256(expected_path):
            errors.append(f"inputs.{hash_key} does not match {snapshot}")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != CHECKS or any(not isinstance(value, bool) for value in checks.values()):
        errors.append("checks must contain exactly the required boolean checks")
    verdict = review.get("verdict")
    if verdict not in {"accept", "revise"}:
        errors.append("verdict must be accept or revise")
    if verdict == "accept" and isinstance(checks, dict) and not all(checks.values()):
        errors.append("accept requires every check to pass")
    if not isinstance(review.get("findings"), list):
        errors.append("findings must be a list")
    try:
        timestamp = datetime.fromisoformat(str(review.get("reviewed_at", "")).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError
    except ValueError:
        errors.append("reviewed_at must be a timezone-aware ISO timestamp")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--version-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        review = json.loads(args.review.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"invalid manual edit review: {exc}")
        return 1
    errors = validate(review, args.version_dir.expanduser().resolve())
    for error in errors:
        print(f"invalid manual edit review: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
