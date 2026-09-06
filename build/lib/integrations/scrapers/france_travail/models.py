"""Data models for France Travail (Pôle Emploi) API and portal integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from ...models import NormalizedJobPosting, ScrapedJobContent
from ...pipeline.experience_prefilter import parse_experience_years


def france_travail_public_url(reference: str) -> str:
    """Return canonical candidate URL on France Travail for a job reference."""
    clean_ref = reference.strip()
    return f"https://candidat.francetravail.fr/offres/recherche/detail/{clean_ref}"


def map_experience_to_seniority(experience_level: str) -> str | None:
    """Map France Travail experience text to standardized seniority."""
    exp_lower = experience_level.lower()
    if "débutant" in exp_lower or "junior" in exp_lower or "0 an" in exp_lower or "1 an" in exp_lower:
        return "Junior"
    if "2 an" in exp_lower or "3 an" in exp_lower or "4 an" in exp_lower:
        return "Mid"
    if "5 an" in exp_lower or "6 an" in exp_lower or "7 an" in exp_lower or "8 an" in exp_lower or "confirmé" in exp_lower or "senior" in exp_lower or "expert" in exp_lower:
        return "Senior"
    return experience_level or None


@dataclass(slots=True)
class FranceTravailOffer:
    """Normalized France Travail offer representation."""

    reference: str
    title: str
    company: str = ""
    description: str = ""
    location: str = ""
    postal_code: str = ""
    contract_type: str = ""
    experience_level: str = ""
    salary: str = ""
    skills: list[str] = field(default_factory=list)  # Compétences
    professional_qualities: list[str] = field(default_factory=list)  # Savoir-être professionnels
    date_posted: str = ""
    date_modified: str = ""
    application_url: str = ""
    source_url: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_url and self.reference:
            self.source_url = france_travail_public_url(self.reference)

    def to_scraped_job_content(self) -> ScrapedJobContent:
        """Convert offer to standard ScrapedJobContent with rich metadata."""
        skills_text = "\n".join(f"- {s}" for s in self.skills) if self.skills else ""
        qualities_text = "\n".join(f"- {q}" for q in self.professional_qualities) if self.professional_qualities else ""
        
        visible_parts = [
            f"Titre: {self.title}",
            f"Entreprise: {self.company}" if self.company else "",
            f"Lieu: {self.location}" if self.location else "",
            f"Type de contrat: {self.contract_type}" if self.contract_type else "",
            f"Salaire: {self.salary}" if self.salary else "",
            f"Expérience: {self.experience_level}" if self.experience_level else "",
            f"\nDescription:\n{self.description}" if self.description else "",
            f"\nCompétences:\n{skills_text}" if skills_text else "",
            f"\nSavoir-être professionnels:\n{qualities_text}" if qualities_text else "",
        ]
        visible_text = "\n".join(p for p in visible_parts if p).strip()

        return ScrapedJobContent(
            source_url=self.source_url,
            canonical_url=self.source_url,
            title=self.title,
            company=self.company,
            location=self.location,
            visible_text=visible_text,
            meta_tags={
                "source_portal": "france-travail",
                "reference": self.reference,
                "contract_type": self.contract_type,
                "experience": self.experience_level,
                "competences": json.dumps(self.skills, ensure_ascii=False),
                "savoir_etre_professionnels": json.dumps(self.professional_qualities, ensure_ascii=False),
                "salary": self.salary,
                "postal_code": self.postal_code,
                "date_posted": self.date_posted,
                "application_url": self.application_url,
            },
        )

    def to_normalized_job_posting(self) -> NormalizedJobPosting:
        """Convert offer to schema v2 NormalizedJobPosting with explicit requirements and skills."""
        visible = self.to_scraped_job_content().visible_text
        sha = hashlib.sha256(visible.encode("utf-8")).hexdigest()

        # Build requirements list incorporating both experience level and key competencies
        requirements: list[str] = []
        if self.experience_level:
            requirements.append(f"Expérience requise : {self.experience_level}")
        requirements.extend(self.skills)

        # Build preferred skills / soft skills incorporating Savoir-être professionnels
        preferred: list[str] = list(self.professional_qualities)

        # Responsibilities extracted from description paragraphs
        responsibilities = [
            d.strip() for d in self.description.split("\n")
            if len(d.strip()) > 15 and not d.startswith("-") and not d.startswith("Titre:")
        ][:8]

        return NormalizedJobPosting(
            schema_version=2,
            extraction_status="complete" if self.title and (self.description or self.skills) else "partial",
            source="FranceTravail",
            source_url=self.source_url,
            canonical_url=self.source_url,
            application_url=self.application_url or self.source_url,
            source_job_id=self.reference,
            company=self.company or None,
            role=self.title or None,
            location=self.location or None,
            seniority=map_experience_to_seniority(self.experience_level),
            employment_type=self.contract_type or None,
            experience_level=self.experience_level or None,
            experience_years=parse_experience_years(self.experience_level) if self.experience_level else None,
            posted_at=self.date_posted[:10] if self.date_posted else None,
            responsibilities=responsibilities,
            requirements=requirements,
            preferred_skills=preferred,
            source_document=visible,
            source_sha256=sha,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass(slots=True)
class FranceTravailSearchParams:
    keywords: str = ""
    departments: list[str] = field(default_factory=list)
    page: int = 1
    page_size: int = 20
