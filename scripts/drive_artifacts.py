#!/usr/bin/env python3
"""Read a Google Drive folder of job-application artifacts into the private data root.

The Drive scope is read-only. Downloads never go inside this git repository.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_application_agents.config import ConfigurationError

from integrations.drive.client import DriveConfigurationError, GoogleDriveClient, parse_folder_id
from integrations.drive.config import load_drive_config
from integrations.drive.sync import DriveSyncError, format_tree, iter_drive_tree, pull_drive_folder


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="strict JSON config file")
    parser.add_argument("--folder-id", help="Drive folder id or drive.google.com folder URL")
    parser.add_argument("--data-root", type=Path, help="private directory that receives downloads")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("authorize", help="authorize read-only Drive access")
    subcommands.add_parser("status", help="list the Drive folder without downloading")
    subcommands.add_parser("pull", help="download the Drive folder into the data root")
    return parser


def _config(args: argparse.Namespace):
    config = load_drive_config(args.config)
    if args.folder_id:
        config = replace(config, folder_id=parse_folder_id(args.folder_id))
    if args.data_root:
        config = replace(config, data_root=args.data_root.expanduser())
    return config


def _require_folder(config) -> str:
    if not config.folder_id:
        raise DriveConfigurationError(
            "Set JAA_DRIVE_FOLDER_ID, drive.folder_id, or pass --folder-id"
        )
    return config.folder_id


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _config(args)
        if args.command == "authorize":
            email = GoogleDriveClient(config).authorize()
            account = email or "the configured service account"
            print(f"READY   Google Drive read-only access for {account}")
            return 0
        folder_id = _require_folder(config)
        client = GoogleDriveClient(config)
        client.connect()
        if args.command == "status":
            entries = iter_drive_tree(client, folder_id)
            listing = format_tree(entries)
            if listing:
                print(listing)
            print(f"READY   {len(entries)} files in Drive folder {folder_id}")
            return 0
        result = pull_drive_folder(
            client, folder_id, config.data_root, repo_root=REPO_ROOT
        )
    except (ConfigurationError, DriveConfigurationError, DriveSyncError) as exc:
        print(f"BLOCKED {exc}", file=sys.stderr)
        return 1
    print(f"READY   destination: {result.destination}")
    print(
        f"READY   wrote {len(result.written)}, unchanged {len(result.unchanged)}, "
        f"skipped {len(result.skipped)}"
    )
    for path in result.written:
        print(f"WROTE   {path}")
    for path in result.skipped:
        print(f"SKIP    {path}")
    return 0


if __name__ == "__main__":
    if VENV_PYTHON.is_file() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])
    raise SystemExit(main())
