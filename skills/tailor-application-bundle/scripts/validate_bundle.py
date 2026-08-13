#!/usr/bin/env python3
"""Validate a Terra-authored application bundle against job and candidate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


JOB_FAMILIES = {"computing", "non_computing", "mixed", "unclear"}
DOCUMENT_FOCUS = {"technical", "transferable", "balanced", "conservative"}
ENTRY_FIELDS = {
    "experience": {"type", "company", "position", "location", "dates", "summary", "highlights", "evidence_ids"},
    "education": {"type", "institution", "area", "degree", "location", "dates", "summary", "highlights", "evidence_ids"},
    "normal": {"type", "name", "location", "dates", "summary", "highlights", "evidence_ids"},
    "one_line": {"type", "label", "details", "evidence_ids"},
    "publication": {"type", "title", "authors", "journal", "dates", "doi", "url", "summary", "evidence_ids"},
    "bullet": {"type", "text", "evidence_ids"},
    "numbered": {"type", "text", "evidence_ids"},
    "reversed_numbered": {"type", "text", "evidence_ids"},
    "text": {"type", "text", "evidence_ids"},
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def ids(value: Any, known: set[str], label: str, errors: list[str], allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value) or any(not nonempty(item) for item in value):
        errors.append(f"{label} must be {'a' if allow_empty else 'a non-empty'} string array")
        return
    unknown = sorted(set(value) - known)
    if unknown:
        errors.append(f"{label} has unknown references: {', '.join(unknown)}")


def cited_text(item: Any, candidate_ids: set[str], job_keys: set[str], label: str, errors: list[str], job_required: bool = False) -> None:
    if not isinstance(item, dict) or set(item) != {"text", "candidate_evidence_ids", "job_evidence_keys"}:
        errors.append(f"{label} must contain text, candidate_evidence_ids, and job_evidence_keys")
        return
    if not nonempty(item.get("text")):
        errors.append(f"{label}.text is required")
    ids(item.get("candidate_evidence_ids"), candidate_ids, f"{label}.candidate_evidence_ids", errors, allow_empty=True)
    ids(item.get("job_evidence_keys"), job_keys, f"{label}.job_evidence_keys", errors, allow_empty=True)
    if not item.get("candidate_evidence_ids") and not item.get("job_evidence_keys"):
        errors.append(f"{label} needs at least one evidence reference")
    if job_required and not item.get("job_evidence_keys"):
        errors.append(f"{label} needs job evidence")


def referenced_candidate_ids(bundle: dict[str, Any]) -> set[str]:
    """Collect candidate evidence used in authored content, excluding the selection lists."""
    found: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, list):
            found.update(item for item in value if isinstance(item, str) and item)

    candidate = bundle.get("candidate", {})
    if isinstance(candidate, dict):
        add(candidate.get("headline_evidence_ids"))
        summary = candidate.get("summary", {})
        if isinstance(summary, dict):
            add(summary.get("evidence_ids"))
    strategy = bundle.get("tailoring_strategy", {})
    if isinstance(strategy, dict):
        for item in strategy.get("fit_arguments", []):
            if isinstance(item, dict):
                add(item.get("candidate_evidence_ids"))
        rationale = strategy.get("selection_rationale", {})
        if isinstance(rationale, dict):
            add(rationale.get("candidate_evidence_ids"))
    for section in bundle.get("resume_sections", []):
        if not isinstance(section, dict):
            continue
        for item in section.get("items", []):
            if not isinstance(item, dict):
                continue
            add(item.get("evidence_ids"))
            for highlight in item.get("highlights", []):
                if isinstance(highlight, dict):
                    add(highlight.get("evidence_ids"))
    letter = bundle.get("motivation_letter", {})
    if isinstance(letter, dict):
        for paragraph in letter.get("paragraphs", []):
            if isinstance(paragraph, dict):
                add(paragraph.get("candidate_evidence_ids"))
    analysis = bundle.get("match_analysis", {})
    if isinstance(analysis, dict):
        for field in ("matched", "gaps"):
            for item in analysis.get(field, []):
                if isinstance(item, dict):
                    add(item.get("candidate_evidence_ids"))
    return found


def validate(bundle: dict[str, Any], template: dict[str, Any], bundle_path: Path) -> list[str]:
    errors: list[str] = []
    if set(bundle) != set(template):
        missing = sorted(set(template) - set(bundle))
        extra = sorted(set(bundle) - set(template))
        if missing:
            errors.append("missing fields: " + ", ".join(missing))
        if extra:
            errors.append("unexpected fields: " + ", ".join(extra))
    if bundle.get("schema_version") != 4:
        errors.append("schema_version must be 4")
    inputs = bundle.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != set(template["inputs"]):
        errors.append("inputs must match the template")
        return errors
    artifacts: dict[str, dict[str, Any]] = {}
    for path_key, hash_key in (("job_json", "job_sha256"), ("candidate_evidence_json", "candidate_evidence_sha256")):
        try:
            path = Path(inputs[path_key]).expanduser().resolve()
            if not path.is_file():
                errors.append(f"{path_key} does not exist")
                continue
            if digest(path) != inputs[hash_key]:
                errors.append(f"{hash_key} does not match {path_key}")
                continue
            artifacts[path_key] = load(path)
        except (OSError, TypeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"cannot verify {path_key}: {exc}")
    if set(artifacts) != {"job_json", "candidate_evidence_json"}:
        return errors
    job = artifacts["job_json"]
    evidence = artifacts["candidate_evidence_json"]
    job_view = bundle.get("job")
    expected_job = {key: job.get(key) for key in ("company", "role", "canonical_url")}
    if job_view != expected_job:
        errors.append("job must copy company, role, and canonical_url from job_json")
    candidate = bundle.get("candidate")
    if not isinstance(candidate, dict) or set(candidate) != set(template["candidate"]):
        errors.append("candidate must match the template")
        candidate = {}
    source_candidate = evidence.get("candidate", {})
    if candidate.get("name") != source_candidate.get("name"):
        errors.append("candidate.name must match candidate evidence")
    if candidate.get("location") != source_candidate.get("location"):
        errors.append("candidate.location must match candidate evidence")
    if candidate.get("contact") != source_candidate.get("contact"):
        errors.append("candidate.contact must match candidate evidence")
    if not nonempty(candidate.get("headline")):
        errors.append("candidate.headline is required")
    candidate_ids = {fact.get("id") for fact in evidence.get("facts", []) if isinstance(fact, dict) and nonempty(fact.get("id"))}
    job_keys = set(job.get("field_evidence", {}))
    strategy = bundle.get("tailoring_strategy")
    selected: set[str] = set()
    if not isinstance(strategy, dict) or set(strategy) != set(template["tailoring_strategy"]):
        errors.append("tailoring_strategy must match the template")
        strategy = {}
    job_family = strategy.get("job_family")
    focus = strategy.get("document_focus")
    if job_family not in JOB_FAMILIES:
        errors.append("tailoring_strategy.job_family must be computing, non_computing, mixed, or unclear")
    if focus not in DOCUMENT_FOCUS:
        errors.append("tailoring_strategy.document_focus must be technical, transferable, balanced, or conservative")

    priorities = strategy.get("job_priorities")
    if not isinstance(priorities, list) or not priorities:
        errors.append("tailoring_strategy.job_priorities must be non-empty")
    else:
        for index, priority in enumerate(priorities):
            label = f"tailoring_strategy.job_priorities.{index}"
            if not isinstance(priority, dict) or set(priority) != {"text", "job_evidence_keys"}:
                errors.append(f"{label} must contain text and job_evidence_keys")
                continue
            if not nonempty(priority.get("text")):
                errors.append(f"{label}.text is required")
            ids(priority.get("job_evidence_keys"), job_keys, f"{label}.job_evidence_keys", errors)

    selected_value = strategy.get("selected_candidate_evidence_ids")
    deprioritized_value = strategy.get("deprioritized_candidate_evidence_ids")
    ids(selected_value, candidate_ids, "tailoring_strategy.selected_candidate_evidence_ids", errors)
    ids(deprioritized_value, candidate_ids, "tailoring_strategy.deprioritized_candidate_evidence_ids", errors, allow_empty=True)
    if isinstance(selected_value, list) and all(isinstance(item, str) for item in selected_value):
        selected = set(selected_value)
        if len(selected) != len(selected_value):
            errors.append("tailoring_strategy.selected_candidate_evidence_ids must not contain duplicates")
    deprioritized = set(deprioritized_value) if isinstance(deprioritized_value, list) and all(isinstance(item, str) for item in deprioritized_value) else set()
    if isinstance(deprioritized_value, list) and len(deprioritized) != len(deprioritized_value):
        errors.append("tailoring_strategy.deprioritized_candidate_evidence_ids must not contain duplicates")
    overlap = selected & deprioritized
    if overlap:
        errors.append("selected and deprioritized candidate evidence overlap: " + ", ".join(sorted(overlap)))
    omitted = candidate_ids - selected - deprioritized
    if omitted:
        errors.append("tailoring strategy does not classify candidate evidence: " + ", ".join(sorted(omitted)))

    fit_arguments = strategy.get("fit_arguments")
    if not isinstance(fit_arguments, list) or not fit_arguments:
        errors.append("tailoring_strategy.fit_arguments must be non-empty")
    else:
        for index, item in enumerate(fit_arguments):
            label = f"tailoring_strategy.fit_arguments.{index}"
            cited_text(item, candidate_ids, job_keys, label, errors, job_required=True)
            if isinstance(item, dict) and not item.get("candidate_evidence_ids"):
                errors.append(f"{label} needs candidate evidence")
    rationale = strategy.get("selection_rationale")
    cited_text(rationale, candidate_ids, job_keys, "tailoring_strategy.selection_rationale", errors, job_required=True)
    if isinstance(rationale, dict) and not rationale.get("candidate_evidence_ids"):
        errors.append("tailoring_strategy.selection_rationale needs candidate evidence")

    summary = candidate.get("summary")
    if not isinstance(summary, dict) or set(summary) != {"text", "evidence_ids"} or not nonempty(summary.get("text")):
        errors.append("candidate.summary must contain non-empty text and evidence_ids")
    else:
        ids(summary.get("evidence_ids"), candidate_ids, "candidate.summary.evidence_ids", errors)
    ids(candidate.get("headline_evidence_ids"), candidate_ids, "candidate.headline_evidence_ids", errors)

    sections = bundle.get("resume_sections")
    if not isinstance(sections, list) or not sections:
        errors.append("resume_sections must be non-empty")
        sections = []
    for si, section in enumerate(sections):
        if not isinstance(section, dict) or set(section) != {"title", "items"} or not nonempty(section.get("title")) or not isinstance(section.get("items"), list):
            errors.append(f"resume_sections.{si} has an invalid shape")
            continue
        for ii, item in enumerate(section["items"]):
            label = f"resume_sections.{si}.items.{ii}"
            if not isinstance(item, dict) or item.get("type") not in ENTRY_FIELDS:
                errors.append(f"{label}.type must be a supported resume entry type")
                continue
            entry_type = item["type"]
            if set(item) != ENTRY_FIELDS[entry_type]:
                errors.append(f"{label} fields do not match type {entry_type}")
                continue
            ids(item.get("evidence_ids"), candidate_ids, f"{label}.evidence_ids", errors)
            required_by_type = {
                "experience": ("company", "position"), "education": ("institution", "area"),
                "normal": ("name",), "one_line": ("label", "details"),
                "publication": ("title", "authors"), "bullet": ("text",),
                "numbered": ("text",), "reversed_numbered": ("text",), "text": ("text",),
            }
            for field in required_by_type[entry_type]:
                value = item.get(field)
                if field == "authors":
                    if not isinstance(value, list) or not value or any(not nonempty(x) for x in value):
                        errors.append(f"{label}.authors must be a non-empty string array")
                elif not nonempty(value):
                    errors.append(f"{label}.{field} is required")
            for field, value in item.items():
                if field in {"type", "evidence_ids", "highlights", "authors"}:
                    continue
                if value is not None and not nonempty(value):
                    errors.append(f"{label}.{field} must be null or non-empty")
            if "highlights" in item:
                if not isinstance(item["highlights"], list):
                    errors.append(f"{label}.highlights must be an array")
                else:
                    for hi, highlight in enumerate(item["highlights"]):
                        if not isinstance(highlight, dict) or set(highlight) != {"text", "evidence_ids"} or not nonempty(highlight.get("text")):
                            errors.append(f"{label}.highlights.{hi} has an invalid shape")
                        else:
                            ids(highlight.get("evidence_ids"), candidate_ids, f"{label}.highlights.{hi}.evidence_ids", errors)

    letter = bundle.get("motivation_letter")
    if not isinstance(letter, dict) or set(letter) != set(template["motivation_letter"]):
        errors.append("motivation_letter must match the template")
        letter = {}
    for field in ("subject", "salutation", "closing", "signature"):
        if not nonempty(letter.get(field)):
            errors.append(f"motivation_letter.{field} is required")
    paragraphs = letter.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        errors.append("motivation_letter.paragraphs must be non-empty")
    else:
        for index, paragraph in enumerate(paragraphs):
            cited_text(paragraph, candidate_ids, job_keys, f"motivation_letter.paragraphs.{index}", errors)

    analysis = bundle.get("match_analysis")
    if not isinstance(analysis, dict) or set(analysis) != {"matched", "gaps"}:
        errors.append("match_analysis must contain matched and gaps")
        analysis = {}
    matched = analysis.get("matched")
    if not isinstance(matched, list) or not matched:
        errors.append("match_analysis.matched must be non-empty")
    else:
        for index, item in enumerate(matched):
            cited_text(item, candidate_ids, job_keys, f"match_analysis.matched.{index}", errors, job_required=True)
    gaps = analysis.get("gaps")
    if not isinstance(gaps, list):
        errors.append("match_analysis.gaps must be an array")
    else:
        for index, item in enumerate(gaps):
            cited_text(item, candidate_ids, job_keys, f"match_analysis.gaps.{index}", errors, job_required=True)
    generated_at = bundle.get("generated_at")
    try:
        parsed = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        if "T" not in str(generated_at) or parsed.utcoffset() is None:
            raise ValueError
    except ValueError:
        errors.append("generated_at must be a timezone-aware ISO-8601 timestamp")
    used = referenced_candidate_ids(bundle)
    outside_selection = used - selected
    if outside_selection:
        errors.append("authored content cites deprioritized candidate evidence: " + ", ".join(sorted(outside_selection)))
    unused_selection = selected - used
    if unused_selection:
        errors.append("selected candidate evidence is not used in the bundle: " + ", ".join(sorted(unused_selection)))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--template", type=Path, default=Path(__file__).resolve().parent.parent / "references" / "bundle-template.json")
    args = parser.parse_args()
    try:
        errors = validate(load(args.bundle), load(args.template), args.bundle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"validation failed: {error}", file=sys.stderr)
        return 1
    print(f"valid and ready: {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
