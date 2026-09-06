"""Base scraper definitions, anti-bot detection, and HTTP headers."""

from __future__ import annotations

from abc import ABC, abstractmethod
import re
from typing import Any

from ..base import BaseJobScraper
from ..models import ScrapedJobContent


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HTTP_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


BOT_BLOCK_INDICATORS = [
    "cloudflare",
    "cf-browser-verification",
    "turnstile",
    "datadome",
    "perimeterx",
    "px-captcha",
    "arkose",
    "access denied",
    "error 403",
    "error 999",
    "please verify you are a human",
    "unusual traffic from your computer",
    "enable javascript to continue",
    "security check to continue",
    "bot detected",
    "rate limit exceeded",
    "join linkedin to view",
    "sign in to see more jobs",
]


def is_bot_blocked(status_code: int, html_body: str) -> bool:
    """Detect if a webpage blocked direct access via HTTP status or anti-bot challenge DOM."""
    if status_code in (403, 429, 999, 503):
        return True

    if not html_body or len(html_body.strip()) < 200:
        return True

    lower_body = html_body.lower()
    for indicator in BOT_BLOCK_INDICATORS:
        if indicator in lower_body:
            return True

    return False
