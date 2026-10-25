"""Transparent scoring of validated candidate/job evidence, not hiring odds."""

from __future__ import annotations

import math
from typing import Any


RUBRIC_VERSION = "evidence-fit-v1"
PRIORITY_WEIGHT = 60
REQUIREMENT_WEIGHT = 40


def score_profile(
    ranking: dict[str, Any], priorities: list[dict[str, Any]],
    required_keys: set[str], *, seniority_ok: bool,
) -> dict[str, Any]:
    """Called only after positioning has validated references and assessments.

    Unknown evidence produces a score interval, never a fabricated match or a
    proven shortfall. Each job requirement counts once, even when a check cites
    several fields. Duplicate checks are rejected by the positioning validator.
    """
    criteria: list[dict[str, Any]] = []
    for index, assessment in enumerate(ranking["priorities"]):
        level = assessment["level"]
        value = {"direct": 1.0, "transferable": 0.5, "unsupported": None}[level]
        criteria.append({
            "id": f"priority.{index}", "label": priorities[index]["text"],
            "weight": PRIORITY_WEIGHT / len(priorities), "status": level,
            "value": value, "fact_ids": assessment["fact_ids"],
            "job_keys": assessment["job_keys"], "rationale": assessment["rationale"],
        })
    checks = {key: check for check in ranking["mandatory_checks"] for key in check["job_keys"]}
    for key in sorted(required_keys):
        assessment = checks[key]
        status = assessment["status"]
        criteria.append({
            "id": key, "label": key, "weight": REQUIREMENT_WEIGHT / len(required_keys),
            "status": status,
            "value": {"met": 1.0, "learning_allowed": 0.5, "unmet": 0.0, "unknown": None}[status],
            "fact_ids": assessment["fact_ids"], "job_keys": [key],
            "rationale": assessment["rationale"],
        })
    # Missing extracted requirements must not turn duty coverage into 100% fit.
    if not required_keys:
        criteria.append({
            "id": "requirements", "label": "Requirements not established",
            "weight": REQUIREMENT_WEIGHT, "status": "unknown", "value": None,
            "fact_ids": [], "job_keys": [], "rationale": "No requirements or constraints were extracted.",
        })
    earned = sum(c["weight"] * c["value"] for c in criteria if c["value"] is not None)
    unknown_weight = sum(c["weight"] for c in criteria if c["value"] is None)
    gaps = [c for c in criteria if c["status"] in {"unmet", "unknown", "unsupported", "learning_allowed", "transferable"}]
    blockers = [c["id"] for c in criteria if c["status"] in {"unmet", "unknown", "unsupported"}]
    if not seniority_ok:
        blockers.append("seniority")
    return {
        "rubric_version": RUBRIC_VERSION, "profile_id": ranking["profile_id"],
        # Conservative rounding prevents a value below a threshold rounding up.
        "score": math.floor(earned + 1e-9),
        "score_upper_bound": min(100, math.ceil(earned + unknown_weight - 1e-9)),
        "evidence_coverage": math.floor(100 - unknown_weight + 1e-9),
        "criteria": criteria, "gaps": gaps, "automatic_blockers": blockers,
        "seniority_compatible": seniority_ok, "rationale": ranking["rationale"],
        "submission_authorized": False,
    }


def automatic_eligibility(assessment: dict[str, Any], threshold: int | None = None) -> dict[str, Any]:
    """Report threshold eligibility only. This never authorizes submission."""
    if threshold is not None and (type(threshold) is not int or not 0 <= threshold <= 100):
        raise ValueError("automatic fit threshold must be an integer from 0 to 100")
    score = assessment.get("score")
    eligible = (
        threshold is not None and type(score) is int and score >= threshold
        and assessment.get("evidence_coverage") == 100
        and assessment.get("automatic_blockers") == []
        and assessment.get("seniority_compatible") is True
    )
    return {"threshold": threshold, "eligible": eligible, "submission_authorized": False}
