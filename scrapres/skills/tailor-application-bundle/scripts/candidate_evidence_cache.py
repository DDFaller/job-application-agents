#!/usr/bin/env python3
"""Manage hash-keyed candidate-evidence cache entries for managed workflows."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
from typing import Any


DEFAULT_CACHE_ROOT = Path.home() / "Documents" / "job-search" / ".cache" / "candidate-evidence"
LOCK_TTL = timedelta(hours=1)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def fingerprint(manifest: dict[str, Any]) -> str:
    payload = {
        "schema_version": manifest.get("schema_version"),
        "version": manifest.get("version"),
        "source_hashes": dict(sorted((manifest.get("source_hashes") or {}).items())),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verify_manifest(manifest_path: Path) -> tuple[dict[str, Any], str]:
    manifest_path = manifest_path.expanduser().resolve()
    manifest = load_object(manifest_path)
    source_dir = Path(manifest["source_dir"]).expanduser().resolve()
    if manifest_path != source_dir / "current.json":
        raise ValueError("manifest must be the source directory current.json")
    if manifest.get("schema_version") != 2:
        raise ValueError("source manifest schema_version must be 2")
    hashes = manifest.get("source_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("source manifest must contain source_hashes")
    for name, expected in hashes.items():
        path = source_dir / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"canonical source hash mismatch: {name}")
    return manifest, fingerprint(manifest)


def validator_module() -> Any:
    path = Path(__file__).with_name("validate_candidate_evidence.py")
    spec = importlib.util.spec_from_file_location("candidate_cache_validator", path)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load candidate evidence validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry_paths(root: Path, key: str) -> tuple[Path, Path, Path]:
    entry = root / key
    return entry, entry / "candidate-evidence.json", entry / "candidate-evidence.receipt.json"


def evidence_matches_manifest(record: dict[str, Any], manifest: dict[str, Any]) -> bool:
    source_dir = Path(manifest["source_dir"]).expanduser().resolve()
    expected = {
        str((source_dir / name).resolve()): manifest["source_hashes"][name]
        for name in manifest.get("markdown_sources", [])
    }
    actual = {
        str(Path(item.get("path", "")).expanduser().resolve()): item.get("sha256")
        for item in record.get("sources", []) if isinstance(item, dict)
    }
    return actual == expected


def validate_entry(evidence: Path, receipt: Path, manifest: dict[str, Any]) -> list[str]:
    validator = validator_module()
    errors = validator.verify_receipt(receipt, evidence)
    if errors:
        return errors
    try:
        record = validator.load_bytes(evidence.read_bytes(), evidence)
        template_path = Path(__file__).resolve().parent.parent / "references" / "candidate-evidence-template.json"
        template = validator.load_bytes(template_path.read_bytes(), template_path)
        validation_errors, notices = validator.validate(record, template)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    if validation_errors:
        return validation_errors
    if notices or record.get("extraction_status") != "complete":
        return notices or ["candidate evidence is not complete"]
    if not evidence_matches_manifest(record, manifest):
        return ["candidate evidence sources do not match the canonical manifest"]
    return []


def lock_path(root: Path, key: str) -> Path:
    return root / ".locks" / f"{key}.json"


def read_lock(path: Path) -> dict[str, Any] | None:
    try:
        return load_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def begin(root: Path, key: str) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    locks = root / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    lock = lock_path(root, key)
    existing = read_lock(lock)
    if existing:
        try:
            created = datetime.fromisoformat(existing["created_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            created = datetime.min.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created <= LOCK_TTL:
            raise BlockingIOError(f"cache build already in progress: {lock}")
        lock.unlink(missing_ok=True)
    token = uuid.uuid4().hex
    payload = {"token": token, "created_at": datetime.now(timezone.utc).isoformat()}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(lock, flags, 0o600)
    except FileExistsError as exc:
        raise BlockingIOError(f"cache build already in progress: {lock}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.write("\n")
    staging = root / key
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    return {
        "fingerprint": key,
        "token": token,
        "staging_dir": str(staging),
        "evidence": str(staging / "candidate-evidence.json"),
        "receipt": str(staging / "candidate-evidence.receipt.json"),
    }


def require_owner(root: Path, key: str, token: str) -> Path:
    path = lock_path(root, key)
    record = read_lock(path)
    if not record or record.get("token") != token:
        raise ValueError("cache build lock is missing or owned by another worker")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("fingerprint", "lookup", "begin", "commit", "abort"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--manifest", required=True, type=Path)
        sub.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
        if name in {"commit", "abort"}:
            sub.add_argument("--token", required=True)
            sub.add_argument("--staging-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest, key = verify_manifest(args.manifest)
        root = args.cache_root.expanduser().resolve()
        if args.command == "fingerprint":
            print(key)
            return 0
        entry, evidence, receipt = entry_paths(root, key)
        if args.command == "lookup":
            building = read_lock(lock_path(root, key)) is not None
            errors = validate_entry(evidence, receipt, manifest) if entry.is_dir() and not building else ["cache miss"]
            if errors:
                print("cache miss: " + "; ".join(errors), file=sys.stderr)
                return 3
            print(json.dumps({"fingerprint": key, "evidence": str(evidence), "receipt": str(receipt)}))
            return 0
        if args.command == "begin":
            if entry.is_dir() and not validate_entry(evidence, receipt, manifest):
                print(json.dumps({"fingerprint": key, "evidence": str(evidence), "receipt": str(receipt)}))
                return 0
            print(json.dumps(begin(root, key)))
            return 0
        staging = args.staging_dir.expanduser().resolve()
        if staging != entry:
            raise ValueError("staging-dir does not match the fingerprint cache entry")
        lock = require_owner(root, key, args.token)
        if args.command == "abort":
            shutil.rmtree(staging, ignore_errors=True)
            lock.unlink(missing_ok=True)
            return 0
        errors = validate_entry(
            staging / "candidate-evidence.json",
            staging / "candidate-evidence.receipt.json",
            manifest,
        )
        if errors:
            raise ValueError("cache entry is invalid: " + "; ".join(errors))
        lock.unlink(missing_ok=True)
        print(json.dumps({"fingerprint": key, "evidence": str(evidence), "receipt": str(receipt)}))
        return 0
    except BlockingIOError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"candidate evidence cache failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
