#!/usr/bin/env python3
"""Validate Luna-produced candidate facts against local source snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


STATUSES = {"complete", "partial", "blocked"}
CATEGORIES = {"identity", "contact", "profile", "experience", "project", "education", "skill", "language"}


def load_bytes(data: bytes, path: Path) -> dict[str, Any]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_bytes(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def receipt_for(record: dict[str, Any], evidence_path: Path) -> dict[str, Any]:
    sources = []
    for source in record.get("sources", []):
        original = Path(source["path"]).expanduser().resolve()
        snapshot = Path(source["snapshot_path"]).expanduser().resolve()
        sources.append({
            "path": str(original),
            "sha256": source["sha256"],
            "size": original.stat().st_size,
            "mtime_ns": original.stat().st_mtime_ns,
            "snapshot_path": str(snapshot),
            "snapshot_sha256": source["snapshot_sha256"],
            "snapshot_size": snapshot.stat().st_size,
            "snapshot_mtime_ns": snapshot.stat().st_mtime_ns,
        })
    _, artifact_sha256 = file_bytes(evidence_path)
    return {
        "schema_version": 1,
        "validator": "validate_candidate_evidence",
        "generated_at_ns": time.time_ns(),
        "artifact_path": str(evidence_path.expanduser().resolve()),
        "artifact_sha256": artifact_sha256,
        "sources": sources,
    }


def verify_receipt(receipt_path: Path, evidence_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
            return ["candidate evidence receipt has an unsupported schema"]
        if receipt.get("validator") != "validate_candidate_evidence":
            errors.append("candidate evidence receipt has an unexpected validator")
        resolved = evidence_path.expanduser().resolve()
        if receipt.get("artifact_path") != str(resolved):
            errors.append("candidate evidence receipt points to a different artifact")
        artifact_bytes, artifact_sha256 = file_bytes(resolved)
        if receipt.get("artifact_sha256") != artifact_sha256:
            errors.append("candidate evidence receipt artifact hash does not match")
        record = json.loads(artifact_bytes.decode("utf-8"))
        expected = {
            (str(Path(item["path"]).expanduser().resolve()), str(Path(item["snapshot_path"]).expanduser().resolve())): item
            for item in record.get("sources", [])
        }
        receipt_sources = receipt.get("sources")
        if not isinstance(receipt_sources, list) or len(receipt_sources) != len(expected):
            errors.append("candidate evidence receipt sources do not match the artifact")
            receipt_sources = []
        seen = set()
        for item in receipt_sources:
            key = (item.get("path"), item.get("snapshot_path"))
            if key in seen or key not in expected:
                errors.append("candidate evidence receipt contains an unexpected source")
                continue
            seen.add(key)
            source = expected[key]
            if item.get("sha256") != source.get("sha256") or item.get("snapshot_sha256") != source.get("snapshot_sha256"):
                errors.append(f"candidate evidence receipt hashes do not match: {key[0]}")
            for key in ("path", "snapshot_path"):
                path = Path(item[key])
                if not path.is_file():
                    errors.append(f"receipt file is missing: {path}")
                    continue
                stat = path.stat()
                size_key = "size" if key == "path" else "snapshot_size"
                mtime_key = "mtime_ns" if key == "path" else "snapshot_mtime_ns"
                if stat.st_size != item.get(size_key) or stat.st_mtime_ns != item.get(mtime_key):
                    errors.append(f"receipt file changed: {path}")
    except (KeyError, OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"cannot verify candidate evidence receipt: {exc}")
    return errors


def aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value)


def validate(record: dict[str, Any], template: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notices: list[str] = []
    if set(record) != set(template):
        missing = sorted(set(template) - set(record))
        extra = sorted(set(record) - set(template))
        if missing:
            errors.append("missing fields: " + ", ".join(missing))
        if extra:
            errors.append("unexpected fields: " + ", ".join(extra))
    if record.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    status = record.get("extraction_status")
    if status not in STATUSES:
        errors.append("extraction_status must be complete, partial, or blocked")
    candidate = record.get("candidate")
    if not isinstance(candidate, dict) or set(candidate) != set(template["candidate"]):
        errors.append("candidate must match the template fields")
        candidate = {}
    for field in ("name", "headline", "location"):
        value = candidate.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors.append(f"candidate.{field} must be null or a non-empty string")
    for field in ("contact", "languages"):
        if not string_list(candidate.get(field)):
            errors.append(f"candidate.{field} must be a string array")
    for field in ("missing_fields", "warnings"):
        if not string_list(record.get(field)):
            errors.append(f"{field} must be a string array")
    if not aware_timestamp(record.get("extracted_at")):
        errors.append("extracted_at must be a timezone-aware ISO-8601 timestamp")

    sources = record.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be an array")
        sources = []
    snapshots: dict[str, str] = {}
    source_paths: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources.{index} must be an object")
            continue
        required = {"path", "sha256", "snapshot_path", "snapshot_sha256", "pages"}
        if set(source) != required:
            errors.append(f"sources.{index} must contain exactly {sorted(required)}")
            continue
        try:
            original = Path(source["path"]).expanduser().resolve()
            snapshot = Path(source["snapshot_path"]).expanduser().resolve()
            if not original.is_file() or file_hash(original) != source["sha256"]:
                errors.append(f"sources.{index} original file hash mismatch")
            snapshot_bytes = snapshot.read_bytes()
            text = snapshot_bytes.decode("utf-8")
            digest = hashlib.sha256(snapshot_bytes).hexdigest()
            if digest != source["snapshot_sha256"]:
                errors.append(f"sources.{index} snapshot hash mismatch")
            source_paths.add(str(original))
            snapshots[str(original)] = text
            if source["pages"] is not None and not isinstance(source["pages"], list):
                errors.append(f"sources.{index}.pages must be an array or null")
        except (OSError, TypeError) as exc:
            errors.append(f"sources.{index} cannot be verified: {exc}")

    facts = record.get("facts")
    if not isinstance(facts, list):
        errors.append("facts must be an array")
        facts = []
    fact_ids: set[str] = set()
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or set(fact) != {"id", "category", "claim", "source_path", "quote", "page"}:
            errors.append(f"facts.{index} has an invalid shape")
            continue
        fact_id = fact.get("id")
        if not isinstance(fact_id, str) or not re.fullmatch(r"E\d{3}", fact_id):
            errors.append(f"facts.{index}.id must match E###")
        elif fact_id in fact_ids:
            errors.append(f"duplicate fact id: {fact_id}")
        else:
            fact_ids.add(fact_id)
        if fact.get("category") not in CATEGORIES:
            errors.append(f"facts.{index}.category is invalid")
        if not isinstance(fact.get("claim"), str) or not fact["claim"].strip():
            errors.append(f"facts.{index}.claim is required")
        path = fact.get("source_path")
        quote = fact.get("quote")
        if path not in source_paths:
            errors.append(f"facts.{index}.source_path is not indexed")
        elif not isinstance(quote, str) or not quote.strip() or quote not in snapshots[path]:
            errors.append(f"facts.{index}.quote is not verbatim in its snapshot")
        if fact.get("page") is not None and not isinstance(fact["page"], int):
            errors.append(f"facts.{index}.page must be an integer or null")

    mapping = record.get("field_evidence")
    if not isinstance(mapping, dict):
        errors.append("field_evidence must be an object")
        mapping = {}
    for key, ids in mapping.items():
        if not isinstance(key, str) or not string_list(ids):
            errors.append(f"field_evidence[{key!r}] must be a non-empty ID array")
        else:
            unknown = sorted(set(ids) - fact_ids)
            if unknown:
                errors.append(f"field_evidence[{key!r}] has unknown IDs: {', '.join(unknown)}")
    required_keys = []
    for field in ("name", "headline", "location"):
        if candidate.get(field):
            required_keys.append(f"candidate.{field}")
    for field in ("contact", "languages"):
        required_keys.extend(f"candidate.{field}.{i}" for i, _ in enumerate(candidate.get(field, [])))
    for key in required_keys:
        if key not in mapping:
            errors.append(f"missing field evidence for {key}")

    if status == "complete":
        if not candidate.get("name"):
            errors.append("complete evidence requires candidate.name")
        if not candidate.get("contact"):
            errors.append("complete evidence requires at least one contact value")
        if not facts:
            errors.append("complete evidence requires facts")
        if record.get("missing_fields"):
            errors.append("complete evidence must have no readiness-blocking missing_fields")
    else:
        notices.append(f"candidate evidence is {status}; it is not ready for tailoring")
    if status == "partial" and not record.get("missing_fields"):
        errors.append("partial evidence must list missing_fields")
    if status == "blocked" and not record.get("warnings"):
        errors.append("blocked evidence must explain the failure")
    return errors, notices


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--receipt", type=Path, help="write a same-run validation receipt")
    parser.add_argument("--verify-receipt", type=Path, help="verify a same-run receipt without rehashing sources")
    parser.add_argument("--template", type=Path, default=Path(__file__).resolve().parent.parent / "references" / "candidate-evidence-template.json")
    args = parser.parse_args()
    if args.verify_receipt:
        errors = verify_receipt(args.verify_receipt, args.evidence)
        if errors:
            for error in errors:
                print(f"validation failed: {error}", file=sys.stderr)
            return 1
        print(f"valid receipt: {args.evidence}")
        return 0
    try:
        record = load_bytes(args.evidence.read_bytes(), args.evidence)
        template = load_bytes(args.template.read_bytes(), args.template)
        errors, notices = validate(record, template)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    for notice in notices:
        print(f"validation warning: {notice}", file=sys.stderr)
    if record["extraction_status"] != "complete":
        return 2
    print(f"valid and ready: {args.evidence}")
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt_for(record, args.evidence), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
