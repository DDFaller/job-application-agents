"""Playwright-based stealth browser scraper for bot-protected and dynamic job portals."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from ..base import BaseJobScraper
from ..email.parsers.base import HTMLTextExtractor
from ..models import ScrapedJobContent
from .base import DEFAULT_USER_AGENT

logger = logging.getLogger(__name__)


# Stealth evasion script executed before any page scripts
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en', 'fr-FR', 'fr']
});
window.chrome = {
    runtime: {}
};
"""


class PlaywrightJobScraper(BaseJobScraper):
    """Playwright browser scraper designed to bypass anti-bot challenges and extract dynamic job descriptions."""

    def __init__(
        self,
        headless: bool = True,
        slowmo_ms: int = 0,
    ) -> None:
        self.headless = headless
        self.slowmo_ms = slowmo_ms

    @property
    def name(self) -> str:
        return "playwright"

    def scrape(self, url: str, timeout_seconds: int = 35) -> ScrapedJobContent:
        """Launch browser, navigate to URL with stealth options, and extract complete DOM & text."""
        from playwright.sync_api import sync_playwright

        start_time = time.time()
        timeout_ms = timeout_seconds * 1000

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.headless,
                    slow_mo=self.slowmo_ms,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-infobars",
                        "--window-position=0,0",
                        "--ignore-certifcate-errors",
                        "--ignore-certifcate-errors-spki-list",
                    ],
                )

                context = browser.new_context(
                    user_agent=DEFAULT_USER_AGENT,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="Europe/Paris",
                    bypass_csp=True,
                )

                # Inject stealth script
                context.add_init_script(STEALTH_INIT_SCRIPT)

                page = context.new_page()
                page.set_default_timeout(timeout_ms)

                # Navigate to the job URL
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                status_code = response.status if response else 200
                canonical_url = page.url

                # Wait slightly for dynamic JS rendering
                page.wait_for_timeout(1500)

                # Dismiss common cookie consent dialogues
                self._dismiss_cookie_dialogs(page)

                # Expand collapsed job descriptions if "Show more" button exists
                self._expand_job_description(page)

                # Extract rendered HTML and text
                raw_html = page.content()

                # Extract visible text from body or primary job container
                visible_text = self._extract_visible_text(page)

                # Extract meta tags and JSON-LD
                meta_tags = self._extract_meta_tags(raw_html)
                json_ld_blocks = self._extract_json_ld(raw_html)

                # Extract core fields
                title, company, location = self._extract_core_fields(page, json_ld_blocks, meta_tags)

                screenshot_bytes: bytes | None = None
                if not visible_text or len(visible_text.strip()) < 100:
                    try:
                        screenshot_bytes = page.screenshot(type="png", full_page=False)
                    except Exception:
                        pass

                browser.close()

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
                    used_playwright=True,
                    fetch_duration_seconds=round(duration, 2),
                    screenshot_bytes=screenshot_bytes,
                )

        except Exception as exc:
            duration = time.time() - start_time
            logger.error("Playwright scrape error on %s: %s", url, exc)
            return ScrapedJobContent(
                source_url=url,
                canonical_url=url,
                raw_html="",
                status_code=500,
                used_playwright=True,
                fetch_duration_seconds=round(duration, 2),
                error_message=f"Playwright automation failed: {exc}",
            )

    def _dismiss_cookie_dialogs(self, page: Any) -> None:
        """Attempt to dismiss common EU/GDPR cookie consent overlays."""
        cookie_selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Accept All')",
            "button:has-text('Agree & Join')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Tout accepter')",
            "button:has-text('J\\'accepte')",
            "#onetrust-accept-btn-handler",
            ".artdeco-global-alert-action",
        ]
        for sel in cookie_selectors:
            try:
                locator = page.locator(sel).first
                if locator.is_visible(timeout=500):
                    locator.click(timeout=800)
                    page.wait_for_timeout(300)
                    break
            except Exception:
                continue

    def _expand_job_description(self, page: Any) -> None:
        """Click 'Show more' / 'See more' buttons to reveal full job text."""
        expand_selectors = [
            "button.show-more-less-html__button--more",
            "button[aria-label*='Show more']",
            "button:has-text('Show more')",
            "button:has-text('See more')",
            "button:has-text('En savoir plus')",
            ".jobs-description__footer-button",
            "[data-tracking-control-name='public_jobs_show-more-html-btn']",
        ]
        for sel in expand_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=800)
                    page.wait_for_timeout(400)
                    break
            except Exception:
                continue

    def _extract_visible_text(self, page: Any) -> str:
        """Extract clean text content from the rendered page."""
        # Prefer specific job content containers
        preferred_containers = [
            ".show-more-less-html__markup",
            ".jobs-description__container",
            "#job-details",
            ".job-details",
            "[data-automation-id='jobPostingDescription']",
            ".description",
            "article",
            "main",
        ]
        for selector in preferred_containers:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=500):
                    text = locator.inner_text(timeout=1000)
                    if text and len(text.strip()) > 150:
                        return text.strip()
            except Exception:
                continue

        # Fallback to entire body
        try:
            body_text = page.locator("body").inner_text(timeout=2000)
            return body_text.strip()
        except Exception:
            return ""

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
        page: Any,
        json_ld: list[dict[str, Any]],
        meta_tags: dict[str, str],
    ) -> tuple[str, str, str]:
        title = ""
        company = ""
        location = ""

        # 1. From JSON-LD
        for item in json_ld:
            if item.get("@type") == "JobPosting":
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
                        location = f"{addr.get('addressLocality', '')}, {addr.get('addressCountry', '')}".strip(", ")
                break

        # 2. Page DOM selectors for LinkedIn / standard ATS
        if not title:
            for sel in ("h1.topcard__title", "h1.top-card-layout__title", "h1.job-title", "h1"):
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=300):
                        title = el.inner_text().strip()
                        if title:
                            break
                except Exception:
                    pass

        if not company:
            for sel in ("a.topcard__org-name-link", "span.topcard__flavor", ".topcard__flavor--black-link", "a.company-name"):
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=300):
                        company = el.inner_text().strip()
                        if company:
                            break
                except Exception:
                    pass

        if not location:
            for sel in ("span.topcard__flavor--bullet", "span.topcard__flavor", ".job-location"):
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=300):
                        loc_text = el.inner_text().strip()
                        if loc_text and loc_text != company:
                            location = loc_text
                            break
                except Exception:
                    pass

        if not title:
            title = meta_tags.get("og:title") or ""
        if not company:
            company = meta_tags.get("og:site_name") or ""

        return title, company, location
