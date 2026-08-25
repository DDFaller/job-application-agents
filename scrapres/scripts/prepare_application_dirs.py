#!/usr/bin/env python3
"""Create application directories only inside the approved job-search root."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path("/home/falluba/Documents/job-search/applications").resolve()


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: prepare_application_dirs.py PATH [PATH ...]", file=sys.stderr)
        return 2
    for raw in argv:
        target = Path(raw).expanduser().resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            print(f"refusing path outside {ROOT}: {target}", file=sys.stderr)
            return 2
        target.mkdir(parents=True, exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
