"""Evidence-bound positioning libraries and job-profile qualification.

Semantic assessment is performed by an isolated worker. This module validates
its evidence references and calculates fit in code. New selections recommend a
profile for human review; legacy selections keep their original semantics.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

LIBRARY_POINTER = Path('master-curriculum/profiles/positioning/current.json')
FACT_PATTERN = re.compile(r'\[([A-Z][A-Z0-9_-]*-\d+)\]')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_reference(ref: dict[str, Any], data_root: Path) -> Path:
    """Require an existing, hash-bound file within the private data root."""
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
        raise ValueError('invalid artifact reference')
    path = Path(ref['path'])
    if not path.is_absolute() or not path.resolve().is_relative_to(data_root.resolve()):
        raise ValueError('artifact reference escapes data root')
    if not path.is_file() or digest(path) != ref.get('sha256'):
        raise ValueError(f'missing or stale artifact: {path.name}')
    return path.resolve()


def _strings(value: Any, label: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value) or any(
        not isinstance(x, str) or not x.strip() for x in value
    ):
        raise ValueError(f'{label} must be a list of nonempty strings')
    if len(value) != len(set(value)):
        raise ValueError(f'{label} contains duplicates')
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} is required')
    return value


def validate_library(library: dict[str, Any], data_root: Path) -> set[str]:
    """Validate a staged or approved library and return its available fact IDs."""
    _object(library, 'library')
    if library.get('schema_version') != 1:
        raise ValueError('unsupported positioning library schema')
    refs = library.get('sources')
    if not isinstance(refs, list) or not refs:
        raise ValueError('library requires source references')
    names: set[str] = set()
    facts: dict[str, str] = {}
    for ref in refs:
        _object(ref, 'source reference')
        name = _text(ref.get('name'), 'source name')
        if name in names:
            raise ValueError('duplicate library source name')
        names.add(name)
        path = read_reference(ref, data_root)
        for line in path.read_text(encoding='utf-8').splitlines():
            for fact in FACT_PATTERN.findall(line):
                if fact in facts and facts[fact] != line.strip():
                    raise ValueError(f'contradictory source fact: {fact}')
                facts[fact] = line.strip()
    if not facts:
        raise ValueError('library sources contain no stable fact IDs')
    profiles = library.get('profiles')
    if not isinstance(profiles, list) or not profiles:
        raise ValueError('library requires profiles')
    seen: set[str] = set()
    for profile in profiles:
        _object(profile, 'profile')
        pid = _text(profile.get('id'), 'profile id')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', pid) or pid in seen:
            raise ValueError('profile IDs must be unique slugs')
        seen.add(pid)
        for key in ('label', 'headline', 'narrative', 'source_profile'):
            _text(profile.get(key), f'{pid}.{key}')
        source_profile = profile['source_profile']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', source_profile):
            raise ValueError('source_profile must be a safe profile folder name')
        source_dir = data_root / 'sources' / source_profile
        if not source_dir.is_dir() or not source_dir.resolve().is_relative_to(data_root.resolve()):
            raise ValueError(f'missing source profile: {source_profile}')
        if profile.get('seniority_ceiling') not in {'entry', 'junior', 'mid', 'senior', 'lead'}:
            raise ValueError('invalid seniority ceiling')
        for key in ('target_roles', 'prohibited_claims', 'risk_notes'):
            _strings(profile.get(key), f'{pid}.{key}')
        anchors = _strings(profile.get('anchor_fact_ids'), 'anchor_fact_ids')
        supports = _strings(profile.get('supporting_fact_ids'), 'supporting_fact_ids')
        if len(supports) < 2 or set(anchors) & set(supports):
            raise ValueError('profile needs an anchor and two distinct supporting facts')
        ids = anchors + supports + _strings(profile.get('project_fact_ids'), 'project_fact_ids', nonempty=False)
        groups = profile.get('skill_groups')
        if not isinstance(groups, list) or not groups:
            raise ValueError('profile requires skill groups')
        for group in groups:
            _object(group, 'skill group')
            _text(group.get('label'), 'skill group label')
            ids += _strings(group.get('fact_ids'), 'skill fact IDs')
        if set(ids) - facts.keys():
            raise ValueError(f'{pid} references unknown evidence')
    _strings(library.get('editorial_rules'), 'editorial_rules')
    return set(facts)


def load_active_library(data_root: Path) -> tuple[Path, dict[str, Any]]:
    """Load only an approved immutable release, never an unreviewed fallback."""
    pointer = data_root / LIBRARY_POINTER
    if not pointer.is_file():
        raise ValueError('approved positioning library missing; stage and review profiles first')
    value = json.loads(pointer.read_text(encoding='utf-8'))
    path = read_reference(value['library'], data_root)
    review_path = read_reference(value['review'], data_root)
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if value.get('approved') is not True or review.get('verdict') != 'accept' or review.get('library_sha256') != digest(path):
        raise ValueError('positioning library lacks an exact accepted review and approval')
    library = json.loads(path.read_text(encoding='utf-8'))
    validate_library(library, data_root)
    return path, library


def _job_keys(keys: Any, job: dict[str, Any]) -> list[str]:
    keys = _strings(keys, 'job_keys')
    for key in keys:
        value: Any = job
        try:
            for part in key.split('.'):
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f'unknown job evidence: {key}') from exc
        if value is None or value == '' or value == []:
            raise ValueError(f'empty job evidence: {key}')
    return keys


# Full-field grammar, deliberately fail-closed: no arbitrary suffixes, durations,
# qualifications or additional skills may hitchhike on an Agile exception.
_AGILE_PRACTICE = re.compile(
    r"(?:knowledge of agile development practices and experience working in agile teams[.]?|"
    r"(?:experience (?:in |with |working in |working with )?|"
    r"(?:prior |previous )experience (?:in |with |working in |working with )|"
    r"familiarity with |knowledge of |understanding of |ability to work in )?"
    r"(?:an? )?(?:agile(?:/scrum| and scrum)?|scrum)"
    r"(?: teams?| environments?| methodologies| methods| practices| working practices)?"
    r"(?: experience)?[.]?)", re.IGNORECASE,
)


def _user_exceptions(selection: dict[str, Any], job: dict[str, Any], data_root: Path) -> set[str]:
    """Validate direct-user authority for narrowly scoped working-practice gaps."""
    entries = selection.get('user_authorized_exceptions', [])
    if not isinstance(entries, list):
        raise ValueError('user_authorized_exceptions must be an array')
    covered: set[str] = set()
    for entry in entries:
        _object(entry, 'user exception')
        keys = _job_keys(entry.get('job_keys'), job)
        for key in keys:
            if not re.fullmatch(r'requirements\.(?:0|[1-9][0-9]*)', key):
                raise ValueError('user exception must cite exact requirement keys')
            value = job['requirements'][int(key.split('.')[1])]
            if not isinstance(value, str) or not _AGILE_PRACTICE.fullmatch(value.strip()):
                raise ValueError('user exception requires an Agile/Scrum-only working-practice field')
            if key in covered:
                raise ValueError('duplicate user exception requirement')
            covered.add(key)
        _text(entry.get('rationale'), 'user exception rationale')
        quote = _text(entry.get('user_instruction_quote'), 'quoted user instruction')
        source = read_reference(entry.get('user_instruction'), data_root)
        if quote not in source.read_text(encoding='utf-8'):
            raise ValueError('quoted user instruction is absent from authority file')
    return covered


def _assess_selection(selection: dict[str, Any], data_root: Path) -> tuple[tuple[str, str | None], list[dict[str, Any]]]:
    """Validate evidence before deriving either legacy qualification or fit."""
    from job_application_agents.job_search.fit import score_profile
    _object(selection, 'selection')
    if selection.get('schema_version') not in {1, 2}:
        raise ValueError('unsupported profile-selection schema')
    library_path = read_reference(selection.get('library'), data_root)
    job_path = read_reference(selection.get('job'), data_root)
    library = json.loads(library_path.read_text(encoding='utf-8'))
    job = json.loads(job_path.read_text(encoding='utf-8'))
    exceptions = _user_exceptions(selection, job, data_root)
    facts = validate_library(library, data_root)
    profiles = {p['id']: p for p in library['profiles']}
    priorities = selection.get('priorities')
    if not isinstance(priorities, list) or len(priorities) != 3:
        raise ValueError('selection requires exactly three job priorities')
    for priority in priorities:
        _object(priority, 'priority')
        _text(priority.get('text'), 'priority text')
        _job_keys(priority.get('job_keys'), job)
    seniority = _object(selection.get('seniority_requirement'), 'seniority_requirement')
    seniority_levels = ['entry', 'junior', 'mid', 'senior', 'lead']
    required_level = seniority.get('level')
    if required_level not in [*seniority_levels, 'unspecified']:
        raise ValueError('invalid required seniority')
    _job_keys(seniority.get('job_keys'), job)
    _text(seniority.get('rationale'), 'seniority rationale')
    # Explicit user authorization to PREPARE a junior CV despite gaps does not
    # convert unknown requirements into evidence or authorize false claims.
    junior_override = selection.get('junior_tailoring_override')
    prepare_despite_gaps = False
    if junior_override is not None:
        _object(junior_override, 'junior tailoring override')
        if junior_override.get('scope') != 'prepare_only':
            raise ValueError('junior tailoring override must be prepare_only')
        source = read_reference(junior_override.get('user_instruction'), data_root)
        quote = _text(junior_override.get('user_instruction_quote'), 'quoted junior tailoring instruction')
        if quote not in source.read_text(encoding='utf-8'):
            raise ValueError('junior tailoring instruction quote is absent from authority file')
        if required_level not in {'entry', 'junior'}:
            raise ValueError('junior tailoring override cannot cover non-junior scope')
        prepare_despite_gaps = True
    requested = selection.get('requested_profile')
    if requested is not None and requested not in profiles:
        raise ValueError('requested profile is not in the approved library')
    rankings = selection.get('rankings')
    if not isinstance(rankings, list) or len(rankings) != len(profiles):
        raise ValueError('selection must assess every profile')
    seen: set[str] = set()
    eligible: list[tuple[int, int, str]] = []
    assessments: list[dict[str, Any]] = []
    required_keys = {f'requirements.{i}' for i in range(len(job.get('requirements') or []))}
    if job.get('location'):
        required_keys.add('location')
    for ranking in rankings:
        _object(ranking, 'ranking')
        pid = ranking.get('profile_id')
        if pid not in profiles or pid in seen:
            raise ValueError('duplicate or unknown ranked profile')
        seen.add(pid)
        _text(ranking.get('rationale'), 'ranking rationale')
        matches = ranking.get('priorities')
        if not isinstance(matches, list) or len(matches) != 3:
            raise ValueError('each profile must assess all three priorities')
        profile = profiles[pid]
        allowed = set(profile['anchor_fact_ids'] + profile['supporting_fact_ids'] + profile['project_fact_ids'])
        for group in profile['skill_groups']:
            allowed.update(group['fact_ids'])
        levels = []
        for i, match in enumerate(matches):
            _object(match, 'priority assessment')
            level = match.get('level')
            if level not in {'direct', 'transferable', 'unsupported'}:
                raise ValueError('invalid priority evidence level')
            levels.append(level)
            ids = _strings(match.get('fact_ids'), 'priority fact IDs', nonempty=level != 'unsupported')
            if set(ids) - facts:
                raise ValueError('unknown priority evidence')
            if set(ids) - allowed:
                raise ValueError('priority evidence is outside this profile')
            keys = _job_keys(match.get('job_keys'), job)
            if not set(keys) & set(priorities[i]['job_keys']):
                raise ValueError('priority assessment cites a different priority')
            _text(match.get('rationale'), 'priority rationale')
        checks = ranking.get('mandatory_checks')
        if not isinstance(checks, list) or not checks:
            raise ValueError('mandatory requirement assessments are required')
        covered: set[str] = set()
        statuses = []
        checks_eligible = []
        for check in checks:
            _object(check, 'mandatory check')
            keys = _job_keys(check.get('job_keys'), job)
            if selection['schema_version'] == 2 and covered.intersection(keys):
                raise ValueError('duplicate mandatory requirement assessment')
            covered.update(keys)
            status = check.get('status')
            if status not in {'met', 'learning_allowed', 'unmet', 'unknown'}:
                raise ValueError('invalid mandatory requirement status')
            if status == 'learning_allowed':
                quote = _text(check.get('allowance_quote'), 'explicit allowance quote')
                if quote not in json.dumps(job, ensure_ascii=False):
                    raise ValueError('learning allowance quote is absent from the job')
            statuses.append(status)
            checks_eligible.append(status in {'met', 'learning_allowed'} or set(keys) <= exceptions)
            ids = _strings(check.get('fact_ids'), 'mandatory fact IDs', nonempty=status in {'met', 'learning_allowed'})
            if set(ids) - facts:
                raise ValueError('unknown mandatory evidence')
            _text(check.get('rationale'), 'mandatory rationale')
        if required_keys - covered:
            raise ValueError(f'{pid} has unchecked mandatory requirements: {sorted(required_keys - covered)}')
        seniority_ok = required_level == 'unspecified' or seniority_levels.index(required_level) <= seniority_levels.index(profile['seniority_ceiling'])
        assessments.append(score_profile(ranking, priorities, required_keys, seniority_ok=seniority_ok))
        qualified = levels.count('direct') >= 2 and 'unsupported' not in levels and all(checks_eligible)
        if seniority_ok and (qualified or prepare_despite_gaps):
            if requested is None or pid == requested:
                eligible.append((-levels.count('direct'), -statuses.count('met'), pid))
    _text(selection.get('reason'), 'selection reason')
    assessments.sort(key=lambda row: (-row['score'], -row['evidence_coverage'], row['profile_id']))
    if selection['schema_version'] == 2:
        selected = requested or assessments[0]['profile_id']
        return ('review', selected), assessments
    return (('use', sorted(eligible)[0][2]) if eligible else ('skip', None)), assessments


def assess_selection(selection: dict[str, Any], data_root: Path) -> tuple[str, str | None]:
    return _assess_selection(selection, data_root)[0]


def assess_fit(selection: dict[str, Any], data_root: Path, *, threshold: int | None = None) -> dict[str, Any]:
    """Return a recomputed report bound to the exact job, library and source facts."""
    from job_application_agents.job_search.fit import automatic_eligibility, RUBRIC_VERSION
    (decision, selected), profiles = _assess_selection(selection, data_root)
    if (selection.get('decision'), selection.get('selected_profile_id')) != (decision, selected):
        raise ValueError('selection decision does not match evidence qualification/ranking')
    recommended = selected or selection.get('requested_profile') or profiles[0]['profile_id']
    assessment = next(row for row in profiles if row['profile_id'] == recommended)
    return {
        'schema_version': 1, 'rubric_version': RUBRIC_VERSION,
        'job': selection['job'], 'library': selection['library'],
        'selected_profile_id': recommended, 'assessment': assessment,
        'profiles': profiles, 'automatic_application': automatic_eligibility(assessment, threshold),
        'decision': 'review', 'submission_authorized': False,
    }


def validate_selection(selection: dict[str, Any], data_root: Path) -> None:
    decision, selected = assess_selection(selection, data_root)
    if (selection.get('decision'), selection.get('selected_profile_id')) != (decision, selected):
        raise ValueError('selection decision does not match evidence qualification/ranking')


def validate_bundle_binding(bundle: dict[str, Any], selection: dict[str, Any], data_root: Path) -> None:
    """Prevent downstream stages from silently switching jobs, profiles or sources."""
    validate_selection(selection, data_root)
    if selection['decision'] != 'use' and not (selection['schema_version'] == 2 and selection['decision'] == 'review'):
        raise ValueError('a skipped selection cannot produce a bundle')
    inputs = bundle.get('inputs', {})
    selection_path = read_reference({'path': inputs.get('profile_selection_json'), 'sha256': inputs.get('profile_selection_sha256')}, data_root)
    if json.loads(selection_path.read_text()) != selection:
        raise ValueError('bundle selection differs from the controller selection')
    if inputs.get('job_sha256') != selection['job']['sha256'] or Path(inputs.get('job_json', '')).resolve() != Path(selection['job']['path']).resolve():
        raise ValueError('bundle uses a different job than its selection')
    library = json.loads(Path(selection['library']['path']).read_text(encoding='utf-8'))
    profile = next(p for p in library['profiles'] if p['id'] == selection['selected_profile_id'])
    if bundle.get('tailoring_strategy', {}).get('selected_profile_id') != profile['id']:
        raise ValueError('bundle switched its selected positioning profile')
    if inputs.get('role_profile') != profile['source_profile']:
        raise ValueError('bundle switched its canonical source profile')
    expected = (data_root / 'sources' / profile['source_profile']).resolve()
    if Path(inputs.get('role_profile_source_dir', '')).resolve() != expected:
        raise ValueError('bundle source directory does not match selected profile')
    if bundle.get('candidate', {}).get('headline') != profile['headline']:
        raise ValueError('bundle must use its approved profile headline')


def validate_positioned_claims(bundle: dict[str, Any], selection: dict[str, Any], data_root: Path) -> None:
    """Require real direct-source citations and visible anchor/support evidence."""
    library = json.loads(read_reference(selection['library'], data_root).read_text())
    known = validate_library(library, data_root)
    profile = next(p for p in library['profiles'] if p['id'] == selection['selected_profile_id'])

    def citations(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith('evidence_ids'):
                    found.update(_strings(child, key, nonempty=False))
                else:
                    found.update(citations(child))
        elif isinstance(value, list):
            for child in value:
                found.update(citations(child))
        return found

    if citations(bundle) - known:
        raise ValueError('positioned bundle cites unknown direct-source facts')
    visible = citations(bundle.get('candidate', {})) | citations(bundle.get('resume_sections', []))
    if not visible & set(profile['anchor_fact_ids']):
        raise ValueError('positioned CV needs visible anchor evidence')
    if len(visible & set(profile['supporting_fact_ids'])) < 2:
        raise ValueError('positioned CV needs two visible supporting facts')
