#!/usr/bin/env python3
"""Create and validate the lightweight Markdown-source retrieval manifest."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_master_sources import read_facts, source_hashes


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def manifest_for(source_dir: Path, version: str | None = None) -> dict[str, Any]:
    source = source_dir.expanduser().resolve()
    errors, _ = read_facts(source)
    if errors:
        raise ValueError("; ".join(errors))
    hashes = source_hashes(source)
    return {
        "schema_version": 2,
        "version": version or "unversioned",
        "source_dir": str(source),
        "markdown_sources": sorted(name for name in hashes if name.endswith(".md")),
        "source_hashes": hashes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def manifest_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Write current.json beside canonical Markdown sources.")
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--version", default="unversioned")
    args = parser.parse_args()
    write_json_atomic(args.source_dir.expanduser().resolve() / "current.json", manifest_for(args.source_dir, args.version))
