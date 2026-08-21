#!/usr/bin/env python3
"""Atomically install one approved, validated XeLaTeX résumé template."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from validate_template import TAILOR_SKILL, validate_template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--target-root", type=Path, default=TAILOR_SKILL / "assets" / "latex" / "templates")
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    if args.approval != "APPROVED":
        print("installation refused: --approval must be exactly APPROVED", file=sys.stderr)
        return 2
    source = args.template.expanduser().resolve()
    target_root = args.target_root.expanduser().resolve()
    if target_root in {Path("/").resolve(), Path.home().resolve()}:
        print("installation refused: target root is too broad", file=sys.stderr)
        return 2
    try:
        status, report = validate_template(source)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"installation refused: {exc}", file=sys.stderr)
        return 1
    if status:
        for error in report.get("errors", []):
            print(f"installation refused: {error}", file=sys.stderr)
        for dependency in report.get("missing_dependencies", []):
            print(f"installation refused: missing dependency {dependency}", file=sys.stderr)
        return status
    template_id = report["id"]
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / template_id
    if target.exists():
        print(f"installation refused: template already exists: {target}", file=sys.stderr)
        return 2
    temporary = Path(tempfile.mkdtemp(prefix=f".{template_id}-", dir=target_root))
    try:
        staged = temporary / template_id
        shutil.copytree(source, staged)
        os.replace(staged, target)
    except Exception as exc:
        print(f"installation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    print(json.dumps({"id": template_id, "path": str(target), "fingerprint": report["fingerprint"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
