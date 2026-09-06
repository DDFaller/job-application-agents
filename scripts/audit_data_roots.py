#!/usr/bin/env python3
"""Audit duplicate job-search roots and optionally quarantine a repository copy."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from job_application_agents.config import resolve_data_root


def contract_fingerprint(root: Path) -> tuple[int, str]:
    """Fingerprint only canonical evidence/profile contracts, never applications."""
    digest = hashlib.sha256()
    count = 0
    if not root.is_dir():
        return count, digest.hexdigest()
    for contract_root in (root / "sources", root / "master-curriculum" / "profiles"):
        if not contract_root.is_dir():
            continue
        for path in sorted(item for item in contract_root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
            count += 1
    return count, digest.hexdigest()


def audit(repository_root: Path, data_root: Path) -> dict[str, object]:
    repository_root = repository_root.resolve()
    canonical = resolve_data_root(data_root, repository_root=repository_root)
    shadow = repository_root / "job-search"
    canonical_count, canonical_hash = contract_fingerprint(canonical)
    shadow_count, shadow_hash = contract_fingerprint(shadow)
    return {
        "canonical_root": str(canonical),
        "canonical_files": canonical_count,
        "canonical_fingerprint": canonical_hash,
        "repository_shadow": str(shadow),
        "shadow_exists": shadow.is_dir(),
        "shadow_files": shadow_count,
        "shadow_fingerprint": shadow_hash if shadow.is_dir() else None,
        "divergent": shadow.is_dir() and shadow_hash != canonical_hash,
        "action": "quarantine repository shadow" if shadow.is_dir() else "none",
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parent.parent)
    result.add_argument("--data-root", type=Path)
    result.add_argument(
        "--quarantine",
        action="store_true",
        help="move the repository-local shadow under the canonical .migration/quarantine directory",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    canonical = resolve_data_root(args.data_root, repository_root=args.repository_root)
    report = audit(args.repository_root, canonical)
    if args.quarantine and report["shadow_exists"]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = canonical / ".migration" / "quarantine" / f"repo-job-search-{stamp}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise SystemExit(f"quarantine destination already exists: {destination}")
        shutil.move(str(report["repository_shadow"]), destination)
        report["quarantined_to"] = str(destination)
    print(json.dumps(report, indent=2))
    return 2 if report["shadow_exists"] and not args.quarantine else 0


if __name__ == "__main__":
    raise SystemExit(main())
