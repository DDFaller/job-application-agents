#!/usr/bin/env python3
"""Rank staged normalized job postings using the repository scorer."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from job_application_agents.job_search.ranking import load_json_jobs, rank_jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="job.json file or directory")
    parser.add_argument("--data-root", type=Path, help="job-search data root")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--candidate", type=Path, help="optional candidate facts JSON")
    parser.add_argument("--tracked", type=Path, help="optional JSON list of excluded job keys")
    parser.add_argument("--write", action="store_true", help="write rankings/latest.json under data root")
    args = parser.parse_args()

    data_root = (args.data_root or Path(os.getenv("JAA_DATA_ROOT", "job-search"))).expanduser().resolve()
    input_root = (args.input or data_root / "staging_job").expanduser().resolve()
    candidate = json.loads(args.candidate.read_text(encoding="utf-8")) if args.candidate else None
    tracked_value = json.loads(args.tracked.read_text(encoding="utf-8")) if args.tracked else []
    tracked = set(tracked_value if isinstance(tracked_value, list) else tracked_value.get("keys", []))
    result = rank_jobs(load_json_jobs(input_root), candidate=candidate, tracked_keys=tracked, top=args.top, min_score=args.min_score)
    payload = {"triage_only": True, "input": str(input_root), "results": result}
    if args.write:
        target = data_root / "rankings" / "latest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        payload["output"] = str(target)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
