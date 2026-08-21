#!/usr/bin/env python3
"""Publish one approved role-profile catalog as an immutable version."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from validate_profile_review import load as load_review
from validate_profile_review import validate as validate_review
from validate_role_profiles import load as load_catalog
from validate_role_profiles import validate as validate_catalog


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def next_version(root: Path) -> str:
    numbers = [int(item.name[1:]) for item in root.glob("p[0-9][0-9][0-9]") if item.is_dir()]
    return f"p{max(numbers, default=0) + 1:03d}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    if args.approval != "APPROVED":
        print("commit refused: --approval must be exactly APPROVED", file=sys.stderr)
        return 2
    catalog_path = args.catalog.expanduser().resolve()
    review_path = args.review.expanduser().resolve()
    state_root = args.state_root.expanduser().resolve()
    if state_root in {Path("/"), Path.home()} or state_root.is_symlink():
        print("commit refused: unsafe state root", file=sys.stderr)
        return 2
    try:
        template_root = Path(__file__).resolve().parent.parent / "references"
        catalog = load_catalog(catalog_path)
        review = load_review(review_path)
        catalog_errors = validate_catalog(catalog, load_catalog(template_root / "role-profiles-template.json"))
        review_errors = validate_review(review, load_review(template_root / "profile-review-template.json"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"commit refused: {exc}", file=sys.stderr)
        return 1
    for error in catalog_errors + review_errors:
        print(f"commit refused: {error}", file=sys.stderr)
    if catalog_errors or review_errors:
        return 1
    if catalog.get("catalog_status") != "staged" or review.get("verdict") != "accept":
        print("commit refused: staged catalog and accepted review required", file=sys.stderr)
        return 2
    if Path(review["inputs"]["catalog_json"]).expanduser().resolve() != catalog_path:
        print("commit refused: review targets a different catalog", file=sys.stderr)
        return 2

    profiles_root = state_root / "profiles"
    versions = profiles_root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    version = next_version(versions)
    version_dir = versions / version
    temporary = Path(tempfile.mkdtemp(prefix=f".{version}.", dir=versions))
    try:
        approved = dict(catalog)
        approved["catalog_status"] = "approved"
        catalog_target = temporary / "role-profiles.json"
        catalog_target.write_text(json.dumps(approved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.copy2(review_path, temporary / "profile-review.json")
        write_json_atomic(temporary / "manifest.json", {
            "schema_version": 1,
            "version": version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "catalog": "role-profiles.json",
            "catalog_sha256": digest(catalog_target),
            "review": "profile-review.json",
            "review_sha256": digest(temporary / "profile-review.json"),
            "source_manifest": approved["source_manifest"],
        })
        os.replace(temporary, version_dir)
        write_json_atomic(profiles_root / "current.json", {
            "schema_version": 1,
            "version": version,
            "catalog": str(version_dir / "role-profiles.json"),
            "catalog_sha256": digest(version_dir / "role-profiles.json"),
            "source_manifest": approved["source_manifest"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        print(f"commit failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"version": version, "catalog": str(version_dir / "role-profiles.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
