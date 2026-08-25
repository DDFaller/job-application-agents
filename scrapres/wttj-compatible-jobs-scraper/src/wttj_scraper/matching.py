from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import Evaluation, Job
from .text import fold


def load_profile(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        profile = json.load(handle)
    required = (
        "profile_version",
        "minimum_score",
        "allowed_departments",
        "accepted_contracts",
        "direct_title_terms",
        "mission_clusters",
    )
    missing = [key for key in required if key not in profile]
    if missing:
        raise ValueError(f"Perfil incompleto: {', '.join(missing)}")
    return profile


def _contains(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if fold(term) in text]


def _department(postal_code: str) -> str:
    digits = re.sub(r"\D", "", postal_code)
    return digits[:2] if len(digits) >= 2 else ""


def evaluate_job(job: Job, profile: dict[str, Any], minimum_score: int | None = None) -> Evaluation:
    title = fold(job.title)
    text = fold(job.searchable_text())
    location = fold(f"{job.location} {job.postal_code}")
    hard: list[str] = []
    gaps: list[str] = []
    reasons: list[str] = []
    evidence: set[str] = set()
    score = 0

    excluded = _contains(title, profile.get("excluded_title_terms", []))
    if excluded:
        hard.append(f"Título especializado ou contrato excluído: {', '.join(excluded)}")

    contract = fold(job.contract_type)
    forbidden_contracts = ("stage", "alternance", "apprentissage")
    if any(term in contract or term in title for term in forbidden_contracts):
        hard.append("Estágio, alternância ou aprendizagem não são aceitos.")
    accepted_contracts = [fold(value) for value in profile.get("accepted_contracts", [])]
    if contract and accepted_contracts and not any(value in contract for value in accepted_contracts):
        hard.append(f"Contrato fora do perfil: {job.contract_type}.")

    department = _department(job.postal_code)
    allowed_departments = set(profile.get("allowed_departments", []))
    allowed_locations = [fold(value) for value in profile.get("allowed_location_terms", [])]
    if department:
        if department not in allowed_departments:
            hard.append(f"Departamento {department} fora do perímetro permitido.")
    elif not any(term and term in location for term in allowed_locations):
        hard.append("Localização não confirmada no perímetro permitido.")

    if re.search(r"\b(?:bac\s*\+?\s*[45]|master|mba)\b", text):
        hard.append("Formação Bac+4/Bac+5 ou Master explicitamente solicitada.")
    if re.search(r"\bpermis\s*b\b", text):
        hard.append("Permis B solicitado sem evidência aprovada no perfil.")
    if re.search(r"anglais.{0,30}(?:bilingue|courant|c1|c2)|(?:bilingue|courant|c1|c2).{0,30}anglais", text):
        hard.append("Inglês avançado ou bilíngue explicitamente solicitado.")
    if re.search(r"francais.{0,30}(?:langue maternelle|c1|c2)|(?:langue maternelle|c1|c2).{0,30}francais", text):
        hard.append("Francês C1/C2 ou nativo explicitamente solicitado.")

    direct = _contains(title, profile.get("direct_title_terms", []))
    adjacent = _contains(title, profile.get("adjacent_title_terms", []))
    if direct:
        score += 30
        reasons.append(f"Título administrativo direto: {direct[0]}.")
    elif adjacent:
        score += 18
        reasons.append(f"Título administrativo adjacente: {adjacent[0]}.")
    else:
        hard.append("Título sem correspondência administrativa suficiente.")

    matched_clusters = 0
    for cluster in profile.get("mission_clusters", []):
        matches = _contains(text, cluster.get("terms", []))
        if not matches:
            continue
        matched_clusters += 1
        score += 5
        reasons.append(f"Missão compatível ({cluster['id']}): {matches[0]}.")
        evidence.update(cluster.get("evidence_ids", []))
    if matched_clusters < 2:
        hard.append("Menos de duas famílias de missões administrativas confirmadas.")

    office_matches = _contains(text, profile.get("office_terms", []))
    if office_matches:
        score += 10
        reasons.append(f"Ferramenta de escritório compatível: {office_matches[0]}.")
        evidence.update(profile.get("office_evidence_ids", []))

    experience_match = re.search(r"\b(?:experience|expérience).{0,50}(?:[1-9]|confirmee|confirmee|significative|similaire)", text)
    if experience_match or matched_clusters >= 3:
        score += 10
        reasons.append("Experiência administrativa aprovada sustenta as missões.")
        evidence.update(profile.get("experience_evidence_ids", []))

    if re.search(r"\bfrancais\b|\bfrançais\b", job.searchable_text(), re.I):
        score += 5
        reasons.append("Francês B2 documentado.")
        evidence.update(profile.get("language_evidence_ids", []))

    if not hard:
        score += 10
        reasons.append("Localização confirmada no perímetro de Noisy-le-Grand/Paris.")

    if re.search(r"\bbac\s*\+?\s*[23]\b", text):
        score -= 5
        gaps.append("A equivalência francesa Bac+2/Bac+3 do diploma estrangeiro não está estabelecida.")
    if re.search(r"formation.{0,50}(?:gestion administrative|assistanat|secretariat)", text):
        score -= 10
        gaps.append("Formação específica em administração/assistanat não consta no perfil aprovado.")

    score = max(0, min(100, score))
    cutoff = int(minimum_score if minimum_score is not None else profile["minimum_score"])
    compatible = not hard and score >= cutoff
    if not hard and score < cutoff:
        gaps.append(f"Score {score} abaixo do corte {cutoff}.")

    return Evaluation(
        compatible=compatible,
        score=score,
        match_reasons=reasons,
        matched_evidence_ids=sorted(evidence),
        gaps=gaps,
        hard_rejections=hard,
    )

