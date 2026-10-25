from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from job_application_agents.positioning import assess_selection, digest, validate_selection
from job_application_agents.orchestration.test_positioning import fixture


class JuniorTailoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        _, _, self.selection = fixture(self.root)
        self.selection['seniority_requirement']['level'] = 'junior'
        for ranking in self.selection['rankings']:
            ranking['mandatory_checks'][0].update(status='unknown', fact_ids=[])
            ranking['priorities'][0].update(level='unsupported', fact_ids=[])
        self.authority = self.root / 'instruction.txt'
        self.authority.write_text('Tailor junior CVs even when my experience is weak.')
        self.override = dict(scope='prepare_only', user_instruction=dict(path=str(self.authority), sha256=digest(self.authority)),
                             user_instruction_quote=self.authority.read_text())

    def test_explicit_preparation_override_preserves_unknown_checks(self):
        self.assertEqual(assess_selection(self.selection, self.root), ('skip', None))
        self.selection['junior_tailoring_override'] = self.override
        self.selection.update(decision='use', selected_profile_id='data')
        validate_selection(self.selection, self.root)
        self.assertEqual(self.selection['rankings'][0]['mandatory_checks'][0]['status'], 'unknown')

    def test_override_does_not_cover_senior_jobs_or_fabricated_evidence(self):
        self.selection['junior_tailoring_override'] = self.override
        self.selection['seniority_requirement']['level'] = 'senior'
        with self.assertRaisesRegex(ValueError, 'non-junior'):
            assess_selection(self.selection, self.root)
        self.selection['seniority_requirement']['level'] = 'junior'
        self.selection['rankings'][0]['priorities'][1]['fact_ids'] = ['INVENTED-001']
        with self.assertRaisesRegex(ValueError, 'unknown priority'):
            assess_selection(self.selection, self.root)

    def test_stale_authority_and_missing_quote_fail(self):
        self.selection['junior_tailoring_override'] = deepcopy(self.override)
        self.selection['junior_tailoring_override']['user_instruction_quote'] = 'Invented consent'
        with self.assertRaisesRegex(ValueError, 'absent'):
            assess_selection(self.selection, self.root)
        self.selection['junior_tailoring_override'] = self.override
        self.authority.write_text('Changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            assess_selection(self.selection, self.root)


if __name__ == '__main__':
    unittest.main()
