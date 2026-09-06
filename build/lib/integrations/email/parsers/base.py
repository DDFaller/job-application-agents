"""Base email parser and text/URL utility helpers."""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from ...base import BaseEmailParser
from ...models import EmailMessage, JobAlertItem


class HTMLTextExtractor(HTMLParser):
    """Simple, dependency-free HTML to plain text stripper with link retention."""

    def __init__(self) -> None:
        super().__init__()
        self.reset()
        self.fed: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, text)
        self._current_href: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            for attr, val in attrs:
                if attr.lower() == "href" and val:
                    self._current_href = val
                    self._current_link_text = []
                    break
        elif tag.lower() in ("p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.fed.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href:
            link_text = "".join(self._current_link_text).strip()
            self.links.append((self._current_href, link_text))
            self._current_href = None
            self._current_link_text = []
        elif tag.lower() in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self.fed.append("\n")

    def handle_data(self, d: str) -> None:
        self.fed.append(d)
        if self._current_href is not None:
            self._current_link_text.append(d)

    def get_text(self) -> str:
        raw = "".join(self.fed)
        # Normalize multiple spaces and blank lines
        lines = [line.strip() for line in raw.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        return unescape(cleaned)


def strip_tracking_params(url: str, keep_params: set[str] | None = None) -> str:
    """Strip marketing/tracking query parameters from URLs (utm_*, trk, trackingId, etc.)."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url

        allowed = set(k.lower() for k in (keep_params or set()))
        tracking_keys_prefixes = ("utm_", "trk", "ref", "midtoken", "midsig", "trkemail", "eid", "otptoken", "li_fat_id")
        tracking_exact_keys = {"trackingid", "refid", "ref_id", "source", "ref", "trk", "alertidx"}

        q_dict = parse_qs(parsed.query, keep_blank_values=False)
        cleaned_query: list[tuple[str, str]] = []

        for key, values in q_dict.items():
            key_lower = key.lower()
            if key_lower in allowed:
                for v in values:
                    cleaned_query.append((key, v))
                continue

            if any(key_lower.startswith(p) for p in tracking_keys_prefixes):
                continue
            if key_lower in tracking_exact_keys:
                continue

            for v in values:
                cleaned_query.append((key, v))

        new_query = urlencode(cleaned_query)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    except Exception:
        return url


def clean_html_snippet(html_text: str) -> str:
    """Convert HTML string to clean single-line text snippet."""
    extractor = HTMLTextExtractor()
    extractor.feed(html_text)
    text = extractor.get_text()
    return re.sub(r"\s+", " ", text).strip()
