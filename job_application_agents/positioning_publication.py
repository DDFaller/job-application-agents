"""Publish an exact reviewed positioning release after explicit approval."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from job_application_agents.positioning import (
    LIBRARY_POINTER, digest, read_reference, validate_library,
)
from job_application_agents.orchestration.contracts import atomic_json_write


def validate_review(library_path: Path, review_path: Path, data_root: Path) -> dict[str, Any]:
    """Require accepted exact bytes and all three preview formats for every profile."""
    for path in (library_path, review_path):
        if not path.resolve().is_relative_to(data_root.resolve()):
            raise ValueError('review inputs must be inside the private data root')
    library = json.loads(library_path.read_text(encoding='utf-8'))
    validate_library(library, data_root)
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if not isinstance(review, dict) or review.get('schema_version') != 1:
        raise ValueError('unsupported positioning review schema')
    if review.get('verdict') != 'accept' or review.get('library_sha256') != digest(library_path):
        raise ValueError('publication requires an accepted review of the exact library')
    findings = review.get('findings')
    if not isinstance(findings, list) or any(not isinstance(x, str) for x in findings):
        raise ValueError('review findings must be strings')
    previews = review.get('previews')
    if not isinstance(previews, list):
        raise ValueError('review requires baseline previews')
    expected = {p['id'] + suffix for p in library['profiles'] for suffix in ('.md', '.tex', '.pdf')}
    seen = set()
    for ref in previews:
        path = read_reference(ref, data_root)
        name = ref.get('name')
        if name not in expected or name in seen or name != path.name:
            raise ValueError('review has duplicate, unexpected or misnamed previews')
        seen.add(name)
    if seen != expected:
        raise ValueError('review must bind Markdown, LaTeX and PDF for every profile')
    return review


def publish_library(library_path: Path, review_path: Path, data_root: Path, *, approval: str) -> Path:
    """Create an immutable version and atomically update the runtime pointer."""
    if approval != 'APPROVED':
        raise ValueError('explicit approval of the reviewed library is required')
    data_root = data_root.resolve()
    base = data_root / LIBRARY_POINTER.parent
    versions = base / 'versions'
    versions.mkdir(parents=True, exist_ok=True)
    with (base / '.publication.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        review = validate_review(library_path, review_path, data_root)
        numbers = [int(p.name[1:]) for p in versions.iterdir() if re.fullmatch(r'p\d+', p.name)]
        destination = versions / f'p{max(numbers, default=0) + 1:03d}'
        staging = Path(tempfile.mkdtemp(prefix='.publish-', dir=versions))
        try:
            shutil.copyfile(library_path, staging / 'positioning-library.json')
            shutil.copyfile(review_path, staging / 'review.json')
            for ref in review['previews']:
                shutil.copyfile(read_reference(ref, data_root), staging / ref['name'])
                if digest(staging / ref['name']) != ref['sha256']:
                    raise ValueError('preview changed during publication')
            # Recheck both copied bytes and live source hashes before promotion.
            copied_review = validate_review(staging / 'positioning-library.json', staging / 'review.json', data_root)
            if copied_review != review:
                raise ValueError('review changed during publication')
            staging.rename(destination)
            atomic_json_write(data_root / LIBRARY_POINTER, {
                'schema_version': 1, 'approved': True,
                'approved_at': datetime.now(timezone.utc).isoformat(),
                'library': {'path': str(destination / 'positioning-library.json'),
                            'sha256': digest(destination / 'positioning-library.json')},
                'review': {'path': str(destination / 'review.json'),
                           'sha256': digest(destination / 'review.json')},
            })
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return destination
