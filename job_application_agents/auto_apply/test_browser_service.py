from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from .browser import application_browser
from .interaction import SiteExclusions
from .models import CandidateProfile, SubmissionReceipt
from .portal import PortalGuard
from .service import AutoApplyService, SUBMISSION_CONFIRMATION


class BrowserTests(unittest.TestCase):
    def test_missing_optional_backend_has_actionable_error(self):
        from importlib.metadata import PackageNotFoundError
        with patch('job_application_agents.auto_apply.browser.version', side_effect=PackageNotFoundError):
            with self.assertRaisesRegex(RuntimeError, 'browser-invisible'):
                with application_browser(backend='invisible'):
                    self.fail('missing dependency must not launch or fall back')

    def test_persistent_invisible_handle_is_already_a_context(self):
        package = MagicMock()
        context = package.InvisiblePlaywright.return_value.__enter__.return_value
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('sys.modules', {'invisible_playwright': package}), patch(
                'job_application_agents.auto_apply.browser.version',
                side_effect=lambda name: '0.39.0' if name == 'invisible-playwright' else '50.47.0',
            ):
                with application_browser(backend='invisible', profile_dir=Path(directory)) as actual:
                    self.assertIs(actual, context)
                context.new_context.assert_not_called()
                package.InvisiblePlaywright.return_value.__exit__.assert_called_once()

    def test_excluded_requests_are_aborted_before_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = PortalGuard(Path(directory))
            guard.exclusions.record('https://blocked.test', reason='user_exclusion', evidence='User instruction')
            context, route = MagicMock(), MagicMock()
            guard.install(context)
            handler = context.route.call_args.args[1]
            route.request.url = 'https://blocked.test/upload'
            handler(route)
            route.abort.assert_called_once()
            route.continue_.assert_not_called()

    def test_visible_challenge_persists_exclusion_but_footer_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = PortalGuard(Path(directory))
            page = MagicMock(url='https://jobs.test/role')
            page.locator.return_value.all.return_value = []
            page.locator.return_value.inner_text.return_value = 'Protected by reCAPTCHA. Privacy Policy.'
            guard.check(page)
            self.assertEqual(guard.exclusions.entries(), [])
            page.locator.return_value.inner_text.return_value = 'Performing security verification'
            with self.assertRaises(PermissionError):
                guard.check(page)
            self.assertIsNotNone(SiteExclusions(Path(directory)).match(page.url))


class LocalApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / 'application'
        self.app.mkdir()
        (self.app / 'job.json').write_text(json.dumps({'canonical_url': 'https://jobs.test/role'}))
        (self.app / 'resume.pdf').write_bytes(b'%PDF-1.4 test')
        self.candidate = CandidateProfile(first_name='Test', last_name='Person', email='test@example.test',
                                          phone='+33123456789', location='Paris')
        self.driver = MagicMock(name='driver')
        self.driver.name = 'test'
        self.registry = MagicMock()
        self.registry.resolve.return_value = self.driver
        self.page = MagicMock()
        self.page.url = 'https://jobs.test/role'
        self.body = 'Application form'
        self.page.locator.return_value.all.return_value = []
        self.page.locator.return_value.inner_text.side_effect = lambda **kw: self.body

        @contextmanager
        def browser(**kwargs):
            context = MagicMock()
            context.new_page.return_value = self.page
            yield context
        self.launch = patch('job_application_agents.auto_apply.service.application_browser', side_effect=browser).start()
        self.addCleanup(patch.stopall)

    def apply(self, **kwargs):
        return AutoApplyService(self.registry).apply(self.app, self.candidate, data_root=self.root, **kwargs)

    def test_preview_never_calls_the_multistep_solver_or_submit(self):
        with patch('job_application_agents.auto_apply.agent_solver.AgentFormSolver.solve_form') as solver:
            receipt = self.apply(mode='supervised')
        solver.assert_not_called()
        self.driver.submit.assert_not_called()
        self.assertFalse(receipt.submitted)
        self.assertFalse((self.app / 'receipt.json').exists())

    def test_missing_resume_does_not_upload_an_arbitrary_pdf(self):
        (self.app / 'resume.pdf').rename(self.app / 'motivation-letter.pdf')
        with self.assertRaises(FileNotFoundError):
            self.apply()
        self.launch.assert_not_called()

    def test_excluded_site_stops_before_browser_launch(self):
        SiteExclusions(self.root).record('https://jobs.test', reason='captcha', evidence='Prior challenge')
        with self.assertRaises(PermissionError):
            self.apply()
        self.launch.assert_not_called()

    def submit(self):
        with patch.dict('os.environ', {'JAA_ENABLE_SUBMISSION': SUBMISSION_CONFIRMATION}), patch('builtins.input', return_value=''):
            return self.apply(mode='supervised', allow_submission=True, browser_backend='invisible')

    def test_click_success_without_acknowledgement_stays_unconfirmed_and_blocks_retry(self):
        self.driver.submit.return_value = SubmissionReceipt(True, 'test', self.page.url, 'now')
        result = self.submit()
        self.assertFalse(result.success)
        self.assertFalse(result.submitted)
        self.assertEqual(json.loads((self.app / 'current.json').read_text())['status'], 'SUBMISSION_UNCONFIRMED')
        receipt = json.loads((self.app / 'receipt.json').read_text())
        self.assertTrue(receipt['submission_attempted'])
        self.assertEqual(len(receipt['documents']['resume']['sha256']), 64)
        with self.assertRaises(PermissionError):
            self.apply()

    def test_only_a_new_acknowledgement_confirms_submission(self):
        self.driver.submit.side_effect = lambda **kw: setattr(self, 'body', 'Your application has been submitted')
        result = self.submit()
        self.assertTrue(result.submitted)
        self.assertEqual(json.loads((self.app / 'current.json').read_text())['status'], 'APPLIED')

    def test_ashby_past_tense_acknowledgement_confirms_submission(self):
        self.driver.submit.side_effect = lambda **kw: setattr(
            self, 'body', "Success\nYour application was successfully submitted. We'll contact you if there are next steps."
        )
        result = self.submit()
        self.assertTrue(result.submitted)
        self.assertEqual(json.loads((self.app / 'current.json').read_text())['status'], 'APPLIED')

    def test_existing_ashby_acknowledgement_does_not_confirm_another_submission(self):
        self.body = 'Your application was successfully submitted.'
        result = self.submit()
        self.assertFalse(result.submitted)
        self.assertEqual(json.loads((self.app / 'current.json').read_text())['status'], 'SUBMISSION_UNCONFIRMED')

    def test_lity_french_receipt_confirms_submission(self):
        self.driver.submit.side_effect = lambda **kw: setattr(
            self, 'body', 'Candidature envoyée\nMerci, nous avons bien reçu votre candidature.'
        )
        self.assertTrue(self.submit().submitted)

    def test_personio_simple_past_receipt_requires_a_new_acknowledgement(self):
        message = 'THANK YOU! We received your application and will get in touch with you as soon as possible!'
        self.driver.submit.side_effect = lambda **kw: setattr(self, 'body', message)
        self.assertTrue(self.submit().submitted)
        (self.app / 'receipt.json').unlink()
        (self.app / 'current.json').unlink()
        self.driver.submit.side_effect = None
        self.assertFalse(self.submit().submitted)

    def test_negative_personio_receipt_does_not_confirm_submission(self):
        self.driver.submit.side_effect = lambda **kw: setattr(
            self, 'body', 'We have not received your application. Please check the form.'
        )
        self.assertFalse(self.submit().submitted)

    def test_negative_past_tense_message_does_not_confirm_submission(self):
        self.driver.submit.side_effect = lambda **kw: setattr(self, 'body', 'Your application was not submitted.')
        self.assertFalse(self.submit().submitted)

    def test_driver_failure_keeps_preclick_receipt_for_recovery(self):
        self.driver.submit.side_effect = RuntimeError('Browser disconnected')
        result = self.submit()
        self.assertFalse(result.submitted)
        self.assertTrue(json.loads((self.app / 'receipt.json').read_text())['submission_attempted'])


if __name__ == '__main__':
    unittest.main()
