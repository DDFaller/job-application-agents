"""Choisir le Service Public (French Public Sector) portal scraper."""

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


DEFAULT_CSP_SEARCH_URL = "https://choisirleservicepublic.gouv.fr/nos-offres/"


def parse_csp_listing(html: str, base_url: str = DEFAULT_CSP_SEARCH_URL) -> list[dict[str, str]]:
    """Extract job URLs and references from CSP search HTML."""
    matches = re.findall(r'href=[\'"]([^\'"]*?/offre-emploi/[^\'"]*?)[\'"]', html, re.I)
    jobs: dict[str, dict[str, str]] = {}

    for href in matches:
        full_url = urllib.parse.urljoin(base_url, href)
        clean_url = full_url.split("?")[0]
        ref_match = re.search(r'(?:reference-)?([0-9]{4}-[0-9]+|[0-9]+)/?$', clean_url)
        reference = ref_match.group(1) if ref_match else clean_url.rstrip("/").split("/")[-1]
        
        jobs[clean_url] = {
            "source_portal": "choisir-service-public",
            "source_url": clean_url,
            "reference": reference,
        }

    return list(jobs.values())


def extract_csp_json_ld(html: str) -> dict[str, Any] | None:
    """Extract JobPosting JSON-LD from CSP HTML."""
    script_pattern = re.compile(
        r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>',
        re.I | re.S,
    )
    for raw in script_pattern.findall(html):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                if str(data.get("@type", "")).lower() == "jobposting":
                    return data
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and str(item.get("@type", "")).lower() == "jobposting":
                        return item
        except (json.JSONDecodeError, TypeError):
            continue
    return None


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


def extract_csp_deadline(html: str) -> str | None:
    """Extract application deadline (Date limite de candidature) from CSP HTML."""
    match = re.search(
        r"Date\s+limite(?:\s+de\s+candidature)?\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
        html,
        re.I,
    )
    if match:
        return parse_french_date_to_iso(match.group(1))
    return None


def extract_csp_publication_date(html: str) -> str | None:
    """Extract publication date from CSP HTML."""
    match = re.search(
        r"Date\s+de\s+publication\s*:\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})",
        html,
        re.I,
    )
    if match:
        return parse_french_date_to_iso(match.group(1))
    return None


class CspScraper(BaseJobScraper):
    """Scraper for Choisir le Service Public portal."""

    @property
    def name(self) -> str:
        return "choisir-service-public"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self.http_scraper = HttpJobScraper()

    def scrape(self, url: str, timeout_seconds: int = 30) -> ScrapedJobContent:
        """Fetch CSP job and parse JSON-LD or fallback HTML content with deadline metadata."""
        scraped = self.http_scraper.scrape(url, timeout_seconds=timeout_seconds or self.timeout_seconds)
        json_ld = extract_csp_json_ld(scraped.raw_html)

        # Extract deadline and publication dates from HTML and JSON-LD
        deadline = extract_csp_deadline(scraped.raw_html)
        if not deadline and json_ld and json_ld.get("validThrough"):
            deadline = parse_french_date_to_iso(str(json_ld.get("validThrough")))

        posted_date = extract_csp_publication_date(scraped.raw_html)
        if not posted_date and json_ld and json_ld.get("datePosted"):
            posted_date = parse_french_date_to_iso(str(json_ld.get("datePosted")))

        meta = dict(scraped.meta_tags)
        meta["source_portal"] = "choisir-service-public"
        if deadline:
            meta["closes_at"] = deadline
            meta["deadline"] = deadline
        if posted_date:
            meta["posted_at"] = posted_date

        ref_match = re.search(r'(?:reference-)?([0-9]{4}-[0-9]+|[0-9]+)/?$', url)
        if ref_match:
            meta["reference"] = ref_match.group(1)

        if json_ld:
            title = str(json_ld.get("title") or scraped.title).strip()
            org = json_ld.get("hiringOrganization")
            company = str(org.get("name") if isinstance(org, dict) else org or scraped.company).strip()
            loc_data = json_ld.get("jobLocation")
            location = ""
            if isinstance(loc_data, dict):
                addr = loc_data.get("address")
                if isinstance(addr, dict):
                    location = str(addr.get("addressLocality") or addr.get("streetAddress") or "").strip()
                elif isinstance(addr, str):
                    location = addr.strip()

            desc = str(json_ld.get("description") or scraped.visible_text).strip()
            if deadline and f"Date limite de candidature : {deadline}" not in desc:
                desc = f"Date limite de candidature : {deadline}\n\n{desc}"

            return ScrapedJobContent(
                source_url=scraped.source_url,
                canonical_url=scraped.canonical_url or url,
                title=title,
                company=company,
                location=location or scraped.location,
                raw_html=scraped.raw_html,
                visible_text=desc,
                meta_tags=meta,
                json_ld=[json_ld] if json_ld else scraped.json_ld,
                status_code=scraped.status_code,
                used_playwright=scraped.used_playwright,
                fetch_duration_seconds=scraped.fetch_duration_seconds,
            )

        if deadline and scraped.visible_text and f"Date limite de candidature : {deadline}" not in scraped.visible_text:
            return ScrapedJobContent(
                source_url=scraped.source_url,
                canonical_url=scraped.canonical_url or url,
                title=scraped.title,
                company=scraped.company,
                location=scraped.location,
                raw_html=scraped.raw_html,
                visible_text=f"Date limite de candidature : {deadline}\n\n{scraped.visible_text}",
                meta_tags=meta,
                json_ld=scraped.json_ld,
                status_code=scraped.status_code,
                used_playwright=scraped.used_playwright,
                fetch_duration_seconds=scraped.fetch_duration_seconds,
            )

        return scraped
