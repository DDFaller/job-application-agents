#!/usr/bin/env python3
"""Publish a validated master-curriculum evidence/readiness pointer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_readiness import load, validate


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def profile_markdown(evidence: dict[str, Any], source_dir: Path, report: dict[str, Any]) -> str:
    candidate = evidence["candidate"]
    lines = [f"# Candidate profile: {candidate.get('name') or 'Unnamed'}", "",
             f"- Evidence status: `{evidence['extraction_status']}`",
             f"- Master source version: `{report['source_version']}`", ""]
    for label, key in (("Headline", "headline"), ("Location", "location")):
        if candidate.get(key):
            lines.append(f"- {label}: {candidate[key]}")
    if candidate.get("contact"):
        lines.append("- Contact: " + "; ".join(candidate["contact"]))
    if candidate.get("languages"):
        lines.append("- Languages: " + "; ".join(candidate["languages"]))
    lines.extend(["", "## Evidence-backed facts", ""])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in evidence.get("facts", []):
        grouped.setdefault(str(fact.get("category", "other")), []).append(fact)
    for category in sorted(grouped):
        lines.extend([f"### {category}", ""])
        for fact in grouped[category]:
            source = Path(fact["source_path"]).name
            lines.append(f"- `{fact['id']}` {fact['claim']} (source: `{source}`)")
            source_ids = fact.get("source_fact_ids", [])
            if source_ids:
                lines.append("  - Canonical facts: " + ", ".join(f"`{item}`" for item in source_ids))
        lines.append("")
    if evidence.get("missing_fields") or evidence.get("warnings"):
        lines.extend(["## Review gaps", ""])
        for item in evidence.get("missing_fields", []):
            lines.append(f"- Missing: {item}")
        for item in evidence.get("warnings", []):
            lines.append(f"- Warning: {item}")
        lines.append("")
    lines.extend(["## Canonical sources", "", f"`{source_dir.resolve()}`", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    args = parser.parse_args()
    report_path = args.report.expanduser().resolve()
    source_dir = args.source_dir.expanduser().resolve()
    state_root = args.state_root.expanduser().resolve()
    try:
        report = load(report_path)
        errors = validate(report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"publication refused: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"publication refused: {error}", file=sys.stderr)
        return 1
    if Path(report["source_dir"]).expanduser().resolve() != source_dir:
        print("publication refused: report source_dir does not match --source-dir", file=sys.stderr)
        return 1
    if report["status"] != "ready":
        print("publication refused: readiness status must be ready", file=sys.stderr)
        return 2
    evidence_path = Path(report["candidate_evidence"]["path"]).expanduser().resolve()
    validator = Path(report["candidate_evidence"]["validator_path"]).expanduser().resolve()
    receipt_path = evidence_path.with_name("candidate-evidence.receipt.json")
    if not receipt_path.is_file():
        print(f"publication refused: missing candidate-evidence receipt: {receipt_path}", file=sys.stderr)
        return 1
    receipt_errors = subprocess.run(
        [sys.executable, str(validator), "--evidence", str(evidence_path), "--verify-receipt", str(receipt_path)],
        capture_output=True, text=True, check=False,
    )
    if receipt_errors.returncode != 0:
        print(receipt_errors.stderr.strip() or "publication refused: candidate-evidence receipt is invalid", file=sys.stderr)
        return 1
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    profile_path = evidence_path.with_name("candidate-profile.md")
    atomic_write(profile_path, profile_markdown(evidence, source_dir, report))
    published_report = state_root / "readiness-current.json"
    atomic_write(published_report, report_path.read_text(encoding="utf-8"))
    current_path = state_root / "current.json"
    current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.is_file() else {}
    current.update({
        "schema_version": 2,
        "version": report["source_version"],
        "source_dir": str(source_dir),
        "source_hashes": report["source_hashes"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "readiness": {"path": str(published_report), "sha256": digest(published_report)},
        "candidate_evidence": {
            "path": str(evidence_path), "sha256": digest(evidence_path),
            "receipt_path": str(receipt_path), "receipt_sha256": digest(receipt_path),
        },
        "candidate_profile": {"path": str(profile_path), "sha256": digest(profile_path)},
    })
    atomic_write(current_path, json.dumps(current, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"source_version": report["source_version"], "current": str(current_path),
                      "candidate_evidence": str(evidence_path), "candidate_profile": str(profile_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
