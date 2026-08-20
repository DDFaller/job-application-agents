#!/usr/bin/env python3
"""Resolve the canonical Markdown curriculum from sources/current.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from source_manifest import manifest_for


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    # Kept as a compatibility option for existing coordinators; it is ignored.
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args()
    source = args.source_dir.expanduser().resolve()
    pointer = source / "current.json"
    errors: list[str] = []
    try:
        current = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"curriculum unavailable: cannot read {pointer}: {exc}", file=sys.stderr)
        return 2
    if current.get("source_dir") != str(source):
        errors.append("source manifest source_dir does not match requested source")
    try:
        live = manifest_for(source, current.get("version"))
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
        live = None
    if live is not None and current.get("source_hashes") != live["source_hashes"]:
        errors.append("source manifest hashes do not match canonical files")
    if current.get("schema_version") != 2:
        errors.append("source manifest schema_version must be 2")
    if errors:
        for error in errors:
            print(f"curriculum unavailable: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "version": current.get("version"),
        "source_dir": str(source),
        "markdown_sources": current.get("markdown_sources", []),
        "source_hashes": current.get("source_hashes", {}),
        "manifest": str(pointer),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
