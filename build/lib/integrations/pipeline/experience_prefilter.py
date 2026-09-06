"""Zero-token heuristic experience prefilter for job openings."""

from __future__ import annotations

from dataclasses import dataclass
import html
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExperienceFilterDecision:
    """Result of evaluating a job against experience criteria."""

    passed: bool
    reason: str
    required_years: float | None = None
    max_allowed_years: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "required_years": self.required_years,
            "max_allowed_years": self.max_allowed_years,
        }


WORD_NUMS = {
    "un": 1.0,
    "une": 1.0,
    "one": 1.0,
    "1er": 1.0,
    "premiere": 1.0,
    "première": 1.0,
    "deux": 2.0,
    "two": 2.0,
    "trois": 3.0,
    "three": 3.0,
    "quatre": 4.0,
    "four": 4.0,
    "cinq": 5.0,
    "five": 5.0,
    "six": 6.0,
    "sept": 7.0,
    "seven": 7.0,
    "huit": 8.0,
    "eight": 8.0,
    "neuf": 9.0,
    "nine": 9.0,
    "dix": 10.0,
    "ten": 10.0,
}

NUM_PAT = r"(?:\d+(?:[.,]\d+)?|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|one|two|three|four|five|six|seven|eight|nine|ten|premi[èe]re)"


def _to_float(val: str | None) -> float | None:
    if not val:
        return None
    val_clean = val.strip().lower()
    if val_clean in WORD_NUMS:
        return WORD_NUMS[val_clean]
    try:
        return float(val_clean.replace(",", "."))
    except ValueError:
        return None


