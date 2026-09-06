"""Welcome to the Jungle scraper implementation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ...base import BaseJobScraper
from ...models import ScrapedJobContent
from ..base import DEFAULT_HTTP_HEADERS
from ..hybrid_scraper import HybridJobScraper
from .extract import find_job_posting, job_from_page_data
from .models import DEFAULT_SEED_URLS, WttjJob, WttjScrapeOptions


def paginated_url(url: str, page_number: int) -> str:
    """Build or replace page query param on a search URL."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class WttjScraper(BaseJobScraper):
    """Scraper specialized in Welcome to the Jungle job listings and posting details."""

    @property
    def name(self) -> str:
        return "welcome-to-the-jungle"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self.underlying_scraper = HybridJobScraper()

    def scrape(self, url: str, timeout_seconds: int = 30) -> ScrapedJobContent:
        """Fetch and extract a single WTTJ job posting via Hybrid (HTTP + Playwright) extraction."""
        scraped = self.underlying_scraper.scrape(url, timeout_seconds=timeout_seconds or self.timeout_seconds)
        if not scraped.is_success and not scraped.raw_html:
            return scraped

        raw_scripts = [json.dumps(obj) for obj in scraped.json_ld]
        wttj_job = job_from_page_data(
            source_url=scraped.canonical_url or url,
            raw_scripts=raw_scripts,
            body_text=scraped.visible_text,
            title_hint=scraped.title,
            raw_html=scraped.raw_html,
        )

        # Merge extracted metadata
        meta = dict(scraped.meta_tags)
        meta.update({
            "contract_type": wttj_job.contract_type,
            "remote": wttj_job.remote,
            "salary": wttj_job.salary,
            "experience": wttj_job.experience,
            "postal_code": wttj_job.postal_code,
            "date_posted": wttj_job.date_posted,
            "valid_through": wttj_job.valid_through,
        })

        return ScrapedJobContent(
            source_url=wttj_job.source_url or scraped.source_url,
            canonical_url=wttj_job.source_url or scraped.canonical_url or url,
            title=wttj_job.title or scraped.title,
            company=wttj_job.company or scraped.company,
            location=wttj_job.location or scraped.location,
            raw_html=scraped.raw_html,
            visible_text=scraped.visible_text or wttj_job.searchable_text(),
            meta_tags=meta,
            json_ld=scraped.json_ld,
            status_code=scraped.status_code,
            used_playwright=scraped.used_playwright,
            fetch_duration_seconds=scraped.fetch_duration_seconds,
            error_message=scraped.error_message,
        )

    def extract_job_from_html(self, html_content: str, source_url: str = "") -> WttjJob:
        """Parse raw HTML and extract structured WttjJob."""
        import re
        script_pattern = re.compile(r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', re.I | re.S)
        scripts = script_pattern.findall(html_content)
        
        clean_body = re.sub(r'<[^>]+>', ' ', html_content)
        clean_body = re.sub(r'\s+', ' ', clean_body).strip()
        
        return job_from_page_data(
            source_url=source_url,
            raw_scripts=scripts,
            body_text=clean_body,
            raw_html=html_content,
        )
