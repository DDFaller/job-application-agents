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
TECHNICAL_SECTION_TOKENS = ("technical skills", "compétences techniques", "hard skills")
SOFT_SECTION_TOKENS = (
    "soft skills", "compétences interpersonnelles", "compétences comportementales",
    "communication", "collaboration",
)
SOFT_EVIDENCE_TOKENS = (
    "delivered sessions", "explaining", "technical sessions", "communication",
    "collaboration", "team", "stakeholder", "documentation", "review gates",
    "read-only access controls", "knowledge sharing",
)
SCORE_FIELDS = {
    "candidate_evidence_id", "relevance", "evidence_strength", "specificity",
    "recency", "risk", "redundancy", "total", "job_evidence_keys",
}
RANKING_FIELDS = {
    "profile_id", "eligible", "score", "candidate_evidence_ids",
    "job_evidence_keys", "rationale",
}
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


def load_bytes(data: bytes, path: Path) -> dict[str, Any]:
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def load(path: Path) -> dict[str, Any]:
    """Load one JSON object from *path* for the public CLI."""
    return load_bytes(path.read_bytes(), path)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def safe_string_set(value: Any) -> set[str]:
    return set(value) if isinstance(value, list) and all(isinstance(item, str) for item in value) else set()


def has_supported_soft_skill_evidence(evidence: dict[str, Any]) -> bool:
    for fact in evidence.get("facts", []):
        if not isinstance(fact, dict) or fact.get("category") not in {"experience", "project"}:
            continue
        claim = str(fact.get("claim", "")).casefold()
        if any(token in claim for token in SOFT_EVIDENCE_TOKENS):
            return True
    return False


def section_title_matches(sections: list[dict[str, Any]], tokens: tuple[str, ...]) -> bool:
    return any(
        any(token in str(section.get("title", "")).casefold() for token in tokens)
        for section in sections if isinstance(section, dict)
    )


def ids(value: Any, known: set[str], label: str, errors: list[str], allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value) or any(not nonempty(item) for item in value):
        errors.append(f"{label} must be {'a' if allow_empty else 'a non-empty'} string array")
        return
    unknown = sorted(set(value) - known)
    if unknown:
        errors.append(f"{label} has unknown references: {', '.join(unknown)}")


def cited_text(item: Any, candidate_ids: set[str], job_keys: set[str], label: str, errors: list[str]) -> None:
    if not isinstance(item, dict) or set(item) != {"text", "candidate_evidence_ids", "job_evidence_keys"}:
        errors.append(f"{label} must contain text, candidate_evidence_ids, and job_evidence_keys")
        return
    if not nonempty(item.get("text")):
        errors.append(f"{label}.text is required")
    ids(item.get("candidate_evidence_ids"), candidate_ids, f"{label}.candidate_evidence_ids", errors, allow_empty=True)
    ids(item.get("job_evidence_keys"), job_keys, f"{label}.job_evidence_keys", errors, allow_empty=True)
    if not item.get("candidate_evidence_ids") and not item.get("job_evidence_keys"):
        errors.append(f"{label} needs at least one evidence reference")


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


