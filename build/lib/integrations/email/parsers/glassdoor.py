"""Glassdoor email alerts parser."""

from __future__ import annotations

from html import unescape
import re
from urllib.parse import parse_qs, urlparse

from ...base import BaseEmailParser
from ...models import EmailMessage, JobAlertItem
from .base import HTMLTextExtractor, clean_html_snippet, strip_tracking_params


class GlassdoorJobAlertParser(BaseEmailParser):
    """Parser for Glassdoor job alert emails (jobs-noreply@glassdoor.com)."""

    GLASSDOOR_SENDERS = [
        "jobs-noreply@glassdoor.com",
        "noreply@glassdoor.com",
        "alerts@glassdoor.com",
    ]

    @property
    def supported_senders(self) -> list[str]:
        return list(self.GLASSDOOR_SENDERS)

    def can_parse(self, message: EmailMessage) -> bool:
        sender = message.sender.lower()
        if any(s in sender for s in self.GLASSDOOR_SENDERS):
            return True
        if "glassdoor.com" in sender and "job" in message.subject.lower():
            return True
        if "glassdoor.com/job-listing" in message.body_html or "glassdoor.com/partner/jobListing" in message.body_html:
            return True
        return False

    def parse_jobs(self, message: EmailMessage) -> list[JobAlertItem]:
        jobs: list[JobAlertItem] = []
        html = message.body_html or message.body_plain
        if not html:
            return jobs

        seen_urls: set[str] = set()

        matches = re.finditer(
            r'<a\s+[^>]*href=["\']([^"\']*(?:glassdoor\.com/(?:job-listing|partner/jobListing|Job/[^"\']*))[^"\']*)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )

        for match in matches:
            raw_url = unescape(match.group(1).strip())
            inner_html = match.group(2).strip()

            clean_url = strip_tracking_params(raw_url)
            if not clean_url or clean_url in seen_urls:
                continue

            seen_urls.add(clean_url)
            title = clean_html_snippet(inner_html)
            if not title or len(title) < 3 or title.lower() in ("apply now", "view job", "see more"):
                title = f"Glassdoor Job Listing"

            # Check job listing ID if present in URL
            m_id = re.search(r"jobListingId=(\d+)|jl=(\d+)", raw_url)
            job_id = (m_id.group(1) or m_id.group(2)) if m_id else None

            jobs.append(
                JobAlertItem(
                    title=title,
                    company="Company",
                    location="",
                    raw_url=raw_url,
                    canonical_url=clean_url,
                    source="Other ATS",
                    job_id=job_id,
                    email_uid=message.uid,
                    email_sender=message.sender,
                    metadata={"email_subject": message.subject},
                )
            )

        return jobs
