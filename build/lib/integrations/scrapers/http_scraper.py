"""Fast direct HTTP scraper for job postings."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from ..base import BaseJobScraper
from ..email.parsers.base import HTMLTextExtractor
from ..models import ScrapedJobContent
from .base import DEFAULT_HTTP_HEADERS, is_bot_blocked

logger = logging.getLogger(__name__)


class HttpJobScraper(BaseJobScraper):
    """Direct HTTP request scraper with JSON-LD and meta tag extraction."""

    @property
    def name(self) -> str:
        return "http"

    def scrape(self, url: str, timeout_seconds: int = 25) -> ScrapedJobContent:
        """Fetch job posting using direct HTTP requests."""
        start_time = time.time()
        canonical_url = url
        raw_html = ""
        meta_tags: dict[str, str] = {}
        json_ld_blocks: list[dict[str, Any]] = []
        visible_text = ""
        title = ""
        company = ""
        location = ""
        status_code = 0
        error_msg: str | None = None

        try:
            with httpx.Client(
                headers=DEFAULT_HTTP_HEADERS,
                follow_redirects=True,
                timeout=timeout_seconds,
            ) as client:
                response = client.get(url)
                status_code = response.status_code
                canonical_url = str(response.url)
                raw_html = response.text

            # Check for bot block or anti-bot challenge
            if is_bot_blocked(status_code, raw_html):
                duration = time.time() - start_time
                return ScrapedJobContent(
                    source_url=url,
                    canonical_url=canonical_url,
                    raw_html=raw_html,
                    status_code=status_code,
                    used_playwright=False,
                    fetch_duration_seconds=round(duration, 2),
                    error_message=f"HTTP direct request blocked or challenged (Status: {status_code})",
                )

            # Extract metadata and JSON-LD
            meta_tags = self._extract_meta_tags(raw_html)
            json_ld_blocks = self._extract_json_ld(raw_html)

            # Extract visible text
            extractor = HTMLTextExtractor()
            extractor.feed(raw_html)
            visible_text = extractor.get_text()

            # Infer title, company, location from JSON-LD or meta tags
            title, company, location = self._extract_core_fields(json_ld_blocks, meta_tags, raw_html)

            duration = time.time() - start_time
            return ScrapedJobContent(
                source_url=url,
                canonical_url=canonical_url,
                title=title,
                company=company,
                location=location,
                raw_html=raw_html,
                visible_text=visible_text,
                meta_tags=meta_tags,
                json_ld=json_ld_blocks,
                status_code=status_code,
                used_playwright=False,
                fetch_duration_seconds=round(duration, 2),
            )

        except Exception as exc:
            duration = time.time() - start_time
            logger.warning("HTTP direct scrape failed for %s: %s", url, exc)
            return ScrapedJobContent(
                source_url=url,
                canonical_url=canonical_url,
                raw_html=raw_html,
                status_code=status_code or 500,
                used_playwright=False,
                fetch_duration_seconds=round(duration, 2),
                error_message=str(exc),
            )

    def _extract_meta_tags(self, html: str) -> dict[str, str]:
        tags: dict[str, str] = {}
        matches = re.finditer(
            r'<meta\s+[^>]*(?:name|property)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']',
            html,
            re.IGNORECASE,
        )
        for m in matches:
            tags[m.group(1).lower()] = m.group(2).strip()
        return tags

    def _extract_json_ld(self, html: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        matches = re.finditer(
            r'<script\s+[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        for m in matches:
            content = m.group(1).strip()
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    blocks.append(data)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            blocks.append(item)
            except Exception:
                continue
        return blocks

    def _extract_core_fields(
        self,
        json_ld: list[dict[str, Any]],
        meta_tags: dict[str, str],
        html: str,
    ) -> tuple[str, str, str]:
        title = ""
        company = ""
        location = ""

        # 1. Inspect JSON-LD for JobPosting
        for item in json_ld:
            item_type = item.get("@type", "")
            if item_type == "JobPosting" or (isinstance(item_type, list) and "JobPosting" in item_type):
                title = str(item.get("title", ""))
                org = item.get("hiringOrganization", {})
                if isinstance(org, dict):
                    company = str(org.get("name", ""))
                elif isinstance(org, str):
                    company = org

                loc = item.get("jobLocation", {})
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    if isinstance(addr, dict):
                        city = addr.get("addressLocality", "")
                        country = addr.get("addressCountry", "")
                        location = f"{city}, {country}".strip(", ")
                    elif isinstance(addr, str):
                        location = addr
                break

        # 2. Inspect OpenGraph meta tags
        if not title:
            title = meta_tags.get("og:title") or meta_tags.get("twitter:title") or ""
        if not company:
            company = meta_tags.get("og:site_name") or meta_tags.get("application-name") or ""
        if not location:
            location = meta_tags.get("job:location") or meta_tags.get("place:location:latitude") or ""

        # 3. HTML title tag fallback
        if not title:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if m:
                title = m.group(1).strip()

        return title, company, location
