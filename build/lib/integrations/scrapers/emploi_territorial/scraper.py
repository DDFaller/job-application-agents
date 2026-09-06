"""Emploi Territorial (French Territorial Public Sector) portal scraper."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
import urllib.parse

from ...base import BaseJobScraper
from ...models import NormalizedJobPosting, ScrapedJobContent
from ..http_scraper import HttpJobScraper


DEFAULT_TERRITORIAL_SEARCH_URL = "https://www.emploi-territorial.fr/emploi-mobilite/"


def parse_territorial_listing(
    html: str,
    base_url: str = DEFAULT_TERRITORIAL_SEARCH_URL,
) -> list[dict[str, str]]:
    """Extract job URLs and reference IDs from Emploi Territorial listing HTML."""
    matches = re.findall(r'href=[\'"]([^\'"]*?/offre/[^\'"]*?)[\'"]', html, re.I)
    jobs: dict[str, dict[str, str]] = {}

    for href in matches:
        full_url = urllib.parse.urljoin(base_url, href)
        clean_url = full_url.split("?")[0]
        ref_match = re.search(r'/offre/([A-Za-z0-9_-]+)', clean_url)
        reference = ref_match.group(1).split("-")[0] if ref_match else clean_url.rstrip("/").split("/")[-1]

        jobs[clean_url] = {
            "source_portal": "emploi-territorial",
            "source_url": clean_url,
            "reference": reference,
        }

    return list(jobs.values())


def parse_french_date_to_iso(date_str: str) -> str | None:
    """Convert DD/MM/YYYY or YYYY-MM-DD to standard ISO YYYY-MM-DD."""
    clean = date_str.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", clean):
        return clean[:10]
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", clean)
    if m:
        d, mth, y = m.groups()
        return f"{y}-{int(mth):02d}-{int(d):02d}"
    return None


def extract_territorial_publication_date(html: str) -> str | None:
    """Extract publication date (Publiée le ...) from Emploi Territorial HTML."""
    match = re.search(r"Publiée\s+le\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})", html, re.I)
    if match:
        return parse_french_date_to_iso(match.group(1))
    return None


def extract_territorial_deadline(html: str) -> str | None:
    """Extract application deadline from Emploi Territorial HTML if present."""
    match = re.search(
        r"Date\s+limite(?:\s+de\s+candidature)?\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
        html,
        re.I,
    )
    if match:
        return parse_french_date_to_iso(match.group(1))
    return None


class EmploiTerritorialScraper(BaseJobScraper):
    """Scraper for Emploi Territorial portal."""

    @property
    def name(self) -> str:
        return "emploi-territorial"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self.http_scraper = HttpJobScraper()

    def scrape(self, url: str, timeout_seconds: int = 30) -> ScrapedJobContent:
        """Fetch Emploi Territorial job and parse structured content."""
        scraped = self.http_scraper.scrape(url, timeout_seconds=timeout_seconds or self.timeout_seconds)
        if not scraped.is_success and not scraped.raw_html:
            return scraped

        # Extract title and company from <title> or <h2> tag
        title = ""
        company = scraped.company
        title_tag_m = re.search(r'<title>(.*?)</title>', scraped.raw_html, re.I | re.S)
        if title_tag_m:
            raw_title_tag = re.sub(r'\s*\|\s*emploi-territorial\.fr.*$', '', title_tag_m.group(1).strip(), flags=re.I)
            if " - " in raw_title_tag:
                t_parts = raw_title_tag.split(" - ", 1)
                title = t_parts[0].strip()
                if not company or company == "Company":
                    company = t_parts[1].strip()
            else:
                title = raw_title_tag.strip()

        if not title or title.lower() == "www.emploi-territorial.fr":
            h2_m = re.search(r'<h2[^>]*>(.*?)</h2>', scraped.raw_html, re.I | re.S)
            if h2_m:
                clean_h2 = re.sub(r'<[^>]+>', ' ', h2_m.group(1)).strip()
                if clean_h2 and clean_h2.lower() not in ("espace demandeur", "espace employeur", "contact"):
                    title = clean_h2

        if not title:
            title = scraped.title

        # Extract location from reference or HTML
        location = scraped.location
        loc_m = re.search(r'(?:Lieu de travail|Localisation|Département)\s*:\s*(?:<[^>]+>\s*)*([^<\n]+)', scraped.raw_html, re.I)
        if loc_m:
            location = loc_m.group(1).strip()
        elif not location:
            dep_m = re.search(r'/offre/o0?(\d{2,3})', url)
            if dep_m:
                dep_code = dep_m.group(1)
                dep_map = {"75": "Paris (75), France", "92": "Hauts-de-Seine (92), France", "93": "Seine-Saint-Denis (93), France", "94": "Val-de-Marne (94), France", "77": "Seine-et-Marne (77), France", "78": "Yvelines (78), France", "91": "Essonne (91), France", "95": "Val-d'Oise (95), France"}
                location = dep_map.get(dep_code, f"Département {dep_code}, France")

        meta = dict(scraped.meta_tags)
        meta["source_portal"] = "emploi-territorial"

        ref_match = re.search(r'/offre/([A-Za-z0-9_-]+)', url)
        if ref_match:
            meta["reference"] = ref_match.group(1).split("-")[0]

        posted_at = extract_territorial_publication_date(scraped.raw_html)
        if posted_at:
            meta["posted_at"] = posted_at
            meta["date_posted"] = posted_at

        deadline = extract_territorial_deadline(scraped.raw_html)
        if deadline:
            meta["closes_at"] = deadline
            meta["deadline"] = deadline

        visible = scraped.visible_text
        if posted_at and f"Date de publication : {posted_at}" not in visible:
            visible = f"Date de publication : {posted_at}\n\n{visible}".strip()
        if deadline and f"Date limite de candidature : {deadline}" not in visible:
            visible = f"Date limite de candidature : {deadline}\n\n{visible}".strip()

        return ScrapedJobContent(
            source_url=scraped.source_url,
            canonical_url=scraped.canonical_url or url,
            title=title,
            company=company,
            location=location,
            raw_html=scraped.raw_html,
            visible_text=visible,
            meta_tags=meta,
            json_ld=scraped.json_ld,
            status_code=scraped.status_code,
            used_playwright=scraped.used_playwright,
            fetch_duration_seconds=scraped.fetch_duration_seconds,
            error_message=scraped.error_message,
        )
