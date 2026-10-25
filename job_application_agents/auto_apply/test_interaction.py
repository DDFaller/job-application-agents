from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call

from .interaction import PacedFormInput, SiteExclusions


class InteractionTests(unittest.TestCase):
    def test_text_and_non_text_fields_observe_the_same_pacing(self):
        page, name, email, choice = Mock(), Mock(), Mock(), Mock()
        inputs = PacedFormInput(page)
        inputs.text("name", name, "Daniel")
        inputs.text("name", name, "Daniel Faller")
        inputs.text("email", email, "person@example.com")
        inputs.check("consent", choice)
        self.assertEqual(page.wait_for_timeout.call_args_list, [call(1000), call(1000)])
        name.press_sequentially.assert_called_with("Daniel Faller", delay=50)
        email.press_sequentially.assert_called_once_with("person@example.com", delay=50)
        choice.set_checked.assert_called_once_with(True)

    def test_exclusion_persists_without_query_tokens_and_matches_host_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = SiteExclusions(root)
            ledger.record("https://ats.example/jobs?token=private", reason="captcha",
                          evidence="Visible human-verification challenge", include_subdomains=True)
            restored = SiteExclusions(root)
            with self.assertRaises(PermissionError):
                restored.require_allowed("https://jobs.ats.example/new")
            restored.require_allowed("https://notats.example/new")
            restored.require_allowed("https://ats.example.evil.test/new")
            self.assertNotIn("private", ledger.path.read_text())
            ledger.record("https://ats.example/new", reason="captcha", evidence="Same block")
            self.assertEqual(len(ledger.entries()), 1)

    def test_exact_host_does_not_exclude_unrelated_tenants(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = SiteExclusions(Path(directory))
            ledger.record("https://tenant.ats.example/job", reason="automation_block",
                          evidence="Portal rejected automated access")
            ledger.require_allowed("https://other.ats.example/job")

    def test_corrupt_ledger_and_unsupported_reason_stop_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = SiteExclusions(Path(directory))
            with self.assertRaises(ValueError):
                ledger.record("https://example.com", reason="http_500", evidence="Server error")
            ledger.path.parent.mkdir(parents=True)
            ledger.path.write_text('{"schema_version": 9, "sites": []}')
            with self.assertRaises(ValueError):
                ledger.require_allowed("https://example.com")


if __name__ == "__main__":
    unittest.main()
