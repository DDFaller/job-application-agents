"""Unit tests for email alert parsers."""

from __future__ import annotations

import unittest

from integrations.email.parsers.base import HTMLTextExtractor, strip_tracking_params
from integrations.email.parsers.generic import GenericJobAlertParser
from integrations.email.parsers.glassdoor import GlassdoorJobAlertParser
from integrations.email.parsers.greenhouse_lever import DirectATSPostingParser
from integrations.email.parsers.indeed import IndeedJobAlertParser
from integrations.email.parsers.linkedin import LinkedInJobAlertParser
from integrations.email.parsers.registry import EmailParserRegistry, parser_registry
from integrations.models import EmailMessage


SAMPLE_LINKEDIN_ALERT_HTML = """
<!DOCTYPE html>
<html>
<body>
  <table>
    <tr>
      <td>
        <h2>Top job picks for you</h2>
        <div>
          <a href="https://www.linkedin.com/comm/jobs/view/4159823451/?trackingId=abc123xyz&refId=def456&midToken=token789&trk=eml-job_alerts-view_job">
            Senior AI Platform Engineer
          </a>
          <div>Mistral AI</div>
          <div>Paris, Île-de-France, France (Hybrid)</div>
          <div>€85,000/yr - €110,000/yr</div>
        </div>
        <hr>
        <div>
          <a href="https://www.linkedin.com/comm/jobs/view/4160912384/?trackingId=uvw987&trk=eml-job_alerts">
            Staff Python / Backend Engineer
          </a>
          <div>Datadog</div>
          <div>Paris, France (On-site)</div>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>
"""

SAMPLE_INDEED_ALERT_HTML = """
<html>
<body>
  <div>
    <h3>Recommended Jobs</h3>
    <div>
      <a href="https://www.indeed.com/rc/clk?jk=8f9a1b2c3d4e5f6a&from=ja&tk=1g2h3i4j">
        Cloud Infrastructure Engineer
      </a>
      <span>Pigment</span>
      <span>Paris (75)</span>
    </div>
  </div>
</body>
</html>
"""

SAMPLE_GREENHOUSE_EMAIL_HTML = """
<html>
<body>
  <p>Hi Alex,</p>
  <p>We saw your profile and thought you would be a great fit for our opening:</p>
  <p><a href="https://boards.greenhouse.io/gorgias/jobs/5678901?gh_jid=5678901&utm_source=email">AI Platform Engineer at Gorgias</a></p>
  <p>Location: Paris / Remote</p>
</body>
</html>
"""


class TestEmailParsers(unittest.TestCase):

    def test_strip_tracking_params(self) -> None:
        raw_url = "https://www.linkedin.com/jobs/view/4159823451/?trackingId=abc123xyz&refId=def456&midToken=token789&trk=eml-job_alerts"
        cleaned = strip_tracking_params(raw_url)
        self.assertEqual(cleaned, "https://www.linkedin.com/jobs/view/4159823451/")

    def test_html_text_extractor(self) -> None:
        extractor = HTMLTextExtractor()
        extractor.feed("<div><h1>Title</h1><p>Paragraph with <a href='https://example.com'>link text</a>.</p></div>")
        text = extractor.get_text()
        self.assertIn("Title", text)
        self.assertIn("Paragraph with link text.", text)
        self.assertEqual(len(extractor.links), 1)
        self.assertEqual(extractor.links[0], ("https://example.com", "link text"))

    def test_linkedin_parser(self) -> None:
        parser = LinkedInJobAlertParser()
        msg = EmailMessage(
            uid="101",
            message_id="msg-101",
            sender="jobalerts-noreply@linkedin.com",
            recipient="candidate@example.com",
            subject="10 new jobs for 'AI Platform Engineer'",
            date_str="Wed, 26 Aug 2026 08:00:00 +0000",
            body_html=SAMPLE_LINKEDIN_ALERT_HTML,
        )

        self.assertTrue(parser.can_parse(msg))
        jobs = parser.parse_jobs(msg)

        self.assertEqual(len(jobs), 2)
        job1 = jobs[0]
        self.assertEqual(job1.title, "Senior AI Platform Engineer")
        self.assertEqual(job1.company, "Mistral AI")
        self.assertIn("Paris", job1.location)
        self.assertEqual(job1.job_id, "4159823451")
        self.assertEqual(job1.canonical_url, "https://www.linkedin.com/jobs/view/4159823451")
        self.assertEqual(job1.source, "LinkedIn")
        self.assertEqual(job1.email_sender, "jobalerts-noreply@linkedin.com")

        job2 = jobs[1]
        self.assertEqual(job2.title, "Staff Python / Backend Engineer")
        self.assertEqual(job2.company, "Datadog")
        self.assertEqual(job2.job_id, "4160912384")
        self.assertEqual(job2.canonical_url, "https://www.linkedin.com/jobs/view/4160912384")

    def test_indeed_parser(self) -> None:
        parser = IndeedJobAlertParser()
        msg = EmailMessage(
            uid="102",
            message_id="msg-102",
            sender="alert@indeed.com",
            recipient="candidate@example.com",
            subject="Indeed Job Alert: Cloud Engineer",
            date_str="2026-08-26",
            body_html=SAMPLE_INDEED_ALERT_HTML,
        )

        self.assertTrue(parser.can_parse(msg))
        jobs = parser.parse_jobs(msg)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Cloud Infrastructure Engineer")
        self.assertEqual(jobs[0].job_id, "8f9a1b2c3d4e5f6a")
        self.assertEqual(jobs[0].canonical_url, "https://www.indeed.com/viewjob?jk=8f9a1b2c3d4e5f6a")

    def test_greenhouse_direct_ats_parser(self) -> None:
        parser = DirectATSPostingParser()
        msg = EmailMessage(
            uid="103",
            message_id="msg-103",
            sender="recruiter@gorgias.com",
            recipient="candidate@example.com",
            subject="Exciting AI Platform role at Gorgias",
            date_str="2026-08-26",
            body_html=SAMPLE_GREENHOUSE_EMAIL_HTML,
        )

        self.assertTrue(parser.can_parse(msg))
        jobs = parser.parse_jobs(msg)
        self.assertEqual(len(jobs), 1)
        self.assertIn("AI Platform Engineer", jobs[0].title)
        self.assertEqual(jobs[0].company, "Gorgias")
        self.assertEqual(jobs[0].source, "Greenhouse")

    def test_parser_registry_routing(self) -> None:
        registry = EmailParserRegistry()

        linkedin_msg = EmailMessage(
            uid="1",
            message_id="1",
            sender="jobalerts-noreply@linkedin.com",
            recipient="a@b.com",
            subject="Job alert",
            date_str="",
            body_html=SAMPLE_LINKEDIN_ALERT_HTML,
        )
        parser = registry.get_parser(linkedin_msg)
        self.assertIsInstance(parser, LinkedInJobAlertParser)

        generic_msg = EmailMessage(
            uid="2",
            message_id="2",
            sender="newsletter@techjobs.org",
            recipient="a@b.com",
            subject="Weekly tech roles",
            date_str="",
            body_html="<p>Check out this <a href='https://jobs.example.org/careers/dev-123'>Software Engineer role</a></p>",
        )
        parser_gen = registry.get_parser(generic_msg)
        self.assertIsInstance(parser_gen, GenericJobAlertParser)
        jobs = parser_gen.parse_jobs(generic_msg)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Software Engineer role")


if __name__ == "__main__":
    unittest.main()
