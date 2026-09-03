#!/usr/bin/env python3
"""Resolve the canonical source and approved role-profile contracts read-only."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2]
MAINTAIN_SCRIPTS = SKILLS_ROOT / "maintain-master-curriculum" / "scripts"


def run_resolver(command: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout, result.stderr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    data_root = args.data_root.expanduser().resolve()
    source_dir = data_root / "sources"
    state_root = data_root / "master-curriculum"
    source_resolver = MAINTAIN_SCRIPTS / "resolve_current.py"
    profile_resolver = MAINTAIN_SCRIPTS / "resolve_profiles.py"

    source_rc, source_out, source_err = run_resolver([
        sys.executable, str(source_resolver), "--source-dir", str(source_dir),
    ])
    if source_rc != 0:
        print(source_err or source_out, file=sys.stderr, end="")
        return 2 if source_rc == 2 else source_rc

    profile_rc, profile_out, profile_err = run_resolver([
        sys.executable, str(profile_resolver),
        "--state-root", str(state_root),
        "--expected-source-manifest", str(source_dir / "current.json"),
    ])
    if profile_rc != 0:
        print(profile_err or profile_out, file=sys.stderr, end="")
        return 2 if profile_rc == 2 else profile_rc

    try:
        source = json.loads(source_out)
        profiles = json.loads(profile_out)
    except json.JSONDecodeError as exc:
        print(f"approved profile resolution failed: invalid resolver output: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({
        "data_root": str(data_root),
        "source": source,
        "profiles": profiles,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
