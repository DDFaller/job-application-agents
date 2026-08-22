#!/usr/bin/env python3
"""Run repository tests and deterministic package checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEST_DIRS = (
    ROOT / "scripts",
    ROOT / "skills" / "manage-job-applications" / "scripts",
    ROOT / "skills" / "maintain-master-curriculum" / "scripts",
    ROOT / "skills" / "tailor-application-bundle" / "scripts",
    ROOT / "skills" / "add-latex-template" / "scripts",
)


def run(command: list[str]) -> bool:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=ROOT).returncode == 0


def main() -> int:
    ok = True
    for relative in (Path(".codex-plugin/plugin.json"), Path(".mcp.json")):
        try:
            json.loads((ROOT / relative).read_text(encoding="utf-8"))
            print(f"OK {relative}")
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL {relative}: {exc}", file=sys.stderr)
            ok = False
    for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
        content = skill.read_text(encoding="utf-8")
        valid = content.startswith("---\n") and "\nname:" in content and "\ndescription:" in content
        print(("OK " if valid else "FAIL ") + str(skill.relative_to(ROOT)))
        ok = ok and valid
    for directory in TEST_DIRS:
        ok = run([sys.executable, "-m", "unittest", "discover", "-s", str(directory), "-p", "test_*.py", "-v"]) and ok
    ok = run([
        sys.executable,
        str(ROOT / "skills" / "tailor-application-bundle" / "scripts" / "render_bundle.py"),
        "--preflight",
    ]) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
