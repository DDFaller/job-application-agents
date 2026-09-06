"""Extraction of Welcome to the Jungle job postings from HTML and JSON-LD."""

from __future__ import annotations

from collections.abc import Iterable
import json
import re
from typing import Any

from .models import WttjJob
from .text import clean_text, strip_html


def _iter_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _iter_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_objects(nested)


def find_job_posting(raw_scripts: Iterable[str]) -> dict[str, Any] | None:
    """Find and return schema.org/JobPosting dictionary from raw script tags."""
    for raw in raw_scripts:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in _iter_objects(payload):
            kind = candidate.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(str(item).lower() == "jobposting" for item in kinds):
                return candidate
    return None


def _organization_name(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name"))
    return clean_text(value)


def _address(payload: dict[str, Any]) -> tuple[str, str]:
    location = payload.get("jobLocation") or payload.get("applicantLocationRequirements") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    if not isinstance(location, dict):
        return clean_text(location), ""
    address = location.get("address", location)
    if not isinstance(address, dict):
        return clean_text(address), ""
    postal_code = clean_text(address.get("postalCode"))
    pieces = [
        address.get("streetAddress"),
        postal_code,
        address.get("addressLocality"),
        address.get("addressRegion"),
        address.get("addressCountry"),
    ]
    return ", ".join(clean_text(piece) for piece in pieces if clean_text(piece)), postal_code


def _employment_type(value: Any) -> str:
    if isinstance(value, list):
        value = " / ".join(clean_text(item) for item in value)
    folded = clean_text(value).upper()
    replacements = {
        "FULL_TIME": "CDI",
        "PART_TIME": "TEMPS PARTIEL",
        "TEMPORARY": "TEMPORAIRE",
        "INTERN": "STAGE",
        "CONTRACTOR": "CDD",
    }
    return replacements.get(folded, folded)


def _salary(payload: dict[str, Any]) -> str:
    salary = payload.get("baseSalary")
    if not salary:
        return ""
    if not isinstance(salary, dict):
        return clean_text(salary)
    currency = clean_text(salary.get("currency"))
    value = salary.get("value", salary)
    if isinstance(value, dict):
        minimum = clean_text(value.get("minValue"))
        maximum = clean_text(value.get("maxValue"))
        unit = clean_text(value.get("unitText"))
        numbers = " - ".join(item for item in (minimum, maximum) if item)
        return clean_text(" ".join(item for item in (numbers, currency, unit) if item))
    return clean_text(value)


def _fallback_contract(body_text: str) -> str:
    beginning = body_text[:1500]
    match = re.search(r"\b(CDI|CDD|Stage|Alternance|Apprentissage|Intérim|Interim)\b", beginning, re.I)
    return match.group(1).upper() if match else ""


def _fallback_postal_code(body_text: str) -> str:
    matches = re.findall(r"\b(7[578]\d{3}|9[234]\d{3})\b", body_text)
    return matches[-1] if matches else ""


def _extract_canonical_url(payload: dict[str, Any], raw_html: str, fallback_url: str = "") -> str:
    """Extract canonical job URL from JSON-LD, og:url, canonical link, or internal WTTJ job link."""
    if payload.get("url") and isinstance(payload.get("url"), str):
        return clean_text(payload["url"])
    if payload.get("sameAs") and isinstance(payload.get("sameAs"), str):
        return clean_text(payload["sameAs"])

    og_match = re.search(r'<meta\s+property=[\'"]og:url[\'"]\s+content=[\'"]([^\'"]+)[\'"]', raw_html, re.I)
    if og_match:
        return clean_text(og_match.group(1))

    canonical_match = re.search(r'<link\s+rel=[\'"]canonical[\'"]\s+href=[\'"]([^\'"]+)[\'"]', raw_html, re.I)
    if canonical_match:
        return clean_text(canonical_match.group(1))

    # Search for direct WTTJ company job link in the HTML
    job_link_match = re.search(r'href=[\'"](https://www\.welcometothejungle\.com/(?:fr|en)/companies/[^/\'"]+/jobs/[^\'"]+)[\'"]', raw_html)
    if job_link_match:
        return clean_text(job_link_match.group(1))

    return fallback_url


def _experience(payload: dict[str, Any], raw_html: str, body_text: str) -> str:
    """Extract experience requirement from JSON-LD, HTML metadata block, or body text."""
    exp_req = payload.get("experienceRequirements")
    if exp_req:
        if isinstance(exp_req, dict):
            months = exp_req.get("monthsOfExperience")
            if months is not None:
                return f"{months} mois"
        elif isinstance(exp_req, str):
            clean = clean_text(exp_req)
            if clean and "non spécifi" not in clean.lower():
                return clean

    html_match = re.search(
        r"Expérience\s*:\s*(?:</span>)?\s*(&gt;|>|≥|&ge;|<|&lt;|≤|&le;)?\s*([^<]+?)(?:</div>|</div|<span|$)",
        raw_html,
        re.I,
    )
    if html_match:
        prefix = clean_text(html_match.group(1) or "")
        val = clean_text(html_match.group(2) or "")
        full_val = f"{prefix} {val}".strip() if prefix else val
        if full_val and "non spécifi" not in full_val.lower():
            return full_val

    text_match = re.search(
        r"Expérience\s*:\s*([^\n\r]+?)(?:\s*(?:Éducation|Salaire|Début|Télétravail|Compétences|$))",
        body_text,
        re.I,
    )
    if text_match:
        val = clean_text(text_match.group(1))
        if val and "non spécifi" not in val.lower():
            return val

    return ""


def job_from_page_data(
    source_url: str,
    raw_scripts: Iterable[str],
    body_text: str,
    title_hint: str = "",
    raw_html: str = "",
) -> WttjJob:
    """Extract structured WttjJob from page scripts and body text."""
    payload = find_job_posting(raw_scripts) or {}
    resolved_url = _extract_canonical_url(payload, raw_html, fallback_url=source_url)
    location, postal_code = _address(payload)
    title = clean_text(payload.get("title") or title_hint)
    description = strip_html(payload.get("description"))
    qualifications = strip_html(payload.get("qualifications") or payload.get("skills"))

    if not postal_code:
        postal_code = _fallback_postal_code(body_text)
    if not location:
        address_match = re.search(
            r"Le lieu de travail\s+(.{1,180}?)(?:Postuler|Vous cherchez un job|$)",
            body_text,
            re.I | re.S,
        )
        location = clean_text(address_match.group(1)) if address_match else ""
    if not description:
        match = re.search(
            r"Descriptif du poste\s+(.+?)(?:Profil recherché|Envie d.en savoir plus|L'entreprise)",
            body_text,
            re.I | re.S,
        )
        description = clean_text(match.group(1)) if match else clean_text(body_text)
    contract_type = _employment_type(payload.get("employmentType")) or _fallback_contract(body_text)

    remote = ""
    if re.search(r"télétravail fréquent", body_text, re.I):
        remote = "fréquent"
    elif re.search(r"télétravail occasionnel", body_text, re.I):
        remote = "occasionnel"
    elif re.search(r"télétravail non autorisé", body_text, re.I):
        remote = "non autorisé"

    experience = _experience(payload, raw_html, body_text)

    return WttjJob(
        source_url=resolved_url,
        title=title,
        company=_organization_name(payload.get("hiringOrganization")),
        location=location,
        postal_code=postal_code,
        contract_type=contract_type,
        remote=remote,
        salary=_salary(payload),
        experience=experience,
        date_posted=clean_text(payload.get("datePosted")),
        valid_through=clean_text(payload.get("validThrough")),
        description=description,
        qualifications=qualifications,
    )
