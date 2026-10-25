"""Synthetic evidence fixtures: no candidate or production data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_application_agents.positioning import (
    assess_selection, digest, load_active_library, validate_bundle_binding,
    validate_library, validate_selection, validate_positioned_claims,
)
from job_application_agents.orchestration.contracts import ArtifactReference, StageResult, StageTask, WorkerProfile
from job_application_agents.orchestration.controller import BatchController, JobSpec, StageDefinition
from job_application_agents.orchestration.test_controller import FakeExecutor, FakeLedger


def fixture(root):
    sources = root / 'sources' / 'engineer'
    sources.mkdir(parents=True)
    source = sources / 'experience.md'
    source.write_text('- [E-001] Built pipelines in Python.\n- [E-002] Operated containers.\n- [E-003] Wrote SQL tests.\n- [E-004] Authorized and willing to relocate to target.\n')
    profile = dict(id='data', label='Data', source_profile='engineer', headline='Data Engineer',
                   narrative='Reliable data workflows.', target_roles=['Data Engineer'], seniority_ceiling='mid',
                   anchor_fact_ids=['E-001'], supporting_fact_ids=['E-002', 'E-003'],
                   skill_groups=[dict(label='Data', fact_ids=['E-001', 'E-003'])], project_fact_ids=[],
                   prohibited_claims=['No AI research'], risk_notes=['No fine-tuning'])
    library = dict(schema_version=1, sources=[dict(name='experience', path=str(source), sha256=digest(source))],
                   profiles=[profile, dict(profile, id='platform', headline='Platform Engineer')], editorial_rules=['One page'])
    lp = root / 'positioning-library.json'; lp.write_text(json.dumps(library))
    jp = root / 'job.json'; jp.write_text(json.dumps(dict(role='Software Engineer', requirements=['Python'],
        location='Target country', responsibilities=['Build pipelines', 'Test data', 'Operate services'])))
    priorities = [dict(text=t, job_keys=[f'responsibilities.{i}']) for i,t in enumerate(['Pipelines','Testing','Operations'])]
    def ranking(pid, levels):
        return dict(profile_id=pid, rationale='Duties support the selected specialization.', priorities=[
            dict(level=level, fact_ids=['E-001'] if level!='unsupported' else [], job_keys=[f'responsibilities.{i}'], rationale='Supported by source work.')
            for i,level in enumerate(levels)], mandatory_checks=[
                dict(job_keys=['requirements.0'],status='met',fact_ids=['E-001'],rationale='Python used professionally.'),
                dict(job_keys=['location'],status='met',fact_ids=['E-004'],rationale='Explicit eligibility and relocation.')])
    selection = dict(schema_version=1, job=dict(path=str(jp),sha256=digest(jp)),
        library=dict(path=str(lp),sha256=digest(lp)), requested_profile=None, priorities=priorities,
        seniority_requirement=dict(level='unspecified',job_keys=['role'],rationale='No explicit seniority requirement.'),
        rankings=[ranking('data',['direct','direct','transferable']),ranking('platform',['direct','transferable','unsupported'])],
        decision='use',selected_profile_id='data',reason='Data duties have direct evidence.')
    return library, lp, selection


class PositioningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.library, self.lp, self.selection = fixture(self.root)

    def test_duties_qualify_profile_despite_generic_title(self):
        validate_selection(self.selection,self.root)
        self.assertEqual(assess_selection(self.selection,self.root),('use','data'))

    def test_weak_research_profile_skips_without_generic_fallback(self):
        s=deepcopy(self.selection)
        for r in s['rankings']:
            r['priorities'][1]['level']='transferable'
        s.update(decision='skip',selected_profile_id=None)
        validate_selection(s,self.root)

    def test_explicit_weak_profile_cannot_bypass_gate(self):
        self.selection.update(requested_profile='platform',decision='skip',selected_profile_id=None)
        validate_selection(self.selection,self.root)
        self.selection.update(decision='use',selected_profile_id='platform')
        with self.assertRaisesRegex(ValueError,'qualification'):
            validate_selection(self.selection,self.root)

    def test_unmet_and_unknown_constraints_skip(self):
        for status in ['unmet','unknown']:
            s=deepcopy(self.selection);s['rankings'][0]['mandatory_checks'][1]['status']=status
            s.update(decision='skip',selected_profile_id=None)
            validate_selection(s,self.root)

    def test_omitted_requirement_is_error_not_skip(self):
        self.selection['rankings'][0]['mandatory_checks'].pop()
        with self.assertRaisesRegex(ValueError,'unchecked mandatory'):
            validate_selection(self.selection,self.root)

    def test_unknown_evidence_and_priority_mismatch_rejected(self):
        for field,value in [('fact_ids',['FAKE-001']),('job_keys',['responsibilities.1'])]:
            s=deepcopy(self.selection);s['rankings'][0]['priorities'][0][field]=value
            with self.assertRaises(ValueError):validate_selection(s,self.root)

    def test_stale_source_and_catalog_are_errors(self):
        source=self.root/'sources/engineer/experience.md';source.write_text('changed')
        with self.assertRaisesRegex(ValueError,'stale'):validate_library(self.library,self.root)
        self.lp.write_text('{}')
        with self.assertRaisesRegex(ValueError,'stale'):validate_selection(self.selection,self.root)

    def test_seniority_ceiling_rejects_senior_opening(self):
        self.selection['seniority_requirement']['level'] = 'senior'
        self.selection.update(decision='skip', selected_profile_id=None)
        validate_selection(self.selection, self.root)

    def test_learning_allowance_requires_actual_job_quote(self):
        check = self.selection['rankings'][0]['mandatory_checks'][0]
        check['status'] = 'learning_allowed'
        with self.assertRaisesRegex(ValueError, 'allowance'):
            validate_selection(self.selection, self.root)
        check['allowance_quote'] = 'Invented learning allowance'
        with self.assertRaisesRegex(ValueError, 'absent'):
            validate_selection(self.selection, self.root)

    def test_malformed_library_rejected(self):
        for value in ([], {'schema_version': 1, 'sources': [None]}):
            with self.assertRaises(ValueError):
                validate_library(value, self.root)

    def test_no_approval_means_no_active_library(self):
        with self.assertRaisesRegex(ValueError,'missing'):load_active_library(self.root)

    def test_visible_claims_need_profile_anchor_and_supports(self):
        bundle = dict(resume_sections=[dict(evidence_ids=['E-001', 'E-002', 'E-003'])])
        validate_positioned_claims(bundle, self.selection, self.root)
        for ids in (['E-001'], ['E-002', 'E-003'], ['E-001', 'E-002', 'E-003', 'FAKE-001']):
            bundle['resume_sections'][0]['evidence_ids'] = ids
            with self.assertRaises(ValueError):
                validate_positioned_claims(bundle, self.selection, self.root)

    def test_bundle_cannot_switch_profile_or_headline(self):
        sp=self.root/'selection.json';sp.write_text(json.dumps(self.selection))
        bundle=dict(inputs=dict(profile_selection_json=str(sp),profile_selection_sha256=digest(sp),
            job_json=self.selection['job']['path'],job_sha256=self.selection['job']['sha256'],
            role_profile='engineer',role_profile_source_dir=str(self.root/'sources/engineer')),
            tailoring_strategy=dict(selected_profile_id='data'),candidate=dict(headline='Data Engineer'))
        validate_bundle_binding(bundle,self.selection,self.root)
        bundle['candidate']['headline']='Software Engineer'
        with self.assertRaisesRegex(ValueError,'headline'):validate_bundle_binding(bundle,self.selection,self.root)

    def controller(self, stages):
        ex=FakeExecutor();ledger=FakeLedger()
        return BatchController(Path(__file__).resolve().parents[2],self.root,executor=ex,ledger=ledger,
            profiles={'worker':WorkerProfile('codex','test')},stages=stages),ex,ledger

    def test_skip_is_terminal_and_never_launches_writer(self):
        stages=(StageDefinition('profile-selection','select','worker'),StageDefinition('bundle-writing','write','worker'))
        c,ex,ledger=self.controller(stages)
        with patch('job_application_agents.orchestration.controller.BatchPreflight.run',return_value=()),patch(
            'job_application_agents.positioning.load_active_library',return_value=(self.lp,self.library)):
            p=c.create([JobSpec('one','https://example.test/job')], review_fit=False)
        state=json.loads(p.read_text());state['jobs']['one']['artifacts'].append(dict(name='job.json',**self.selection['job']));p.write_text(json.dumps(state))
        c.tick(p);task=StageTask.read(Path(ex.handles[0].task_path))
        s=deepcopy(self.selection)
        for r in s['rankings']:r['mandatory_checks'][0]['status']='unmet'
        s.update(decision='skip',selected_profile_id=None)
        out=Path(task.output_dir)/'profile-selection.json';out.parent.mkdir(parents=True);out.write_text(json.dumps(s))
        StageResult(task.run_id,task.job_key,task.stage,1,'succeeded',True,
            (ArtifactReference('profile-selection.json',str(out),digest(out)),)).write(Path(task.result_path))
        state=c.tick(p)
        self.assertEqual(state['jobs']['one']['status'],'skipped')
        self.assertEqual(state['status'],'complete')
        self.assertEqual(len(ex.handles),1)
        self.assertIn(('finalize','skipped'),ledger.events)

    def test_selector_cannot_replace_approved_library(self):
        stages = (StageDefinition('profile-selection', 'select', 'worker'),)
        c, ex, _ = self.controller(stages)
        with patch('job_application_agents.orchestration.controller.BatchPreflight.run', return_value=()), patch(
            'job_application_agents.positioning.load_active_library', return_value=(self.lp, self.library)
        ):
            state_path = c.create([JobSpec('one', 'https://example.test/job')], review_fit=False)
        state = json.loads(state_path.read_text())
        state['jobs']['one']['artifacts'].append(dict(name='job.json', **self.selection['job']))
        state_path.write_text(json.dumps(state))
        c.tick(state_path)
        task = StageTask.read(Path(ex.handles[0].task_path))
        output = Path(task.output_dir) / 'replacement.json'
        output.parent.mkdir(parents=True)
        changed = deepcopy(self.library)
        changed['editorial_rules'].append('Changed by worker')
        output.write_text(json.dumps(changed))
        StageResult(task.run_id, task.job_key, task.stage, 1, 'succeeded', True,
            (ArtifactReference('positioning-library.json', str(output), digest(output)),)
        ).write(Path(task.result_path))
        result = c.tick(state_path)
        self.assertEqual(result['jobs']['one']['status'], 'needs_input')
        refs = {a['name']: a for a in result['jobs']['one']['artifacts']}
        self.assertEqual(refs['positioning-library.json']['path'], str(self.lp))

    def test_identical_provenance_copy_keeps_canonical_binding(self):
        stages = (StageDefinition('profile-selection', 'select', 'worker'),)
        c, ex, _ = self.controller(stages)
        with patch('job_application_agents.orchestration.controller.BatchPreflight.run', return_value=()), patch(
            'job_application_agents.positioning.load_active_library', return_value=(self.lp, self.library)
        ):
            path = c.create([JobSpec('one', 'https://example.test/job')], review_fit=False)
        state = json.loads(path.read_text())
        state['jobs']['one']['artifacts'].append(dict(name='job.json', **self.selection['job']))
        path.write_text(json.dumps(state))
        c.tick(path)
        task = StageTask.read(Path(ex.handles[0].task_path))
        output = Path(task.output_dir)
        output.mkdir(parents=True)
        copy = output / 'library-copy.json'
        copy.write_bytes(self.lp.read_bytes())
        selection = output / 'profile-selection.json'
        selection.write_text(json.dumps(self.selection))
        StageResult(task.run_id, task.job_key, task.stage, 1, 'succeeded', True, (
            ArtifactReference('positioning-library.json', str(copy), digest(copy)),
            ArtifactReference('profile-selection.json', str(selection), digest(selection)),
        )).write(Path(task.result_path))
        result = c.tick(path)
        self.assertEqual(result['jobs']['one']['status'], 'prepared')
        refs = {a['name']: a for a in result['jobs']['one']['artifacts']}
        self.assertEqual(refs['positioning-library.json']['path'], str(self.lp))

    def test_stored_stage_sequence_wins_over_new_defaults(self):
        old=(StageDefinition('extract','extract','worker'),StageDefinition('write','write','worker'))
        c,ex,_=self.controller(old)
        with patch('job_application_agents.orchestration.controller.BatchPreflight.run',return_value=()):
            p=c.create([JobSpec('one','https://example.test/job')], review_fit=False)
        new=(old[0],StageDefinition('profile-selection','select','worker'),old[1])
        resumed,_,_=self.controller(new);resumed.tick(p)
        self.assertEqual(resumed.stages,old)

    def test_legacy_stage_one_remains_writer(self):
        old=(StageDefinition('extract','extract','worker'),StageDefinition('write','write','worker'))
        c,_,_=self.controller(old)
        with patch('job_application_agents.orchestration.controller.BatchPreflight.run',return_value=()):
            p=c.create([JobSpec('one','https://example.test/job')], review_fit=False)
        s=json.loads(p.read_text());s['schema_version']=1;s.pop('stages');s['jobs']['one']['stage_index']=1;p.write_text(json.dumps(s))
        new=(old[0],StageDefinition('profile-selection','select','worker'),old[1])
        resumed,ex,_=self.controller(new);resumed.tick(p)
        self.assertEqual(StageTask.read(Path(ex.handles[0].task_path)).stage,'write')


if __name__=='__main__':unittest.main()
