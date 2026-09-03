#!/usr/bin/env python3
"""Resolve and verify the currently approved role-profile catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from validate_role_profiles import fingerprint, load, validate


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument(
        "--template", type=Path,
        default=Path(__file__).resolve().parent.parent / "references" / "role-profiles-template.json",
    )
    parser.add_argument(
        "--expected-source-manifest", type=Path,
        help="Require the profile pointer to bind to this canonical source manifest",
    )
    args = parser.parse_args()
    pointer_path = args.state_root.expanduser().resolve() / "profiles" / "current.json"
    try:
        pointer = load(pointer_path)
        if set(pointer) != {"schema_version", "version", "catalog", "catalog_sha256", "source_manifest", "updated_at"} or pointer.get("schema_version") != 1:
            raise ValueError("profile pointer schema is invalid")
        catalog_path = Path(pointer["catalog"]).expanduser().resolve()
        profiles_root = args.state_root.expanduser().resolve() / "profiles"
        try:
            relative_catalog = catalog_path.relative_to(profiles_root / "versions")
        except ValueError as exc:
            raise ValueError("profile catalog is outside the canonical profile state root") from exc
        if len(relative_catalog.parts) != 2 or relative_catalog.parts[1] != "role-profiles.json":
            raise ValueError("profile catalog must be an immutable version artifact")
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
        review = load(review_path)
        if review.get("verdict") != "accept":
            raise ValueError("profile version review is not accepted")
        review_inputs = review.get("inputs")
        if not isinstance(review_inputs, dict):
            raise ValueError("approved profile review inputs are missing")
        reviewed_catalog = Path(str(review_inputs.get("catalog_json", ""))).expanduser().resolve()
        if not reviewed_catalog.is_file() or digest(reviewed_catalog) != review_inputs.get("catalog_sha256"):
            raise ValueError("reviewed profile catalog snapshot is missing or its hash does not match")
        review_catalog_ref = version_manifest.get("review_catalog")
        if review_catalog_ref:
            published_review_catalog = (catalog_path.parent / str(review_catalog_ref)).resolve()
            if not published_review_catalog.is_file() or digest(published_review_catalog) != version_manifest.get("review_catalog_sha256"):
                raise ValueError("published profile review snapshot is missing or its hash does not match")
            if reviewed_catalog != published_review_catalog:
                raise ValueError("profile review does not reference its immutable snapshot")
        catalog = load(catalog_path)
        errors = validate(catalog, load(args.template))
        if errors:
            raise ValueError("; ".join(errors))
        if catalog.get("catalog_status") != "approved":
            raise ValueError("current profile catalog is not approved")
        if pointer.get("source_manifest") != catalog.get("source_manifest"):
            raise ValueError("profile pointer source binding does not match catalog")
        manifest_path = args.expected_source_manifest.expanduser().resolve() if args.expected_source_manifest else None
        if manifest_path:
            expected_manifest = load(manifest_path)
            expected_binding = {
                "path": str(manifest_path),
                "sha256": digest(manifest_path),
                "fingerprint": fingerprint(expected_manifest.get("source_hashes", {})),
            }
            if catalog.get("source_manifest") != expected_binding:
                raise ValueError("profile catalog is not bound to the expected source manifest")
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
