"""Specialized parser for LinkedIn job alert emails (jobalerts-noreply@linkedin.com)."""

from __future__ import annotations

from html import unescape
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from ...base import BaseEmailParser
from ...models import EmailMessage, JobAlertItem
from .base import HTMLTextExtractor, clean_html_snippet, strip_tracking_params


class LinkedInJobAlertParser(BaseEmailParser):
    """Parser specifically targeting LinkedIn job alert emails."""

    LINKEDIN_SENDERS = [
        "jobalerts-noreply@linkedin.com",
        "jobs-listings@linkedin.com",
        "updates-noreply@linkedin.com",
        "messages-noreply@linkedin.com",
    ]

    @property
    def supported_senders(self) -> list[str]:
        return list(self.LINKEDIN_SENDERS)

    def can_parse(self, message: EmailMessage) -> bool:
        sender_clean = message.sender.lower()
        if any(s in sender_clean for s in self.LINKEDIN_SENDERS):
            return True
        if "linkedin.com" in sender_clean and ("job" in message.subject.lower() or "alert" in message.subject.lower()):
            return True
        # Check body content heuristics
        if "linkedin.com/jobs/view" in message.body_html or "linkedin.com/comm/jobs/view" in message.body_html:
            return True
        return False

    def parse_jobs(self, message: EmailMessage) -> list[JobAlertItem]:
        """Extract job listings from a LinkedIn alert email."""
        jobs: list[JobAlertItem] = []
        html = message.body_html or message.body_plain

        if not html:
            return jobs

        # Strategy 1: Structured HTML parsing for LinkedIn email cards
        jobs = self._parse_html_job_cards(html, message)

        # Strategy 2: Fallback regex link scanner if structured parsing found nothing
        if not jobs:
            jobs = self._parse_regex_links(html, message)

        return jobs

    def _parse_html_job_cards(self, html: str, message: EmailMessage) -> list[JobAlertItem]:
        """Parse structured HTML blocks representing LinkedIn job recommendations."""
        jobs: list[JobAlertItem] = []
        seen_job_ids: set[str] = set()

        # Extract all <a> tags with job links
        # Match pattern: <a [^>]*href="([^"]*(?:linkedin\.com/(?:comm/)?jobs/view/|jobPostingId=)[^"]*)"[^>]*>(.*?)</a>
        link_matches = re.finditer(
            r'<a\s+[^>]*href=["\']([^"\']*(?:linkedin\.com/(?:comm/)?jobs/view/|jobPostingId=)[^"\']*)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )

        for match in link_matches:
            raw_url = unescape(match.group(1).strip())
            inner_html = match.group(2).strip()

            job_id, canonical_url = self._extract_linkedin_job_id_and_canonical(raw_url)
            if not job_id or job_id in seen_job_ids:
                continue

            # Extract title from link or surrounding context
            title = clean_html_snippet(inner_html)
            if not title or len(title) < 3 or title.lower() in ("view job", "apply", "see all jobs", "save"):
                # Title might be in surrounding table/card
                title, company, location, salary = self._extract_card_context(html, raw_url)
            else:
                company, location, salary = self._extract_company_and_location_near(html, raw_url, title)

            if not title:
                title = f"Opportunity ({job_id})"

            seen_job_ids.add(job_id)
            jobs.append(
                JobAlertItem(
                    title=title,
                    company=company or "Company",
                    location=location or "",
                    raw_url=raw_url,
                    canonical_url=canonical_url,
                    source="LinkedIn",
                    job_id=job_id,
                    salary_text=salary,
                    email_uid=message.uid,
                    email_sender=message.sender,
                    snippet=f"{title} at {company or 'Company'} - {location or 'Location'}",
                    metadata={"email_subject": message.subject},
                )
            )

        return jobs

    def _extract_linkedin_job_id_and_canonical(self, url: str) -> tuple[str | None, str]:
        """Extract numeric LinkedIn job ID and build clean canonical URL."""
        # Check /jobs/view/1234567890
        m = re.search(r"/jobs/view/(\d+)", url)
        if m:
            job_id = m.group(1)
            return job_id, f"https://www.linkedin.com/jobs/view/{job_id}"

        # Check jobPostingId=1234567890 in query params
        try:
            parsed = urlparse(url)
            q = parse_qs(parsed.query)
            if "jobPostingId" in q and q["jobPostingId"]:
                job_id = q["jobPostingId"][0]
                return job_id, f"https://www.linkedin.com/jobs/view/{job_id}"
            if "currentJobId" in q and q["currentJobId"]:
                job_id = q["currentJobId"][0]
                return job_id, f"https://www.linkedin.com/jobs/view/{job_id}"
        except Exception:
            pass

        # Check numeric ID at end of path
        m_num = re.search(r"/(\d{8,12})(?:[/?#]|$)", url)
        if m_num:
            job_id = m_num.group(1)
            return job_id, f"https://www.linkedin.com/jobs/view/{job_id}"

        clean_url = strip_tracking_params(url)
        return None, clean_url

    def _extract_card_context(self, html: str, target_url: str) -> tuple[str, str, str, str | None]:
        """Find the table row / div containing target_url and extract title, company, location."""
        idx = html.find(target_url)
        if idx == -1:
            return "", "", "", None

        # Look in a window of 800 chars before and 800 chars after
        start = max(0, idx - 800)
        end = min(len(html), idx + 800)
        window = html[start:end]

        extractor = HTMLTextExtractor()
        extractor.feed(window)
        lines = [
            line.strip()
            for line in extractor.get_text().splitlines()
            if line.strip() and not line.startswith("http") and not line.endswith('">')
        ]

        title = ""
        company = ""
        location = ""
        salary = None

        for line in lines:
            if any(term in line.lower() for term in ("view job", "unsubscribe", "notification", "see jobs", "settings", "linkedin")):
                continue
            if not title and len(line) > 3:
                title = line
                continue
            if title and not company and len(line) > 1:
                company = line
                continue
            if title and company and not location and len(line) > 2:
                if re.search(r"(remote|hybrid|on-site|[a-z]+,\s*[a-z]+)", line, re.I):
                    location = line
                elif not location:
                    location = line
                continue
            if re.search(r"([€$£]\s*\d+|\d+k\s*-\s*\d+k|per\s+year|/yr)", line, re.I):
                salary = line

        return title, company, location, salary

    def _extract_company_and_location_near(
        self, html: str, target_url: str, title: str
    ) -> tuple[str, str, str | None]:
        """Extract company name, location, and salary near the job title anchor."""
        idx = html.find(target_url)
        if idx == -1:
            return "", "", None

        # Find the closing </a> tag of the target link
        close_a_idx = html.find("</a>", idx)
        start_search = close_a_idx + 4 if close_a_idx != -1 else idx + len(target_url)
        end = min(len(html), start_search + 1000)
        sub = html[start_search:end]

        extractor = HTMLTextExtractor()
        extractor.feed(sub)
        lines = [
            l.strip()
            for l in extractor.get_text().splitlines()
            if l.strip() and not l.startswith("http") and not l.endswith('">')
        ]

        company = ""
        location = ""
        salary = None

        for line in lines:
            if line == title or line.lower() in ("view job", "apply now", "save", "see all", "linkedin"):
                continue
            if not company:
                company = line
                continue
            if company and not location:
                location = line
                continue
            if re.search(r"([€$£]\s*\d+|\d+k\s*-\s*\d+k|per\s+year|/yr)", line, re.I):
                salary = line
                break

        return company, location, salary

    def _parse_regex_links(self, text: str, message: EmailMessage) -> list[JobAlertItem]:
        """Fallback scanner finding LinkedIn job URLs in plain text or raw markup."""
        jobs: list[JobAlertItem] = []
        seen_job_ids: set[str] = set()

        url_matches = re.finditer(
            r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)[^\s\"'>]*",
            text,
            re.IGNORECASE,
        )

        for match in url_matches:
            raw_url = match.group(0)
            job_id = match.group(1)
            if job_id in seen_job_ids:
                continue

            seen_job_ids.add(job_id)
            canonical = f"https://www.linkedin.com/jobs/view/{job_id}"
            jobs.append(
                JobAlertItem(
                    title=f"LinkedIn Opportunity ({job_id})",
                    company="Company",
                    location="",
                    raw_url=raw_url,
                    canonical_url=canonical,
                    source="LinkedIn",
                    job_id=job_id,
                    email_uid=message.uid,
                    email_sender=message.sender,
                    metadata={"email_subject": message.subject},
                )
            )

        return jobs
