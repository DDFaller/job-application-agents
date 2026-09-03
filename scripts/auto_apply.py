#!/usr/bin/env python3
"""CLI interface for Playwright automated job application submission."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if __name__ == "__main__" and VENV_PYTHON.is_file() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.auto_apply import AutoApplyService


def main() -> int:
    parser = argparse.ArgumentParser(description="Automate job application submission using Playwright.")
    parser.add_argument(
        "--app-dir",
        type=Path,
        required=True,
        help="Path to the tailored application package directory (e.g. job-search/applications/company/role/id)",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="Optional path to candidate_profile.json",
    )
    parser.add_argument(
        "--mode",
        choices=["supervised", "dry-run"],
        default="dry-run",
        help="Execution mode. Dry-run is the safe default; supervised fills for review.",
    )
    parser.add_argument(
        "--allow-submit",
        action="store_true",
        help=(
            "opt into submission after review; also requires "
            "JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45000,
        help="Page timeout in milliseconds (default: 45000).",
    )

    args = parser.parse_args()

    service = AutoApplyService()
    profile = service.load_candidate_profile(args.profile)

    receipt = service.apply(
        app_dir=args.app_dir,
        candidate_profile=profile,
        mode=args.mode,
        timeout_ms=args.timeout,
        allow_submission=args.allow_submit,
    )

    return 0 if receipt.success else 1


if __name__ == "__main__":
    sys.exit(main())
