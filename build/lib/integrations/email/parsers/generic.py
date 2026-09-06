"""Generic heuristic fallback parser for job alert emails from any company."""

from __future__ import annotations

from html import unescape
import re
from urllib.parse import urlparse

from ...base import BaseEmailParser
from ...models import EmailMessage, JobAlertItem
from .base import HTMLTextExtractor, clean_html_snippet, strip_tracking_params


class GenericJobAlertParser(BaseEmailParser):
    """Fallback parser scanning for job links and opportunity titles in arbitrary alert emails."""

    JOB_KEYWORDS = (
        "job",
        "career",
        "position",
        "opening",
        "role",
        "engineer",
        "developer",
        "designer",
        "manager",
        "lead",
        "architect",
        "apply",
        "opportunity",
        "vacancy",
    )

    JOB_URL_PATTERNS = [
        re.compile(r"/jobs?/(?:view|detail|posting|id|\d+)", re.I),
        re.compile(r"/careers?/(?:job|opening|position)", re.I),
        re.compile(r"/positions?/\d+", re.I),
        re.compile(r"job[_-]?id=", re.I),
        re.compile(r"gh_jid=", re.I),
    ]

    @property
    def supported_senders(self) -> list[str]:
        return ["*"]

    def can_parse(self, message: EmailMessage) -> bool:
        # Generic parser is always willing to parse as a fallback
        return True

    def parse_jobs(self, message: EmailMessage) -> list[JobAlertItem]:
        jobs: list[JobAlertItem] = []
        html = message.body_html or message.body_plain
        if not html:
            return jobs

        extractor = HTMLTextExtractor()
        extractor.feed(html)

        seen_urls: set[str] = set()

        for href, link_text in extractor.links:
            clean_url = strip_tracking_params(unescape(href))
            if not clean_url or clean_url in seen_urls:
                continue

            parsed = urlparse(clean_url)
            if not parsed.scheme or not parsed.netloc:
                continue

            # Skip common social/nav/unsubscribe links
            netloc_lower = parsed.netloc.lower()
            path_lower = parsed.path.lower()
            if any(skip in netloc_lower for skip in ("twitter.com", "facebook.com", "instagram.com", "youtube.com", "unsubscribe")):
                continue
            if any(skip in path_lower for skip in ("unsubscribe", "preference", "privacy-policy", "terms-of-service", "settings", "login")):
                continue

            # Check if URL or link text indicates a job posting
            is_job_url = any(p.search(clean_url) for p in self.JOB_URL_PATTERNS)
            is_job_text = any(k in link_text.lower() for k in self.JOB_KEYWORDS)

            if is_job_url or (is_job_text and len(link_text.strip()) > 5):
                seen_urls.add(clean_url)
                title = link_text.strip() or f"Position ({parsed.netloc})"
                if len(title) < 3 or title.lower() in ("click here", "apply now", "view job", "read more"):
                    title = message.subject or f"Job Opening ({parsed.netloc})"

                company = self._infer_company(parsed, message)

                jobs.append(
                    JobAlertItem(
                        title=title,
                        company=company,
                        location="",
                        raw_url=href,
                        canonical_url=clean_url,
                        source="Other ATS",
                        email_uid=message.uid,
                        email_sender=message.sender,
                        snippet=f"{title} at {company}",
                        metadata={"email_subject": message.subject},
                    )
                )

        return jobs

    def _infer_company(self, parsed_url: Any, message: EmailMessage) -> str:
        domain = parsed_url.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        parts = domain.split(".")
        if parts:
            name = parts[0]
            if name not in ("jobs", "careers", "apply", "app", "boards"):
                return name.capitalize()
            elif len(parts) > 1:
                return parts[1].capitalize()
        return "Company"
