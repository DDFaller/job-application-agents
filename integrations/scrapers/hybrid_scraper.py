"""Hybrid scraper combining fast direct HTTP with automatic Playwright fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..base import BaseJobScraper
from ..models import ScrapedJobContent
from .base import is_bot_blocked
from .http_scraper import HttpJobScraper
from .playwright_scraper import PlaywrightJobScraper

logger = logging.getLogger(__name__)


class HybridJobScraper(BaseJobScraper):
    """Use ordinary browser rendering only for accessible, incomplete pages."""

    def __init__(
        self,
        http_scraper: HttpJobScraper | None = None,
        playwright_scraper: PlaywrightJobScraper | None = None,
        min_content_length: int = 150,
        enable_playwright_fallback: bool = True,
    ) -> None:
        self.http_scraper = http_scraper or HttpJobScraper()
        self.playwright_scraper = playwright_scraper or PlaywrightJobScraper()
        self.min_content_length = min_content_length
        self.enable_playwright_fallback = enable_playwright_fallback

    @property
    def name(self) -> str:
        return "hybrid"

    def scrape(self, url: str, timeout_seconds: int = 30) -> ScrapedJobContent:
        """Fetch directly; stop at errors or barriers before considering rendering."""
        logger.info("Attempting direct HTTP scrape for: %s", url)
        start_time = time.time()

        http_result = self.http_scraper.scrape(url, timeout_seconds=min(15, timeout_seconds))

        if (http_result.error_message or not 200 <= http_result.status_code < 300
                or is_bot_blocked(http_result.status_code, http_result.raw_html)):
            if not http_result.error_message:
                http_result.error_message = "HTTP request failed or encountered an access barrier; browser fallback not attempted"
            return http_result

        # Check if HTTP direct scrape succeeded with rich content
        if (
            http_result.is_success
            and len(http_result.visible_text.strip()) >= self.min_content_length
            and not http_result.error_message
        ):
            logger.info("Direct HTTP scrape succeeded for %s (%d chars)", url, len(http_result.visible_text))
            return http_result

        # Check if fallback is enabled
        if not self.enable_playwright_fallback:
            logger.warning("HTTP scrape incomplete and Playwright fallback disabled.")
            return http_result

        # Fallback to Playwright
        logger.warning(
            "Accessible HTTP page needs rendering (Status: %d, Length: %d, Error: %s). Activating Playwright fallback...",
            http_result.status_code,
            len(http_result.visible_text),
            http_result.error_message or "none",
        )

        pw_result = self.playwright_scraper.scrape(url, timeout_seconds=timeout_seconds)

        if pw_result.is_success:
            logger.info("Playwright fallback succeeded for %s (%d chars)", url, len(pw_result.visible_text))
        # Preserve rendering failures, especially authentication or challenges;
        # an earlier incomplete HTML fragment must not hide a later barrier.
        return pw_result