def positioning_referenced_ids(bundle: dict[str, Any]) -> set[str]:
    """Collect evidence used for positioning rather than neutral context."""
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
            if isinstance(item, dict):
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
        for item in analysis.get("matched", []):
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
    if bundle.get("schema_version") != 5:
        errors.append("schema_version must be 5")
    inputs = bundle.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != set(template["inputs"]):
        errors.append("inputs must match the template")
        return errors
    artifacts: dict[str, dict[str, Any]] = {}
    for path_key, hash_key in (
        ("job_json", "job_sha256"),
        ("candidate_evidence_json", "candidate_evidence_sha256"),
        ("role_profiles_json", "role_profiles_sha256"),
    ):
        try:
            path = Path(inputs[path_key]).expanduser().resolve()
            if not path.is_file():
                errors.append(f"{path_key} does not exist")
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != inputs[hash_key]:
                errors.append(f"{hash_key} does not match {path_key}")
                continue
            artifacts[path_key] = load_bytes(data, path)
        except (OSError, TypeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"cannot verify {path_key}: {exc}")
    if set(artifacts) != {"job_json", "candidate_evidence_json", "role_profiles_json"}:
        return errors
    job = artifacts["job_json"]
    evidence = artifacts["candidate_evidence_json"]
    profile_catalog = artifacts["role_profiles_json"]
    if profile_catalog.get("schema_version") != 1:
        errors.append("role profile catalog schema_version must be 1")
    source_binding = profile_catalog.get("source_manifest")
    if not isinstance(source_binding, dict) or set(source_binding) != {"path", "sha256", "fingerprint"}:
        errors.append("role profile catalog source binding is invalid")
    else:
        try:
            source_manifest_path = Path(source_binding["path"]).expanduser().resolve()
            source_manifest_bytes = source_manifest_path.read_bytes()
            if hashlib.sha256(source_manifest_bytes).hexdigest() != source_binding.get("sha256"):
                errors.append("role profile source manifest hash does not match")
            source_manifest = json.loads(source_manifest_bytes.decode("utf-8"))
            fingerprint_payload = json.dumps(
                source_manifest.get("source_hashes"), sort_keys=True, separators=(",", ":")
            ).encode()
            if hashlib.sha256(fingerprint_payload).hexdigest() != source_binding.get("fingerprint"):
                errors.append("role profile source fingerprint does not match")
            source_dir = Path(source_manifest.get("source_dir", "")).expanduser().resolve()
            expected_sources = {
                str((source_dir / name).resolve()): source_manifest["source_hashes"][name]
                for name in source_manifest.get("markdown_sources", [])
            }
            actual_sources = {
                str(Path(item.get("path", "")).expanduser().resolve()): item.get("sha256")
                for item in evidence.get("sources", []) if isinstance(item, dict)
            }
            if actual_sources != expected_sources:
                errors.append("candidate evidence sources do not match the profile-bound source manifest")
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"cannot verify role profile source binding: {exc}")
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
    source_facts_by_candidate = {
        fact.get("id"): set(fact.get("source_fact_ids", []))
        for fact in evidence.get("facts", []) if isinstance(fact, dict) and nonempty(fact.get("id"))
    }
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

    profile_items = profile_catalog.get("profiles")
    if not isinstance(profile_items, list):
        errors.append("role profile catalog profiles must be an array")
        profile_items = []
    profiles = {
        item.get("id"): item for item in profile_items
        if isinstance(item, dict) and nonempty(item.get("id"))
    }
    if profile_catalog.get("catalog_status") != "approved" or not profiles:
        errors.append("role profile catalog must be approved and non-empty")

    claim_scores = strategy.get("claim_scores")
    score_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(claim_scores, list) or not claim_scores:
        errors.append("tailoring_strategy.claim_scores must be non-empty")
        claim_scores = []
    for index, score in enumerate(claim_scores):
        label = f"tailoring_strategy.claim_scores.{index}"
        if not isinstance(score, dict) or set(score) != SCORE_FIELDS:
            errors.append(f"{label} fields are invalid")
            continue
        evidence_id = score.get("candidate_evidence_id")
        if evidence_id not in candidate_ids or evidence_id in score_by_id:
            errors.append(f"{label}.candidate_evidence_id must be unique and known")
            continue
        score_by_id[evidence_id] = score
        values = [score.get(field) for field in ("relevance", "evidence_strength", "specificity", "recency", "risk", "redundancy")]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 3 for value in values):
            errors.append(f"{label} dimensions must be integers from 0 through 3")
        else:
            expected_total = values[0] * values[1] * values[2] * values[3] - values[4] - values[5]
            if score.get("total") != expected_total:
                errors.append(f"{label}.total does not match the scoring formula")
        ids(score.get("job_evidence_keys"), job_keys, f"{label}.job_evidence_keys", errors)

    ranking = strategy.get("profile_ranking")
    ranking_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(ranking, list) or not ranking:
        errors.append("tailoring_strategy.profile_ranking must be non-empty")
        ranking = []
    for index, item in enumerate(ranking):
        label = f"tailoring_strategy.profile_ranking.{index}"
        if not isinstance(item, dict) or set(item) != RANKING_FIELDS:
            errors.append(f"{label} fields are invalid")
            continue
        profile_id = item.get("profile_id")
        if profile_id not in profiles or profile_id in ranking_by_id:
            errors.append(f"{label}.profile_id must be unique and known")
            continue
        ranking_by_id[profile_id] = item
        if not isinstance(item.get("eligible"), bool) or not isinstance(item.get("score"), int) or isinstance(item.get("score"), bool):
            errors.append(f"{label} eligible and score fields are invalid")
        ids(item.get("candidate_evidence_ids"), candidate_ids, f"{label}.candidate_evidence_ids", errors, allow_empty=True)
        ids(item.get("job_evidence_keys"), job_keys, f"{label}.job_evidence_keys", errors, allow_empty=True)
        if not nonempty(item.get("rationale")):
            errors.append(f"{label}.rationale is required")
        cited = item.get("candidate_evidence_ids", [])
        if any(evidence_id not in score_by_id for evidence_id in cited):
            errors.append(f"{label} cites candidate evidence without a claim score")
        expected_score = sum(
            max(0, total) for evidence_id in cited if evidence_id in score_by_id
            for total in [score_by_id[evidence_id].get("total")] if isinstance(total, int) and not isinstance(total, bool)
        )
        if item.get("score") != expected_score:
            errors.append(f"{label}.score does not equal its non-negative claim scores")
        source_ids = set().union(*(source_facts_by_candidate.get(evidence_id, set()) for evidence_id in cited)) if cited else set()
        profile = profiles.get(profile_id, {})
        deterministically_eligible = (
            bool(source_ids & safe_string_set(profile.get("anchor_fact_ids")))
            and len(source_ids & safe_string_set(profile.get("supporting_fact_ids"))) >= 2
            and bool(item.get("job_evidence_keys"))
        )
        if item.get("eligible") != deterministically_eligible:
            errors.append(f"{label}.eligible does not satisfy anchor/support/job-evidence gates")
    if set(ranking_by_id) != set(profiles):
        errors.append("profile_ranking must classify every approved profile")

    eligible = [
        item for item in ranking_by_id.values()
        if item.get("eligible") is True and isinstance(item.get("score"), int) and not isinstance(item.get("score"), bool)
    ]
    selected_profile_id = strategy.get("selected_profile_id")
    if not eligible:
        errors.append("a bundle cannot be written without an eligible approved profile")
    else:
        def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
            scored = [score_by_id[eid] for eid in item.get("candidate_evidence_ids", []) if eid in score_by_id]
            return (
                -item["score"],
                -sum(score.get("evidence_strength", 0) for score in scored if isinstance(score.get("evidence_strength"), int)),
                -sum(score.get("relevance", 0) for score in scored if isinstance(score.get("relevance"), int)),
                sum(score.get("risk", 0) for score in scored if isinstance(score.get("risk"), int)),
                item["profile_id"],
            )
        expected_profile = sorted(eligible, key=rank_key)[0]["profile_id"]
        if selected_profile_id != expected_profile:
            errors.append("selected_profile_id must be the highest-ranked eligible profile")
    selected_profile = profiles.get(selected_profile_id, {})
    anchor_ids = strategy.get("selected_profile_anchor_evidence_ids")
    support_ids = strategy.get("selected_profile_supporting_evidence_ids")
    positioning_ids = strategy.get("positioning_candidate_evidence_ids")
    ids(anchor_ids, candidate_ids, "tailoring_strategy.selected_profile_anchor_evidence_ids", errors)
    ids(support_ids, candidate_ids, "tailoring_strategy.selected_profile_supporting_evidence_ids", errors)
    ids(positioning_ids, candidate_ids, "tailoring_strategy.positioning_candidate_evidence_ids", errors)
    if not any(source_facts_by_candidate.get(eid, set()) & safe_string_set(selected_profile.get("anchor_fact_ids")) for eid in anchor_ids or []):
        errors.append("selected profile requires at least one mapped anchor")
    supported_source_ids = set().union(*(source_facts_by_candidate.get(eid, set()) for eid in support_ids or [])) if support_ids else set()
    if len(supported_source_ids & safe_string_set(selected_profile.get("supporting_fact_ids"))) < 2:
        errors.append("selected profile requires at least two mapped supporting facts")
    allowed_source_ids = safe_string_set(selected_profile.get("allowed_positioning_fact_ids"))
    for evidence_id in positioning_ids or []:
        if not source_facts_by_candidate.get(evidence_id, set()) & allowed_source_ids:
            errors.append(f"positioning evidence is not allowed by selected profile: {evidence_id}")
        if evidence_id not in score_by_id:
            errors.append(f"positioning evidence lacks a claim score: {evidence_id}")

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
            cited_text(item, candidate_ids, job_keys, label, errors)
            if isinstance(item, dict) and not item.get("candidate_evidence_ids"):
                errors.append(f"{label} needs candidate evidence")
    rationale = strategy.get("selection_rationale")
    cited_text(rationale, candidate_ids, job_keys, "tailoring_strategy.selection_rationale", errors)
    if isinstance(rationale, dict) and not rationale.get("candidate_evidence_ids"):
        errors.append("tailoring_strategy.selection_rationale needs candidate evidence")

    summary = candidate.get("summary")
    if not isinstance(summary, dict) or set(summary) != {"text", "evidence_ids"} or not nonempty(summary.get("text")):
        errors.append("candidate.summary must contain non-empty text and evidence_ids")
    else:
        ids(summary.get("evidence_ids"), candidate_ids, "candidate.summary.evidence_ids", errors)
    ids(candidate.get("headline_evidence_ids"), candidate_ids, "candidate.headline_evidence_ids", errors)
    positioning = set(positioning_ids or [])
    if not set(candidate.get("headline_evidence_ids", [])) <= positioning:
        errors.append("headline evidence must be approved profile positioning evidence")
    if isinstance(summary, dict) and not set(summary.get("evidence_ids", [])) <= positioning:
        errors.append("summary evidence must be approved profile positioning evidence")

    sections = bundle.get("resume_sections")
    if not isinstance(sections, list) or not sections:
        errors.append("resume_sections must be non-empty")
        sections = []
    rendered_education_record_counts: dict[str, int] = {}
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
            item_evidence = set(item.get("evidence_ids", []))
            if entry_type == "experience":
                matching_records = [
                    record for record in evidence.get("records", {}).get("experience", [])
                    if isinstance(record, dict) and item_evidence & set(record.get("evidence_ids", []))
                ]
                valid_records = [
                    record for record in matching_records
                    if item.get("company") in {record.get("legal_employer"), record.get("contracting_party")}
                ]
                if not valid_records:
                    errors.append(f"{label} must use a structured legal employer or contracting party; a client cannot be the company")
            if entry_type == "education":
                matching_records = [
                    record for record in evidence.get("records", {}).get("education", [])
                    if isinstance(record, dict) and item_evidence & set(record.get("evidence_ids", []))
                ]
                valid_records = [
                    record for record in matching_records
                    if item.get("institution") == record.get("institution")
                    and item.get("degree") == record.get("official_degree")
                    and item.get("area") == record.get("field")
                ]
                if not valid_records:
                    errors.append(f"{label} must copy institution, official degree, and field from a structured education record")
                else:
                    for record in valid_records:
                        record_id = record.get("id")
                        rendered_education_record_counts[record_id] = rendered_education_record_counts.get(record_id, 0) + 1
                        if record.get("dates") and not nonempty(item.get("dates")):
                            errors.append(f"{label}.dates must preserve the structured education record dates")
            if "highlights" in item:
                if not isinstance(item["highlights"], list):
                    errors.append(f"{label}.highlights must be an array")
                else:
                    for hi, highlight in enumerate(item["highlights"]):
                        if not isinstance(highlight, dict) or set(highlight) != {"text", "evidence_ids"} or not nonempty(highlight.get("text")):
                            errors.append(f"{label}.highlights.{hi} has an invalid shape")
                        else:
                            ids(highlight.get("evidence_ids"), candidate_ids, f"{label}.highlights.{hi}.evidence_ids", errors)

    typed_education_record_ids = {
        record.get("id") for record in evidence.get("records", {}).get("education", [])
        if isinstance(record, dict) and nonempty(record.get("id"))
    }
    missing_education = sorted(
        record_id for record_id in typed_education_record_ids
        if rendered_education_record_counts.get(record_id, 0) == 0
    )
    if missing_education:
        errors.append(
            "resume must preserve every typed education record: " + ", ".join(missing_education)
        )
    duplicated_education = sorted(
        record_id for record_id, count in rendered_education_record_counts.items() if count > 1
    )
    if duplicated_education:
        errors.append(
            "resume must render each typed education record exactly once: "
            + ", ".join(duplicated_education)
        )
    if any(
        isinstance(fact, dict) and fact.get("category") == "skill"
        for fact in evidence.get("facts", [])
    ) and not section_title_matches(sections, TECHNICAL_SECTION_TOKENS):
        errors.append("resume must contain a technical-skills section when skill evidence exists")
    if has_supported_soft_skill_evidence(evidence) and not section_title_matches(sections, SOFT_SECTION_TOKENS):
        errors.append("resume must contain an evidence-backed soft-skills section when supported evidence exists")

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
    if not isinstance(analysis, dict) or set(analysis) != {"matched", "gaps", "credibility_warnings"}:
        errors.append("match_analysis must contain matched, gaps, and credibility_warnings")
        analysis = {}
    matched = analysis.get("matched")
    if not isinstance(matched, list) or not matched:
        errors.append("match_analysis.matched must be non-empty")
    else:
        for index, item in enumerate(matched):
            cited_text(item, candidate_ids, job_keys, f"match_analysis.matched.{index}", errors)
    gaps = analysis.get("gaps")
    if not isinstance(gaps, list):
        errors.append("match_analysis.gaps must be an array")
    else:
        for index, item in enumerate(gaps):
            cited_text(item, candidate_ids, job_keys, f"match_analysis.gaps.{index}", errors)
    credibility_warnings = analysis.get("credibility_warnings")
    if credibility_warnings != evidence.get("warnings", []):
        errors.append("match_analysis.credibility_warnings must copy candidate evidence warnings exactly")
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
    positioning_used = positioning_referenced_ids(bundle)
    positioning_declared = set(strategy.get("positioning_candidate_evidence_ids", []))
    outside_profile = positioning_used - positioning_declared
    if outside_profile:
        errors.append("positioning content uses evidence outside the selected profile: " + ", ".join(sorted(outside_profile)))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--template", type=Path, default=Path(__file__).resolve().parent.parent / "references" / "bundle-template.json")
    args = parser.parse_args()
    try:
        errors = validate(load(args.bundle), load(args.template), args.bundle)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
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