def parse_experience_years(text: str | None) -> float | None:
    """Extract required years of experience from job descriptions or metadata text.

    Supports French and English expressions, word numbers (cinq, deux, three, etc.),
    month conversions, operators (>, >=, +, etc.), ranges, and entry-level indicators.
    """
    if not text or not isinstance(text, str):
        return None

    clean = html.unescape(text).strip()
    if not clean:
        return None

    # Normalise newlines and multiple spaces
    clean_flat = re.sub(r"\s+", " ", clean)

    # 1. Check entry-level / beginner phrasing (0 years)
    if re.search(
        r"\b(d[ée]butant\s*accept[ée]|jeune\s*dipl[oô]m[ée]|d[ée]butant\b|sans\s*exp[ée]rience|0\s*an(?:s)?\s*d['’]exp[ée]rience|no\s*experience\s*required|entry[- ]level|fresh\s*graduate)\b",
        clean_flat,
        re.I,
    ):
        return 0.0

    # 2. Check for explicit "Non spécifié" / "Not specified" in metadata label
    if re.search(
        r"^exp[ée]rience\s*:\s*(?:non\s*sp[ée]cifi[ée]|unspecified|not\s*specified)\b",
        clean_flat,
        re.I,
    ):
        return None

    # Strip label prefixes if present (e.g. "Expérience :", "Expérience requise :", "Experience:")
    target = re.sub(
        r"^exp[ée]rience\s*(?:professionnelle\s*)?(?:exig[ée]e|souhait[ée]e|requise|minimale|level|required)?\s*[:=-]?\s*",
        "",
        clean_flat,
        flags=re.I,
    ).strip()

    # 3. Leading comparison operators / standalone numbers + years or months:
    # e.g. "> 5 ans", ">5 ans", ">= 3 years", "≥ 3 ans", "+5 ans", "5+ years", "5 ans", "2 years", "1 an", "6 mois", "> 6 mois"
    m_simple_mth = re.search(r"^[><≥≤>=+~]?\s*(\d+)\+?\s*(?:months?|mois)\b", target, re.I)
    if m_simple_mth:
        try:
            return round(float(m_simple_mth.group(1)) / 12.0, 2)
        except ValueError:
            pass

    m_simple_yrs = re.search(
        r"^[><≥≤>=+~]?\s*(" + NUM_PAT + r")\+?\s*(?:[-–—àa/to]+\s*" + NUM_PAT + r")?\s*(?:an\(s\)|ans?\(s\)?|years?|yrs?|an|ans|ann[ée]e|ann[ée]es)\b",
        target,
        re.I,
    )
    if m_simple_yrs:
        val = _to_float(m_simple_yrs.group(1))
        if val is not None:
            return val

    # 4. France Travail standard metadata & colon-separated / newline-separated expressions:
    # e.g. "Expérience 5 An(s)", "Expérience\n5 An(s)", "Expérience exigée de 1 An(s)", "Expérience requise : 2 ans"
    m_ft_years = re.search(
        r"exp[ée]rience\s*(?:professionnelle\s*)?(?:exig[ée]e|souhait[ée]e|requise|minimale)?\s*(?:[:=-]|\n)?\s*(?:d['’]au\s*moins|de|plus\s+de)?\s*[><≥≤>=+~]?\s*(" + NUM_PAT + r")\s*(?:an\(s\)|ans?\(s\)?|an|ans|ann[ée]e|ann[ée]es)\b",
        clean_flat,
        re.I,
    )
    if m_ft_years:
        val = _to_float(m_ft_years.group(1))
        if val is not None:
            return val

    m_ft_months = re.search(
        r"exp[ée]rience\s*(?:professionnelle\s*)?(?:exig[ée]e|souhait[ée]e|requise|minimale)?\s*(?:[:=-]|\n)?\s*(?:d['’]au\s*moins|de|plus\s+de)?\s*[><≥≤>=+~]?\s*(\d+)\s*mois",
        clean_flat,
        re.I,
    )
    if m_ft_months:
        try:
            return round(float(m_ft_months.group(1)) / 12.0, 2)
        except ValueError:
            pass

    # 5. General French patterns within larger text:
    # "vous justifiez au minimum de cinq années d’expérience", "2 ans d'expérience", "plus de 5 ans d'expérience"
    m_fr = re.search(
        r"(?:vous\s+justifiez\s+(?:d['’]|de\s+)?|justifiant\s+(?:d['’]|de\s+)?|au\s*moins\s+|plus\s+de\s+|environ\s+|minimum\s+(?:de\s+)?|au\s+minimum\s+(?:de\s+)?)?(" + NUM_PAT + r")\s*(?:[-–—àa]\s*" + NUM_PAT + r")?\s*(?:an\(s\)|ans?\(s\)?|an|ans|ann[ée]e|ann[ée]es)\s+d['’]exp[ée]rience",
        clean_flat,
        re.I,
    )
    if m_fr:
        val = _to_float(m_fr.group(1))
        if val is not None:
            return val

    # French months in text: "6 mois d'expérience"
    m_fr_mth = re.search(r"(\d+)\s*mois\s+d['’]exp[ée]rience", clean_flat, re.I)
    if m_fr_mth:
        try:
            return round(float(m_fr_mth.group(1)) / 12.0, 2)
        except ValueError:
            pass

    # 6. General English patterns within larger text:
    # "5+ years of software engineering experience", "minimum of five years of experience", "1-2 years of experience"
    m_en = re.search(
        r"(?:minimum\s+(?:of\s+)?|more\s+than\s+|at\s+least\s+)?(" + NUM_PAT + r")\+?\s*(?:[-–—to]+\s*" + NUM_PAT + r")?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:[\w-]+\s+){0,5}experience",
        clean_flat,
        re.I,
    )
    if m_en:
        val = _to_float(m_en.group(1))
        if val is not None:
            return val

    # "experience: 3+ years", "experience of 2+ years", "experience level: 5 years"
    m_en_post = re.search(
        r"experience\s*(?:required|needed|level)?\s*[:=-]?\s*(?:minimum\s+(?:of\s+)?|at\s+least\s+)?(" + NUM_PAT + r")\+?\s*(?:years?|yrs?)",
        clean_flat,
        re.I,
    )
    if m_en_post:
        val = _to_float(m_en_post.group(1))
        if val is not None:
            return val

    # English months: "6 months of experience"
    m_en_mth = re.search(r"(\d+)\+?\s*months?\s+of\s+experience", clean_flat, re.I)
    if m_en_mth:
        try:
            return round(float(m_en_mth.group(1)) / 12.0, 2)
        except ValueError:
            pass

    return None


