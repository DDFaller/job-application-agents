"""Parsers for ATS and direct employer job notifications (Greenhouse, Lever, Ashby, Workable, Otta)."""

from __future__ import annotations

from html import unescape
import re
from urllib.parse import urlparse

from ...base import BaseEmailParser
from ...models import EmailMessage, JobAlertItem
from .base import HTMLTextExtractor, clean_html_snippet, strip_tracking_params


class DirectATSPostingParser(BaseEmailParser):
    """Parser for recruiter and ATS alert emails containing direct application links."""

    ATS_DOMAINS = [
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "workable.com",
        "otta.com",
        "welcomekit.co",
        "smartrecruiters.com",
    ]

    ATS_SENDERS = [
        "no-reply@greenhouse.io",
        "jobs@lever.co",
        "notifications@otta.com",
        "no-reply@ashbyhq.com",
        "noreply@workablemail.com",
    ]

    @property
    def supported_senders(self) -> list[str]:
        return list(self.ATS_SENDERS)

    def can_parse(self, message: EmailMessage) -> bool:
        sender = message.sender.lower()
        if any(s in sender for s in self.ATS_SENDERS):
            return True
        if any(domain in sender for domain in self.ATS_DOMAINS):
            return True
        # Check if body contains links to known ATS domains
        html = message.body_html or message.body_plain
        return any(domain in html for domain in self.ATS_DOMAINS)

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
            domain = parsed.netloc.lower()

            if any(ats in domain for ats in self.ATS_DOMAINS):
                seen_urls.add(clean_url)
                title = link_text.strip() or message.subject
                company = self._infer_company_from_url_or_sender(parsed, message)

                # Determine source
                source = "Other ATS"
                if "greenhouse.io" in domain:
                    source = "Greenhouse"
                elif "lever.co" in domain:
                    source = "Lever"
                elif "ashbyhq.com" in domain:
                    source = "Ashby"
                elif "workable.com" in domain:
                    source = "Workable"
                elif "otta.com" in domain:
                    source = "Otta"

                jobs.append(
                    JobAlertItem(
                        title=title,
                        company=company,
                        location="",
                        raw_url=href,
                        canonical_url=clean_url,
                        source=source,
                        email_uid=message.uid,
                        email_sender=message.sender,
                        metadata={"email_subject": message.subject},
                    )
                )

        return jobs

    def _infer_company_from_url_or_sender(self, parsed_url: Any, message: EmailMessage) -> str:
        # e.g. jobs.lever.co/company_name/job-id
        path_parts = [p for p in parsed_url.path.split("/") if p]
        if "lever.co" in parsed_url.netloc and path_parts:
            return path_parts[0].capitalize()
        if "greenhouse.io" in parsed_url.netloc and len(path_parts) >= 2:
            return path_parts[0].capitalize() if path_parts[0] != "embed" else path_parts[1].capitalize()
        if "ashbyhq.com" in parsed_url.netloc and path_parts:
            return path_parts[0].capitalize()

        # From sender name if possible
        if "@" in message.sender:
            domain = message.sender.split("@")[-1].split(".")[0]
            if domain not in ("greenhouse", "lever", "ashbyhq", "workable", "gmail", "otta"):
                return domain.capitalize()

        return "Company"
