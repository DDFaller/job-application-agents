"""Validate an isolated profile-selection result against its bound sources."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from job_application_agents.positioning import assess_fit, assess_selection, validate_selection


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--derive', action='store_true', help='Derive decision/profile from evidence and save them before validation')
    args = parser.parse_args()
    try:
        selection = json.loads(args.selection.read_text())
        if args.derive:
            decision, profile = assess_selection(selection, args.data_root.resolve())
            selection.update(decision=decision, selected_profile_id=profile)
        validate_selection(selection, args.data_root.resolve())
        if args.derive:
            args.selection.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + '\n')
        report = assess_fit(selection, args.data_root.resolve())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({'validated': True, 'fit': report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
