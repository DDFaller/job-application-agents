#!/usr/bin/env python3
"""List and attach directly to active tmux or Agent Deck stage sessions."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def list_sessions() -> list[dict[str, str]]:
    try:
        completed = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}\t#{session_created_string}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    sessions = []
    for line in completed.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            name, attached, created = parts[0], parts[1], parts[2]
            sessions.append({
                "name": name,
                "attached": attached != "0",
                "created": created,
            })
    return sessions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filter", nargs="?", help="Substring filter for session name")
    parser.add_argument("--all", action="store_true", help="Show all tmux sessions, not just jaa-* or agentdeck_*")
    args = parser.parse_args()

    sessions = list_sessions()
    if not args.all:
        sessions = [
            s for s in sessions if s["name"].startswith("jaa-") or s["name"].startswith("agentdeck_")
        ]

    if args.filter:
        sessions = [s for s in sessions if args.filter in s["name"]]

    if not sessions:
        prefix = f" matching '{args.filter}'" if args.filter else ""
        print(f"No active job sessions found{prefix}.")
        print("Run `python3 scripts/run_application_batch.py` to start a batch.")
        return 1

    if len(sessions) == 1:
        target = sessions[0]["name"]
        print(f"Attaching to {target}...")
        os.execvp("tmux", ["tmux", "attach", "-t", target])

    print("Active job sessions:")
    for idx, session in enumerate(sessions, 1):
        attached = " (attached)" if session["attached"] else ""
        print(f"  [{idx}] {session['name']} - created {session['created']}{attached}")

    try:
        choice = input(f"\nSelect session [1-{len(sessions)}] (or Enter for 1, Ctrl+C to cancel): ").strip()
        idx = int(choice) if choice else 1
        if not 1 <= idx <= len(sessions):
            print("Invalid choice.")
            return 1
        target = sessions[idx - 1]["name"]
        os.execvp("tmux", ["tmux", "attach", "-t", target])
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
