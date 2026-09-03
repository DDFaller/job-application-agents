"""Specialized parser for Indeed job alert emails."""

from __future__ import annotations

from html import unescape
import re
from urllib.parse import parse_qs, urlparse

from ...base import BaseEmailParser
from ...models import EmailMessage, JobAlertItem
from .base import HTMLTextExtractor, clean_html_snippet, strip_tracking_params


class IndeedJobAlertParser(BaseEmailParser):
    """Parser targeting Indeed job alert emails (alert@indeed.com, etc.)."""

    INDEED_SENDERS = [
        "alert@indeed.com",
        "do-not-reply@indeed.com",
        "jobalerts@indeed.com",
    ]

    @property
    def supported_senders(self) -> list[str]:
        return list(self.INDEED_SENDERS)

    def can_parse(self, message: EmailMessage) -> bool:
        sender = message.sender.lower()
        if any(s in sender for s in self.INDEED_SENDERS):
            return True
        if "indeed.com" in sender and ("job" in message.subject.lower() or "alert" in message.subject.lower()):
            return True
        if "indeed.com/rc/clk" in message.body_html or "indeed.com/viewjob" in message.body_html:
            return True
        return False

    def parse_jobs(self, message: EmailMessage) -> list[JobAlertItem]:
        jobs: list[JobAlertItem] = []
        html = message.body_html or message.body_plain
        if not html:
            return jobs

        seen_keys: set[str] = set()

        # Find indeed job links (viewjob?jk=... or /rc/clk?jk=...)
        matches = re.finditer(
            r'<a\s+[^>]*href=["\']([^"\']*(?:indeed\.com/(?:viewjob|rc/clk|company/[^/]+/jobs)[^"\']*))["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE | re.DOTALL,
        )

        for match in matches:
            raw_url = unescape(match.group(1).strip())
            inner_html = match.group(2).strip()

            job_key, canonical_url = self._extract_indeed_job_key_and_canonical(raw_url)
            if not job_key or job_key in seen_keys:
                continue

            title = clean_html_snippet(inner_html)
            if not title or len(title) < 3 or title.lower() in ("view job", "apply", "save job"):
                title = f"Indeed Job ({job_key})"

            seen_keys.add(job_key)
            jobs.append(
                JobAlertItem(
                    title=title,
                    company="Company",
                    location="",
                    raw_url=raw_url,
                    canonical_url=canonical_url,
                    source="Indeed",
                    job_id=job_key,
                    email_uid=message.uid,
                    email_sender=message.sender,
                    metadata={"email_subject": message.subject},
                )
            )

        return jobs

    def _extract_indeed_job_key_and_canonical(self, url: str) -> tuple[str | None, str]:
        try:
            parsed = urlparse(url)
            q = parse_qs(parsed.query)
            if "jk" in q and q["jk"]:
                job_key = q["jk"][0]
                return job_key, f"https://www.indeed.com/viewjob?jk={job_key}"
        except Exception:
            pass

        m = re.search(r"jk=([a-f0-9]+)", url, re.I)
        if m:
            job_key = m.group(1)
            return job_key, f"https://www.indeed.com/viewjob?jk={job_key}"

        return None, strip_tracking_params(url)
