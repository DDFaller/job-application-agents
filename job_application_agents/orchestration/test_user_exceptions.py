"""Explicit authority changes eligibility, never facts or employer requirements."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from job_application_agents.orchestration.test_positioning import fixture
from job_application_agents.positioning import assess_selection, digest, validate_selection


class UserExceptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        _, _, self.selection = fixture(self.root)
        self.job_path = Path(self.selection['job']['path'])
        self.job = json.loads(self.job_path.read_text())
        self.job['requirements'].append('Experience working in Agile/Scrum teams.')
        self.save_job()
        for ranking in self.selection['rankings']:
            ranking['mandatory_checks'].append(dict(job_keys=['requirements.1'],
                status='unknown', fact_ids=[], rationale='No evidence of Agile team practice.'))
        self.authority = self.root / 'direct-user-instruction.txt'
        self.authority.write_text('Apply to this job despite the unevidenced Agile-team experience; I accept that soft gap.')
        self.exception = dict(job_keys=['requirements.1'],
            user_instruction=dict(path=str(self.authority), sha256=digest(self.authority)),
            user_instruction_quote=self.authority.read_text(), rationale='User accepts this working-practice gap.')
        self.selection['user_authorized_exceptions'] = [self.exception]

    def save_job(self):
        self.job_path.write_text(json.dumps(self.job))
        self.selection['job']['sha256'] = digest(self.job_path)

    def test_unknown_and_unmet_qualify_without_mutation(self):
        for status in ('unknown', 'unmet'):
            self.selection['rankings'][0]['mandatory_checks'][-1]['status'] = status
            before = deepcopy(self.selection)
            job_bytes = self.job_path.read_bytes()
            validate_selection(self.selection, self.root)
            self.assertEqual(self.selection, before)
            self.assertEqual(self.job_path.read_bytes(), job_bytes)

    def test_volkswagen_agile_working_practice_sentence(self):
        self.job['requirements'][1] = 'Knowledge of agile development practices and experience working in agile teams.'
        self.save_job()
        validate_selection(self.selection, self.root)

    def test_default_still_skips(self):
        del self.selection['user_authorized_exceptions']
        self.assertEqual(assess_selection(self.selection, self.root), ('skip', None))

    def test_missing_or_fabricated_authority_rejected(self):
        for field, value in [('user_instruction', None), ('user_instruction_quote', ''),
                             ('user_instruction_quote', 'Invented permission'), ('rationale', '')]:
            with self.subTest(field=field, value=value):
                selection = deepcopy(self.selection)
                selection['user_authorized_exceptions'][0][field] = value
                with self.assertRaises(ValueError):
                    assess_selection(selection, self.root)

    def test_stale_and_out_of_root_authority_rejected(self):
        self.authority.write_text('Changed instruction')
        with self.assertRaisesRegex(ValueError, 'stale'):
            assess_selection(self.selection, self.root)
        self.exception['user_instruction']['sha256'] = digest(self.authority)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            # Narrow the permitted root without reading any external files.
            from job_application_agents.positioning import read_reference
            read_reference(self.exception['user_instruction'], self.root / 'private')
        link = self.root / 'private'
        link.mkdir()
        (link / 'authority').symlink_to(self.authority)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            read_reference(dict(path=str(link / 'authority'), sha256=digest(self.authority)), link)

    def test_hard_and_combined_requirement_fields_rejected(self):
        for text in ('German C1', 'Work authorization', 'Senior engineer',
                     'Agile teams and German C1', 'Agile/Scrum and Python',
                     '5 years experience in Agile teams', 'Scrum certification',
                     'Agile teams in Berlin', {'text': 'Agile teams'}):
            with self.subTest(text=text):
                self.job['requirements'][1] = text
                self.save_job()
                with self.assertRaisesRegex(ValueError, 'Agile/Scrum-only'):
                    assess_selection(self.selection, self.root)

    def test_bad_scope_and_duplicates_rejected(self):
        for keys in (['location'], ['responsibilities.0'], ['requirements'],
                     ['requirements.01'], ['requirements.99'], ['requirements.1', 'requirements.1']):
            with self.subTest(keys=keys):
                self.exception['job_keys'] = keys
                with self.assertRaises(ValueError):
                    assess_selection(self.selection, self.root)
        self.exception['job_keys'] = ['requirements.1']
        self.selection['user_authorized_exceptions'].append(deepcopy(self.exception))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            assess_selection(self.selection, self.root)

    def test_mixed_check_remains_ineligible(self):
        self.selection['rankings'][0]['mandatory_checks'][-1]['job_keys'].append('location')
        self.assertEqual(assess_selection(self.selection, self.root), ('skip', None))

    def test_other_gates_remain_required(self):
        for change in ('coverage', 'seniority', 'priority', 'requested'):
            selection = deepcopy(self.selection)
            if change == 'coverage':
                selection['rankings'][0]['mandatory_checks'].pop()
                with self.assertRaisesRegex(ValueError, 'unchecked'):
                    assess_selection(selection, self.root)
                continue
            if change == 'seniority':
                selection['seniority_requirement']['level'] = 'senior'
            elif change == 'priority':
                selection['rankings'][0]['priorities'][0]['level'] = 'transferable'
            else:
                selection['requested_profile'] = 'platform'
            self.assertEqual(assess_selection(selection, self.root), ('skip', None))

    def test_exception_does_not_count_as_met(self):
        data, platform = self.selection['rankings']
        platform['priorities'] = deepcopy(data['priorities'])
        platform['mandatory_checks'][-1].update(status='met', fact_ids=['E-001'])
        self.assertEqual(assess_selection(self.selection, self.root), ('use', 'platform'))

    def test_changed_job_requires_new_binding(self):
        self.job_path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'stale'):
            assess_selection(self.selection, self.root)


if __name__ == '__main__':
    unittest.main()
