#!/usr/bin/env python3
"""Inspect a batch's fit reports and record explicit preparation/skip decisions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_application_agents.config import resolve_data_root
from job_application_agents.orchestration import BatchController, LocalProcessExecutor, WorkerProfile
from job_application_agents.orchestration.controller import StageDefinition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--job')
    parser.add_argument('--decision', choices=['prepare', 'skip'])
    parser.add_argument('--selection-sha256', help='Exact selection revision shown in the report being approved')
    args = parser.parse_args()
    try:
        state = json.loads(args.state.read_text())
        if args.decision:
            if not args.job or not args.selection_sha256:
                parser.error('--decision requires --job and --selection-sha256')
            stages = tuple(StageDefinition(**s) for s in state['stages'])
            controller = BatchController(ROOT, resolve_data_root(args.data_root, repository_root=ROOT),
                executor=LocalProcessExecutor(ROOT), stages=stages,
                profiles={s.profile: WorkerProfile('codex', 'unused-review-only') for s in stages})
            state = controller.review_fit(args.state, args.job, args.decision,
                selection_sha256=args.selection_sha256)
        rows = {}
        for key, job in state['jobs'].items():
            if args.job and key != args.job:
                continue
            if 'fit_report' not in job:
                continue
            ref = next(a for a in job['artifacts'] if a['name'] == 'profile-selection.json')
            rows[key] = {'status': job['status'], 'opening_url': job['opening_url'],
                'selection_sha256': ref['sha256'], 'fit': job['fit_report'],
                'decision': job.get('fit_decision')}
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
