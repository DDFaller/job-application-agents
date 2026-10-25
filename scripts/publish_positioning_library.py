#!/usr/bin/env python3
"""Validate or activate a reviewed private positioning library."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from job_application_agents.config import resolve_data_root
from job_application_agents.positioning_publication import publish_library, validate_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--approval', choices=['APPROVED'])
    args = parser.parse_args()
    try:
        root = resolve_data_root(args.data_root, repository_root=Path(__file__).resolve().parents[1])
        if args.approval:
            print(publish_library(args.library, args.review, root, approval=args.approval))
        else:
            validate_review(args.library, args.review, root)
            print('Review validated; no activation performed.')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