class JobExperiencePrefilter:
    """Zero-token heuristic gate filtering out jobs exceeding maximum required experience."""

    def __init__(
        self,
        max_experience_years: float | int | None = 1.0,
        allow_unspecified: bool = True,
    ) -> None:
        self.max_experience_years = float(max_experience_years) if max_experience_years is not None else None
        self.allow_unspecified = allow_unspecified

    def evaluate(
        self,
        experience_text: str | None = None,
        experience_years: float | int | None = None,
        max_experience_years: float | int | None = None,
        job_text: str | None = None,
    ) -> ExperienceFilterDecision:
        """Evaluate job experience requirements against maximum allowed years."""
        effective_max = (
            float(max_experience_years)
            if max_experience_years is not None
            else self.max_experience_years
        )

        # If max experience is not set (None or < 0), no filter is applied
        if effective_max is None or effective_max < 0:
            return ExperienceFilterDecision(
                passed=True,
                reason="Experience filter is disabled; passed by default",
                max_allowed_years=effective_max,
            )

        # Resolve required experience years
        req_years: float | None = None
        if experience_years is not None:
            try:
                req_years = float(experience_years)
            except ValueError:
                pass
        elif experience_text:
            req_years = parse_experience_years(experience_text)
        elif job_text:
            req_years = parse_experience_years(job_text)

        if req_years is None:
            if self.allow_unspecified:
                return ExperienceFilterDecision(
                    passed=True,
                    reason="No explicit experience requirement detected; passed by default",
                    required_years=None,
                    max_allowed_years=effective_max,
                )
            return ExperienceFilterDecision(
                passed=False,
                reason="Experience requirement not specified and allow_unspecified is False",
                required_years=None,
                max_allowed_years=effective_max,
            )

        if req_years > effective_max:
            reason = (
                f"Required experience ({req_years:g} year{'s' if req_years != 1 else ''}) "
                f"exceeds maximum allowed threshold of {effective_max:g} year{'s' if effective_max != 1 else ''}"
            )
            logger.debug("JobExperiencePrefilter rejected: %s", reason)
            return ExperienceFilterDecision(
                passed=False,
                reason=reason,
                required_years=req_years,
                max_allowed_years=effective_max,
            )

        return ExperienceFilterDecision(
            passed=True,
            reason=(
                f"Required experience ({req_years:g} year{'s' if req_years != 1 else ''}) "
                f"is within threshold (≤ {effective_max:g} year{'s' if effective_max != 1 else ''})"
            ),
            required_years=req_years,
            max_allowed_years=effective_max,
        )

    def evaluate_job(
        self,
        job: Any,
        max_experience_years: float | int | None = None,
    ) -> ExperienceFilterDecision:
        """Evaluate a NormalizedJobPosting, dict, or object."""
        exp_years = None
        exp_text = None

        if isinstance(job, dict):
            exp_years = job.get("experience_years")
            exp_text = job.get("experience_level") or job.get("experience")
            if not exp_text and isinstance(job.get("requirements"), list):
                exp_text = "\n".join(job.get("requirements", []))
            if not exp_text and job.get("role"):
                exp_text = job.get("role")
        else:
            exp_years = getattr(job, "experience_years", None)
            exp_text = getattr(job, "experience_level", None)
            if not exp_text and hasattr(job, "requirements"):
                reqs = getattr(job, "requirements", [])
                if isinstance(reqs, list):
                    exp_text = "\n".join(reqs)
            if not exp_text and hasattr(job, "role"):
                exp_text = getattr(job, "role", None)

        return self.evaluate(
            experience_text=exp_text,
            experience_years=exp_years,
            max_experience_years=max_experience_years,
        )


def filter_job_by_experience(
    job: Any,
    max_experience_years: float | int | None = 1.0,
    allow_unspecified: bool = True,
) -> ExperienceFilterDecision:
    """Convenience function to evaluate job experience requirement (default: max 1 year).

    Args:
        job: NormalizedJobPosting instance, dict with job fields, or object with experience fields.
        max_experience_years: Maximum allowed required experience in years (default: 1.0). None disables.
        allow_unspecified: Whether to pass jobs where no experience requirement is explicitly stated.

    Returns:
        ExperienceFilterDecision containing pass/fail, rejection reason, and extracted required years.
    """
    prefilter = JobExperiencePrefilter(
        max_experience_years=max_experience_years,
        allow_unspecified=allow_unspecified,
    )
    return prefilter.evaluate_job(job)
