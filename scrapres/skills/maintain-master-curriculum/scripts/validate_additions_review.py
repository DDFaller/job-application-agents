#!/usr/bin/env python3
"""Validate an agent-authored, claim-level master curriculum additions review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from validate_master_sources import read_facts, source_hashes

TOP = {"schema_version", "verdict", "current_source_dir", "staged_source_dir", "current_source_hashes", "staged_source_hashes", "inputs", "changes", "unresolved_questions", "reviewed_at"}
INPUT_FIELDS = {"id", "kind", "path", "sha256", "snapshot_path", "snapshot_sha256"}
CHANGE_FIELDS = {"action", "fact_id", "before", "after", "evidence", "verdict", "rationale", "issues"}
EVIDENCE_FIELDS = {"source_id", "quote"}
VERDICTS = {"accept", "revise", "reject"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("review root must be an object")
    return value


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def string_list(value: Any) -> bool:
    return isinstance(value, list) and all(nonempty(item) for item in value)


def aware(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def diff(current: dict[str, str], staged: dict[str, str]) -> dict[str, tuple[str, str | None, str | None]]:
    result: dict[str, tuple[str, str | None, str | None]] = {}
    for fact_id in sorted(set(current) | set(staged)):
        before, after = current.get(fact_id), staged.get(fact_id)
        if before == after:
            continue
        action = "add" if before is None else "remove" if after is None else "modify"
        result[fact_id] = (action, before, after)
    return result


def validate(review: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(review) != TOP:
        errors.append("review fields do not match the additions-review template")
    if review.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if review.get("verdict") not in VERDICTS:
        errors.append("verdict must be accept, revise, or reject")
    if not aware(review.get("reviewed_at")):
        errors.append("reviewed_at must be a timezone-aware ISO-8601 timestamp")
    if not string_list(review.get("unresolved_questions")):
        errors.append("unresolved_questions must be a string array")

    current_facts: dict[str, str] = {}
    current_value = review.get("current_source_dir")
    if current_value is None:
        if review.get("current_source_hashes") != {}:
            errors.append("current_source_hashes must be empty when current_source_dir is null")
    elif nonempty(current_value):
        current_path = Path(current_value).expanduser().resolve()
        current_errors, current_facts = read_facts(current_path)
        errors.extend(f"current source: {item}" for item in current_errors)
        if review.get("current_source_hashes") != source_hashes(current_path):
            errors.append("current_source_hashes do not match current sources")
    else:
        errors.append("current_source_dir must be null or a non-empty path")

    staged_facts: dict[str, str] = {}
    try:
        staged_path = Path(review.get("staged_source_dir", "")).expanduser().resolve()
        staged_errors, staged_facts = read_facts(staged_path)
        errors.extend(f"staged source: {item}" for item in staged_errors)
        if review.get("staged_source_hashes") != source_hashes(staged_path):
            errors.append("staged_source_hashes do not match staged sources")
    except TypeError:
        errors.append("staged_source_dir must be a path string")

    input_text: dict[str, str] = {}
    inputs = review.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        errors.append("inputs must be a non-empty array")
        inputs = []
    for index, item in enumerate(inputs):
        label = f"inputs.{index}"
        if not isinstance(item, dict) or set(item) != INPUT_FIELDS:
            errors.append(f"{label} must contain exactly {sorted(INPUT_FIELDS)}")
            continue
        input_id = item.get("id")
        if not isinstance(input_id, str) or not re.fullmatch(r"I\d{3}", input_id):
            errors.append(f"{label}.id must match I###")
            continue
        if input_id in input_text:
            errors.append(f"duplicate input ID: {input_id}")
            continue
        if item.get("kind") not in {"document", "user_statement"}:
            errors.append(f"{label}.kind is invalid")
        try:
            original = Path(item["path"]).expanduser().resolve()
            snapshot = Path(item["snapshot_path"]).expanduser().resolve()
            if not original.is_file() or digest(original) != item.get("sha256"):
                errors.append(f"{label} original path or hash is invalid")
            text = snapshot.read_text(encoding="utf-8")
            if digest(snapshot) != item.get("snapshot_sha256"):
                errors.append(f"{label} snapshot hash is invalid")
            input_text[input_id] = text
        except (OSError, TypeError, UnicodeError) as exc:
            errors.append(f"{label} cannot be verified: {exc}")

    expected = diff(current_facts, staged_facts)
    seen: set[str] = set()
    change_verdicts: list[str] = []
    changes = review.get("changes")
    if not isinstance(changes, list) or not changes:
        errors.append("changes must be a non-empty array")
        changes = []
    for index, change in enumerate(changes):
        label = f"changes.{index}"
        if not isinstance(change, dict) or set(change) != CHANGE_FIELDS:
            errors.append(f"{label} must contain exactly {sorted(CHANGE_FIELDS)}")
            continue
        fact_id = change.get("fact_id")
        if not nonempty(fact_id) or fact_id in seen:
            errors.append(f"{label}.fact_id is missing or duplicated")
            continue
        seen.add(fact_id)
        actual = (change.get("action"), change.get("before"), change.get("after"))
        if fact_id not in expected or actual != expected.get(fact_id):
            errors.append(f"{label} does not match the actual fact-level diff")
        verdict = change.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"{label}.verdict is invalid")
        else:
            change_verdicts.append(verdict)
        if not nonempty(change.get("rationale")):
            errors.append(f"{label}.rationale is required")
        if not string_list(change.get("issues")):
            errors.append(f"{label}.issues must be a string array")
        citations = change.get("evidence")
        if not isinstance(citations, list) or not citations:
            errors.append(f"{label}.evidence must be non-empty")
            continue
        has_input = False
        for ci, citation in enumerate(citations):
            if not isinstance(citation, dict) or set(citation) != EVIDENCE_FIELDS:
                errors.append(f"{label}.evidence.{ci} has an invalid shape")
                continue
            source_id, quote = citation.get("source_id"), citation.get("quote")
            if source_id in input_text:
                has_input = True
                haystack = input_text[source_id]
            elif source_id in current_facts:
                haystack = current_facts[source_id]
            else:
                errors.append(f"{label}.evidence.{ci} has an unknown source_id")
                continue
            if not nonempty(quote) or quote not in haystack:
                errors.append(f"{label}.evidence.{ci}.quote is not verbatim in its source")
        if not has_input:
            errors.append(f"{label} requires at least one supplied-input citation")
    if set(expected) != seen:
        errors.append("changes must cover every actual fact-level difference exactly once")

    computed = "reject" if "reject" in change_verdicts else "revise" if "revise" in change_verdicts else "accept"
    if review.get("verdict") != computed:
        errors.append(f"overall verdict must be {computed}")
    if review.get("verdict") == "accept" and review.get("unresolved_questions"):
        errors.append("accepted reviews cannot have unresolved questions")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", required=True, type=Path)
    args = parser.parse_args()
    try:
        review = load(args.review)
        errors = validate(review)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid additions review ({review['verdict']}): {args.review.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
