"""Behavioral checks for evidence scoring and explicit preparation choices."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_application_agents.positioning import assess_fit, assess_selection, digest, validate_selection
from job_application_agents.job_search.fit import automatic_eligibility
from job_application_agents.orchestration.contracts import ArtifactReference, StageResult, StageTask, WorkerProfile
from job_application_agents.orchestration.controller import BatchController, JobSpec, StageDefinition
from job_application_agents.orchestration.test_controller import FakeExecutor, FakeLedger
from job_application_agents.orchestration.test_positioning import fixture


class FitReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.library, self.lp, self.selection = fixture(self.root)
        self.selection.update(schema_version=2, decision='review')

    def test_unknown_is_review_with_score_interval_not_rejection(self):
        self.selection['rankings'][0]['mandatory_checks'][1].update(status='unknown', fact_ids=[])
        self.assertEqual(assess_selection(self.selection, self.root), ('review', 'data'))
        report = assess_fit(self.selection, self.root, threshold=60)
        assessment = report['assessment']
        self.assertEqual((assessment['score'], assessment['score_upper_bound'], assessment['evidence_coverage']), (70, 90, 80))
        self.assertFalse(report['automatic_application']['eligible'])
        self.assertIn('location', assessment['automatic_blockers'])

    def test_unmet_is_distinct_from_unknown(self):
        self.selection['rankings'][0]['mandatory_checks'][1]['status'] = 'unmet'
        assessment = assess_fit(self.selection, self.root)['assessment']
        self.assertEqual((assessment['score'], assessment['score_upper_bound'], assessment['evidence_coverage']), (70, 70, 100))
        self.assertEqual(assess_selection(self.selection, self.root), ('review', 'data'))

    def test_low_fit_and_seniority_gap_remain_visible(self):
        self.selection['requested_profile'] = 'platform'
        self.selection['selected_profile_id'] = 'platform'
        self.selection['seniority_requirement']['level'] = 'senior'
        report = assess_fit(self.selection, self.root, threshold=0)
        self.assertEqual(report['assessment']['score'], 70)
        self.assertIn('seniority', report['assessment']['automatic_blockers'])
        self.assertFalse(report['automatic_application']['eligible'])

    def test_numeric_fit_is_derived_and_worker_cannot_select_winner(self):
        self.selection['rankings'][1]['score'] = 100
        self.assertEqual(assess_fit(self.selection, self.root)['assessment']['score'], 90)
        self.selection['selected_profile_id'] = 'platform'
        with self.assertRaisesRegex(ValueError, 'ranking'):
            validate_selection(self.selection, self.root)

    def test_duplicate_and_omitted_checks_are_invalid(self):
        for duplicate in (True, False):
            s = deepcopy(self.selection)
            checks = s['rankings'][0]['mandatory_checks']
            checks.append(deepcopy(checks[0])) if duplicate else checks.pop()
            with self.assertRaisesRegex(ValueError, 'duplicate|unchecked'):
                assess_fit(s, self.root)

    def test_threshold_is_optional_and_never_submission_authority(self):
        assessment = assess_fit(self.selection, self.root)['assessment']
        self.assertFalse(automatic_eligibility(assessment)['eligible'])
        self.assertTrue(automatic_eligibility(assessment, 90)['eligible'])
        self.assertFalse(automatic_eligibility(assessment, 91)['eligible'])
        self.assertFalse(automatic_eligibility(assessment, 0)['submission_authorized'])
        for invalid in (-1, 101, True, 80.0, '80'):
            with self.assertRaises(ValueError): automatic_eligibility(assessment, invalid)

    def test_changed_evidence_invalidates_score(self):
        (self.root / 'sources/engineer/experience.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            assess_fit(self.selection, self.root)

    def controller_result(self, *, prepare_selected=False, legacy=False):
        executor, ledger = FakeExecutor(), FakeLedger()
        controller = BatchController(Path(__file__).resolve().parents[2], self.root,
            executor=executor, ledger=ledger, profiles={'worker': WorkerProfile('codex', 'test')},
            stages=(StageDefinition('profile-selection', 'select', 'worker'), StageDefinition('bundle-writing', 'write', 'worker')))
        with patch('job_application_agents.orchestration.controller.BatchPreflight.run', return_value=()), patch(
            'job_application_agents.positioning.load_active_library', return_value=(self.lp, self.library)):
            path = controller.create([JobSpec('one', 'https://example.test/job')], prepare_selected=prepare_selected)
        state = json.loads(path.read_text())
        state['jobs']['one']['artifacts'].append(dict(name='job.json', **self.selection['job']))
        path.write_text(json.dumps(state))
        controller.tick(path)
        task = StageTask.read(Path(executor.handles[0].task_path))
        self.assertTrue(any('schema_version 2' in c for c in task.constraints))
        s = deepcopy(self.selection)
        if legacy: s.update(schema_version=1, decision='use')
        output = Path(task.output_dir) / 'profile-selection.json'
        output.parent.mkdir(parents=True)
        output.write_text(json.dumps(s))
        StageResult(task.run_id, task.job_key, task.stage, 1, 'succeeded', True,
            (ArtifactReference('profile-selection.json', str(output), digest(output)),)).write(Path(task.result_path))
        return controller, executor, ledger, path, output

    def test_next_run_waits_for_review_and_resumes_exact_selection(self):
        c, ex, ledger, path, output = self.controller_result()
        state = c.tick(path)
        self.assertEqual(state['status'], 'awaiting_fit_review')
        job = state['jobs']['one']
        self.assertEqual(job['match_score'], 90)
        self.assertEqual(len(ex.handles), 1)
        self.assertFalse(any(event[0] == 'finalize' for event in ledger.events))
        self.assertTrue(any(a['name'] == 'fit-report.json' for a in job['artifacts']))
        with self.assertRaisesRegex(ValueError, 'revision'):
            c.review_fit(path, 'one', 'prepare', selection_sha256='wrong')
        c.review_fit(path, 'one', 'prepare', selection_sha256=digest(output))
        c.tick(path)
        self.assertEqual(len(ex.handles), 2)
        task = StageTask.read(Path(ex.handles[1].task_path))
        self.assertEqual(task.stage, 'bundle-writing')
        self.assertIn('No application submission, employer contact, or APPLIED status', task.constraints)

    def test_user_skip_is_terminal(self):
        c, ex, ledger, path, output = self.controller_result()
        c.tick(path)
        c.review_fit(path, 'one', 'skip', selection_sha256=digest(output))
        state = c.tick(path)
        self.assertEqual(state['jobs']['one']['status'], 'skipped')
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(len(ex.handles), 1)

    def test_explicit_selection_prepares_despite_unknown_and_exposes_score(self):
        self.selection['rankings'][0]['mandatory_checks'][0].update(status='unknown', fact_ids=[])
        c, ex, _, path, _ = self.controller_result(prepare_selected=True)
        state = c.tick(path)
        self.assertEqual(len(ex.handles), 2)
        self.assertEqual(state['jobs']['one']['fit_report']['assessment']['score'], 70)
        self.assertFalse(state['jobs']['one']['fit_decision']['submission_authorized'])

    def test_new_run_rejects_old_worker_protocol_instead_of_silently_skipping(self):
        c, ex, _, path, _ = self.controller_result(legacy=True)
        state = c.tick(path)
        self.assertEqual(state['jobs']['one']['status'], 'needs_input')
        self.assertIn('schema 2', state['jobs']['one']['blocker']['message'])
        self.assertEqual(len(ex.handles), 1)


if __name__ == '__main__': unittest.main()
