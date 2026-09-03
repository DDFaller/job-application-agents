#!/usr/bin/env python3
"""Generate a self-contained HTML application report from JSON records."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from job_application_agents.job_search.reports import build_report, render_html_report


def discover_records(data_root: Path) -> list[dict]:
    records = []
    for current in sorted(data_root.glob("applications/**/current.json")):
        try:
            value = json.loads(current.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            value.setdefault("local_bundle_path", str(current.parent))
            records.append(value)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, help="job-search data root")
    parser.add_argument("--input", type=Path, help="JSON array or object containing records")
    parser.add_argument("--output", type=Path, default=Path("reports/application-dashboard.html"))
    args = parser.parse_args()
    data_root = (args.data_root or Path(os.getenv("JAA_DATA_ROOT", "job-search"))).expanduser().resolve()
    if args.input:
        if not args.input.is_file():
            parser.error(f"input file not found: {args.input}")
        try:
            value = json.loads(args.input.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            parser.error(f"input is not valid JSON: {exc}")
        records = value if isinstance(value, list) else value.get("records", [])
    else:
        records = discover_records(data_root)
    output = render_html_report(build_report(records), args.output.expanduser().resolve())
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
