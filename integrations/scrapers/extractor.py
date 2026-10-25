"""Semantic normalization and evidence extraction for scraped job postings."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from ..email.parsers.base import strip_tracking_params
from ..models import JobAlertItem, NormalizedJobPosting, ScrapedJobContent
from ..pipeline.experience_prefilter import parse_experience_years


TECH_KEYWORDS = [
    "Python", "TypeScript", "JavaScript", "Go", "Golang", "Rust", "Java", "C++", "C#",
    "FastAPI", "Flask", "Django", "React", "Vue", "Next.js", "Node.js", "Express",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "BigQuery", "Snowflake", "Kafka",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Helm", "ArgoCD", "AWS", "GCP", "Azure",
    "Linux", "CI/CD", "GitHub Actions", "GitLab CI", "Datadog", "Prometheus", "Grafana",
    "OpenTelemetry", "PyTorch", "TensorFlow", "LangChain", "LlamaIndex", "Playwright", "GraphQL", "REST",
]

WORK_MODEL_PATTERNS = {
    "Remote": [r"\bremote\b", r"\btélétravail\b", r"\bwork from home\b", r"\bfully remote\b"],
    "Hybrid": [r"\bhybrid\b", r"\bhybride\b", r"\bpartially remote\b", r"\b\d+\s*days\s*(?:in|at)\s*office\b"],
    "On-site": [r"\bon-site\b", r"\bon site\b", r"\bin-office\b", r"\bsur site\b", r"\bprésentiel\b"],
}

SENIORITY_PATTERNS = {
    "Senior": [r"\bsenior\b", r"\bsr\b", r"\bprincipal\b", r"\bstaff\b", r"\blead\b"],
    "Mid": [r"\bmid\b", r"\bintermediate\b", r"\bconfirmé\b"],
    "Junior": [r"\bjunior\b", r"\bjr\b", r"\bentry[- ]level\b", r"\bgraduate\b", r"\bdébutant\b"],
}

EMPLOYMENT_TYPE_PATTERNS = {
    "Full-time": [r"\bfull[- ]time\b", r"\bcdi\b", r"\bpermanent\b", r"\btemps plein\b"],
    "Part-time": [r"\bpart[- ]time\b", r"\btemps partiel\b"],
    "Contract": [r"\bcontract\b", r"\bfreelance\b", r"\bcdd\b", r"\bcontractor\b", r"\bprestation\b"],
    "Internship": [r"\binternship\b", r"\bintern\b", r"\bstage\b", r"\balternance\b", r"\bapprenticeship\b"],
}


def _public_job_url(url: str) -> str:
    """Keep public job identity without email authentication or tracking data."""
    parsed = urlparse(url)
    if parsed.hostname == "linkedin.com" or (parsed.hostname or "").endswith(".linkedin.com"):
        match = re.search(r"/(?:comm/)?jobs/view/(\d+)", parsed.path)
        if match:
            return f"https://www.linkedin.com/jobs/view/{match.group(1)}"
    return strip_tracking_params(url)


class JobPostingExtractor:
    """Structures scraped web content into canonical, validated job.json and source.md."""

    def extract(
        self,
        scraped: ScrapedJobContent,
        alert_hint: JobAlertItem | None = None,
        output_dir: Path | None = None,
    ) -> tuple[NormalizedJobPosting, str]:
        """Convert scraped content into NormalizedJobPosting and verbatim source.md content."""
        extracted_at = datetime.now(timezone.utc).isoformat()

        # Build clean source.md
        source_text = self._build_source_markdown(scraped, alert_hint)
        source_bytes = source_text.encode("utf-8")
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()

        source_doc_path = None
        if output_dir:
            source_file = output_dir / "source.md"
            source_file.write_text(source_text, encoding="utf-8")
            source_doc_path = str(source_file.resolve())

        # Resolve core fields
        company = scraped.company or (alert_hint.company if alert_hint else "") or ""
        role = scraped.title or (alert_hint.title if alert_hint else "") or ""
        location = scraped.location or (alert_hint.location if alert_hint else "") or ""

        # Unescape HTML entities (e.g. &amp; -> &)
        import html
        role = html.unescape(html.unescape(role)).strip()
        if company:
            company = html.unescape(html.unescape(company)).strip()

        # Extract location embedded in company string (e.g. "Alarm.com — Cracow, Poland | LinkedIn Jobs")
        if " — " in company:
            parts = company.split(" — ", 1)
            company = parts[0].strip()
            if not location:
                loc_cand = re.sub(r"\s*\|.*$", "", parts[1]).strip()
                if loc_cand:
                    location = loc_cand

        company = re.sub(r"\s*(?:—|\|).*$", "", company).strip()
        location = re.sub(r"\s*\|.*$", "", location).strip()

        # Parse LinkedIn pattern "<Company> hiring <Role> in <Location>"
        hiring_match = re.match(r"^(.+?)\s+hiring\s+(.+?)(?:\s+in\s+(.+))?$", role, re.IGNORECASE)
        if hiring_match:
            detected_company = hiring_match.group(1).strip()
            detected_role = hiring_match.group(2).strip()
            detected_loc = hiring_match.group(3).strip() if hiring_match.group(3) else None
            if not company or company == "Company":
                company = detected_company
            role = detected_role
            if detected_loc and not location:
                location = detected_loc
        elif " at " in role:
            parts = role.split(" at ", 1)
            role = parts[0].strip()
            if not company or company == "Company":
                company = parts[1].strip()
        elif " | " in role:
            role = role.split(" | ", 1)[0].strip()
        elif " - " in role:
            parts = role.rsplit(" - ", 1)
            if len(parts) == 2 and len(parts[1].strip()) < 35 and (not company or company == "Company"):
                role = parts[0].strip()
                company = parts[1].strip()
            elif len(role.split(" - ")[0]) > 4:
                role = role.split(" - ")[0].strip()

        company = re.sub(r"\s*(?:—|\|).*$", "", company).strip()
        location = re.sub(r"\s*\|.*$", "", location).strip()

        source_type = "LinkedIn" if "linkedin.com" in scraped.source_url.lower() else "Other ATS"
        source_url = _public_job_url(
            (alert_hint.canonical_url or alert_hint.raw_url) if alert_hint else scraped.source_url
        )
        application_url = _public_job_url(scraped.canonical_url or source_url)
        source_job_id = alert_hint.job_id if alert_hint else None
        if not source_job_id:
            m = re.search(r"/jobs/view/(\d+)", source_url or scraped.canonical_url)
            if m:
                source_job_id = m.group(1)

        # Detect work model, seniority, employment type, technologies, and dates
        work_model = self._detect_work_model(source_text)
        seniority = self._detect_seniority(role, source_text)
        employment_type = self._detect_employment_type(source_text)
        technologies = self._detect_technologies(source_text)
        language = self._detect_language(source_text)
        posted_at = self._detect_posted_date(scraped, source_text)
        closes_at = self._detect_deadline(scraped, source_text)
        experience_level, experience_years = self._detect_experience(scraped, source_text)

        # Extract structured lists
        responsibilities, requirements, preferred_skills = self._extract_sections(source_text)

        # Missing evidence remains missing; discovery is not a completed extraction.
        missing_fields = [name for name, value in (("company", company), ("role", role)) if not value]
        if not responsibilities and not requirements:
            missing_fields.extend(("responsibilities", "requirements"))
        status = "partial" if missing_fields else "complete"
        warnings = []
        if not scraped.is_success:
            status = "blocked"
            warnings.append("Public posting retrieval failed or returned insufficient content")

        # Construct field-level evidence dictionary
        field_evidence = self._generate_field_evidence(
            source_text=source_text,
            company=company,
            role=role,
            location=location,
            work_model=work_model,
            employment_type=employment_type,
            seniority=seniority,
            experience_level=experience_level,
            language=language,
            source_job_id=source_job_id,
            posted_at=posted_at,
            closes_at=closes_at,
            responsibilities=responsibilities,
            requirements=requirements,
            preferred_skills=preferred_skills,
            technologies=technologies,
        )

        job_posting = NormalizedJobPosting(
            schema_version=2,
            extraction_status=status,
            source=source_type,
            source_url=source_url,
            canonical_url=application_url,
            application_url=application_url,
            source_job_id=source_job_id,
            company=company or None,
            role=role or None,
            location=location or None,
            work_model=work_model,
            employment_type=employment_type,
            seniority=seniority,
            experience_level=experience_level,
            experience_years=experience_years,
            language=language,
            posted_at=posted_at,
            closes_at=closes_at,
            responsibilities=responsibilities,
            requirements=requirements,
            preferred_skills=preferred_skills,
            technologies=technologies,
            application_instructions=[],
            source_document=source_doc_path,
            source_sha256=source_sha256,
            field_evidence=field_evidence,
            missing_fields=missing_fields,
            warnings=warnings,
            extracted_at=extracted_at,
        )

        return job_posting, source_text

    def _build_source_markdown(self, scraped: ScrapedJobContent, alert_hint: JobAlertItem | None) -> str:
        """Construct raw source.md containing visible posting text and metadata."""
        lines: list[str] = []
        company = scraped.company or (alert_hint.company if alert_hint else "")
        title = scraped.title or (alert_hint.title if alert_hint else "")
        location = scraped.location or (alert_hint.location if alert_hint else "")

        if title:
            lines.append(f"# {title}")
        if company:
            lines.append(f"**Company:** {company}")
        if location:
            lines.append(f"**Location:** {location}")
        source_url = _public_job_url(
            (alert_hint.canonical_url or alert_hint.raw_url) if alert_hint else scraped.source_url
        )
        application_url = _public_job_url(scraped.canonical_url or source_url)
        if source_url:
            lines.append(f"**Source URL:** {source_url}")
        if application_url:
            lines.append(f"**Application URL:** {application_url}")
        lines.append("")

        if scraped.visible_text:
            lines.append(scraped.visible_text.strip())
        elif alert_hint and alert_hint.snippet:
            lines.append(alert_hint.snippet)

        return "\n".join(lines).strip() + "\n"

    def _detect_work_model(self, text: str) -> str:
        for model, patterns in WORK_MODEL_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text, re.I):
                    return model
        return "Unspecified"

    def _detect_seniority(self, role: str, text: str) -> str | None:
        for level, patterns in SENIORITY_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, role, re.I):
                    return level
        for level, patterns in SENIORITY_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text[:500], re.I):
                    return level
        return None

    def _detect_employment_type(self, text: str) -> str | None:
        for emp_type, patterns in EMPLOYMENT_TYPE_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text, re.I):
                    return emp_type
        return None

    def _detect_technologies(self, text: str) -> list[str]:
        found: list[str] = []
        for tech in TECH_KEYWORDS:
            pattern = rf"\b{re.escape(tech)}\b"
            if re.search(pattern, text, re.I) and tech not in found:
                found.append(tech)
        return found[:12]

    def _detect_language(self, text: str) -> str:
        french_words = ["responsabilités", "profil", "recherché", "expérience", "missions", "compétences"]
        count = sum(1 for w in french_words if w in text.lower())
        return "fr" if count >= 2 else "en"

    def _extract_sections(self, text: str) -> tuple[list[str], list[str], list[str]]:
        responsibilities: list[str] = []
        requirements: list[str] = []
        preferred_skills: list[str] = []

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        current_section = "none"

        for line in lines:
            lower = line.lower()
            if any(k in lower for k in ("responsibilit", "missions", "what you will do", "what you'll do", "your role")):
                current_section = "resp"
                continue
            elif any(k in lower for k in ("requirement", "qualification", "what you need", "what you bring", "profil", "who you are")):
                current_section = "req"
                continue
            elif any(k in lower for k in ("preferred", "bonus", "nice to have", "plus")):
                current_section = "pref"
                continue
            elif line.startswith("#") or (line.endswith(":") and len(line) < 35):
                current_section = "other"
                continue

            # Check if bullet point
            if line.startswith(("-", "*", "•", "–")) or re.match(r"^\d+[\.\)]\s+", line):
                clean_item = re.sub(r"^[-*•–\d\.\)]+\s*", "", line).strip()
                # Ignore boilerplate and form notices
                lower_item = clean_item.lower()
                if any(b in lower_item for b in ("champs obligatoires", "données personnelles", "politique de confidentialité", "tous droits réservés")):
                    continue
                if len(clean_item) > 10:
                    if current_section == "resp" and len(responsibilities) < 8:
                        responsibilities.append(clean_item)
                    elif current_section == "req" and len(requirements) < 8:
                        requirements.append(clean_item)
                    elif current_section == "pref" and len(preferred_skills) < 5:
                        preferred_skills.append(clean_item)

        return responsibilities, requirements, preferred_skills

    def _parse_iso_date(self, date_str: str) -> str | None:
        """Parse various date formats (DD/MM/YYYY, YYYY-MM-DD, ISO timestamps) into YYYY-MM-DD."""
        if not date_str:
            return None
        clean = str(date_str).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", clean):
            return clean[:10]
        m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", clean)
        if m:
            d, mth, y = m.groups()
            return f"{y}-{int(mth):02d}-{int(d):02d}"
        return None

    def _detect_deadline(self, scraped: ScrapedJobContent, text: str) -> str | None:
        """Detect application deadline (closes_at) from metadata, JSON-LD, or body text."""
        if scraped.meta_tags.get("closes_at"):
            parsed = self._parse_iso_date(scraped.meta_tags["closes_at"])
            if parsed:
                return parsed
        if scraped.meta_tags.get("deadline"):
            parsed = self._parse_iso_date(scraped.meta_tags["deadline"])
            if parsed:
                return parsed

        for jld in (scraped.json_ld or []):
            if isinstance(jld, dict) and jld.get("validThrough"):
                parsed = self._parse_iso_date(str(jld["validThrough"]))
                if parsed:
                    return parsed

        # Search in visible text or raw HTML
        patterns = [
            r"Date\s+limite(?:\s+de\s+candidature)?\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
            r"Date\s+de\s+clôture\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
            r"Date\s+de\s+fin(?:\s+de\s+publication)?\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
            r"(?:deadline|apply\s+before|closing\s+date)\s*:\s*(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        ]
        target_texts = [text, scraped.raw_html or ""]
        for target in target_texts:
            for pat in patterns:
                m = re.search(pat, target, re.I)
                if m:
                    parsed = self._parse_iso_date(m.group(1))
                    if parsed:
                        return parsed
        return None

    def _detect_posted_date(self, scraped: ScrapedJobContent, text: str) -> str | None:
        """Detect date posted from metadata, JSON-LD, or body text."""
        if scraped.meta_tags.get("posted_at"):
            parsed = self._parse_iso_date(scraped.meta_tags["posted_at"])
            if parsed:
                return parsed
        if scraped.meta_tags.get("date_posted"):
            parsed = self._parse_iso_date(scraped.meta_tags["date_posted"])
            if parsed:
                return parsed

        for jld in (scraped.json_ld or []):
            if isinstance(jld, dict) and jld.get("datePosted"):
                parsed = self._parse_iso_date(str(jld["datePosted"]))
                if parsed:
                    return parsed

        patterns = [
            r"Date\s+de\s+publication\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
            r"Publiée?\s+le\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
            r"(?:posted\s+on|posted\s+date)\s*:\s*(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
        ]
        target_texts = [text, scraped.raw_html or ""]
        for target in target_texts:
            for pat in patterns:
                m = re.search(pat, target, re.I)
                if m:
                    parsed = self._parse_iso_date(m.group(1))
                    if parsed:
                        return parsed
        return None

    def _detect_experience(self, scraped: ScrapedJobContent, source_text: str) -> tuple[str | None, float | None]:
        """Detect experience requirement string and parsed numerical years."""
        # 1. Meta tags / direct scraper fields
        meta_exp = (
            scraped.meta_tags.get("experience")
            or scraped.meta_tags.get("experience_level")
            or scraped.meta_tags.get("experienceRequirements")
        )
        if meta_exp and str(meta_exp).strip():
            years = parse_experience_years(str(meta_exp))
            if years is not None:
                return str(meta_exp).strip(), years

        # 2. Check JSON-LD metadata if present
        for ld in (scraped.json_ld or []):
            if isinstance(ld, dict):
                exp_req = ld.get("experienceRequirements")
                if exp_req:
                    if isinstance(exp_req, dict):
                        months = exp_req.get("monthsOfExperience")
                        if months is not None:
                            return f"{months} mois", round(float(months) / 12.0, 2)
                    elif isinstance(exp_req, str):
                        clean_req = str(exp_req).strip()
                        years = parse_experience_years(clean_req)
                        if years is not None:
                            return clean_req, years

        # 3. Text search
        years = parse_experience_years(source_text)
        if years is not None:
            # Locate snippet in source text
            for line in source_text.splitlines():
                if parse_experience_years(line) == years and len(line.strip()) < 100:
                    return line.strip(), years
            return f"{years:g} year{'s' if years != 1 else ''} experience", years

        return None, None

    def _generate_field_evidence(
        self,
        source_text: str,
        company: str,
        role: str,
        location: str,
        work_model: str,
        employment_type: str | None,
        seniority: str | None,
        language: str | None,
        source_job_id: str | None,
        experience_level: str | None = None,
        posted_at: str | None = None,
        closes_at: str | None = None,
        responsibilities: list[str] | None = None,
        requirements: list[str] | None = None,
        preferred_skills: list[str] | None = None,
        technologies: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Generate verifiable exact quote evidence mapped to source.md content."""
        evidence: dict[str, list[str]] = {}

        def find_best_quote(target: str, default_quote: str) -> list[str]:
            if target and target.lower() in source_text.lower():
                # Find line containing target
                for line in source_text.splitlines():
                    if target.lower() in line.lower() and len(line.strip()) > 3:
                        return [line.strip()]
            return []

        # Scalar fields
        if company:
            evidence["company"] = find_best_quote(company, f"Company: {company}")
        if role:
            evidence["role"] = find_best_quote(role, role)
        if location:
            evidence["location"] = find_best_quote(location, location)
        if work_model != "Unspecified":
            evidence["work_model"] = find_best_quote(work_model, f"Work model: {work_model}")
        if employment_type:
            evidence["employment_type"] = find_best_quote(employment_type, employment_type)
        if seniority:
            evidence["seniority"] = find_best_quote(seniority, seniority)
        if experience_level:
            evidence["experience_level"] = find_best_quote(experience_level, f"Expérience: {experience_level}")
        if language:
            evidence["language"] = find_best_quote("English" if language == "en" else "Français", f"Language: {language}")
        if source_job_id:
            evidence["source_job_id"] = find_best_quote(source_job_id, f"Job ID: {source_job_id}")
        if posted_at:
            evidence["posted_at"] = find_best_quote(posted_at, f"Date de publication: {posted_at}")
        if closes_at:
            evidence["closes_at"] = find_best_quote(closes_at, f"Date limite de candidature: {closes_at}")

        # Array fields
        for idx, resp in enumerate(responsibilities or []):
            evidence[f"responsibilities.{idx}"] = find_best_quote(resp[:30], resp)

        for idx, req in enumerate(requirements or []):
            evidence[f"requirements.{idx}"] = find_best_quote(req[:30], req)

        for idx, pref in enumerate(preferred_skills or []):
            evidence[f"preferred_skills.{idx}"] = find_best_quote(pref[:30], pref)

        for idx, tech in enumerate(technologies or []):
            evidence[f"technologies.{idx}"] = find_best_quote(tech, tech)

        # Normalized labels may differ from the literal source wording.
        for field, value, patterns in (
            ("work_model", work_model, WORK_MODEL_PATTERNS),
            ("employment_type", employment_type, EMPLOYMENT_TYPE_PATTERNS),
            ("seniority", seniority, SENIORITY_PATTERNS),
        ):
            if value and not evidence.get(field):
                for line in source_text.splitlines():
                    if any(re.search(pattern, line, re.I) for pattern in patterns.get(value, [])):
                        evidence[field] = [line.strip()]
                        break
        if language and not evidence.get("language"):
            # This is the posting's language, supported by its actual text.
            excerpt = next((line.strip() for line in source_text.splitlines()
                            if len(line.strip()) > 20 and not line.startswith("**")), None)
            if excerpt:
                evidence["language"] = [excerpt]
        return {key: quotes for key, quotes in evidence.items() if quotes}
