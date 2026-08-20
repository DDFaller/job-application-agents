#!/usr/bin/env python3
"""Start Codex with this repository and the job-search data root in scope."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path.home() / "Documents" / "job-search")
    parser.add_argument("codex_args", nargs="*")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    command = [
        "codex", "-C", str(repo), "--add-dir", str(args.data_root.expanduser().resolve()),
        "-c", "agents.enabled=true", "-c", "agents.max_concurrent_threads_per_session=6",
        *args.codex_args,
    ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
