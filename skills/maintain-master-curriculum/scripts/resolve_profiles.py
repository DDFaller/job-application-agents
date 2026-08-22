#!/usr/bin/env python3
"""Resolve and verify the currently approved role-profile catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from validate_role_profiles import load, validate


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument(
        "--template", type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "role-profiles-template.json",
    )
    args = parser.parse_args()
    pointer_path = args.state_root.expanduser().resolve() / "profiles" / "current.json"
    try:
        pointer = load(pointer_path)
        if set(pointer) != {"schema_version", "version", "catalog", "catalog_sha256", "source_manifest", "updated_at"} or pointer.get("schema_version") != 1:
            raise ValueError("profile pointer schema is invalid")
        catalog_path = Path(pointer["catalog"]).expanduser().resolve()
        if not catalog_path.is_file() or digest(catalog_path) != pointer.get("catalog_sha256"):
            raise ValueError("profile catalog is missing or its hash does not match")
        if catalog_path.parent.name != pointer.get("version"):
            raise ValueError("profile catalog is not in the pointed immutable version")
        version_manifest_path = catalog_path.parent / "manifest.json"
        version_manifest = load(version_manifest_path)
        if version_manifest.get("version") != pointer.get("version"):
            raise ValueError("profile version manifest does not match the pointer")
        if version_manifest.get("catalog_sha256") != digest(catalog_path):
            raise ValueError("profile version manifest catalog hash does not match")
        review_path = catalog_path.parent / str(version_manifest.get("review", ""))
        if not review_path.is_file() or digest(review_path) != version_manifest.get("review_sha256"):
            raise ValueError("approved profile review is missing or its hash does not match")
        if load(review_path).get("verdict") != "accept":
            raise ValueError("profile version review is not accepted")
        catalog = load(catalog_path)
        errors = validate(catalog, load(args.template))
        if errors:
            raise ValueError("; ".join(errors))
        if catalog.get("catalog_status") != "approved":
            raise ValueError("current profile catalog is not approved")
        if pointer.get("source_manifest") != catalog.get("source_manifest"):
            raise ValueError("profile pointer source binding does not match catalog")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"profiles unavailable: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "version": pointer["version"],
        "catalog": str(catalog_path),
        "catalog_sha256": pointer["catalog_sha256"],
        "profiles": [item["id"] for item in catalog["profiles"]],
        "source_manifest": catalog["source_manifest"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
