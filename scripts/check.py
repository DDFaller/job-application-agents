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
    ROOT / "integrations" / "tests",
    ROOT / "job_application_agents" / "render_service",
    ROOT / "job_application_agents" / "orchestration",
    ROOT / "job_application_agents" / "sync",
    ROOT / "job_application_agents" / "auto_apply",
    ROOT / "skills" / "manage-job-applications" / "scripts",
    ROOT / "skills" / "maintain-master-curriculum" / "scripts",
    ROOT / "skills" / "tailor-application-bundle" / "scripts",
    ROOT / "skills" / "humanize-application-copy" / "scripts",
    ROOT / "skills" / "add-latex-template" / "scripts",
    ROOT / "job_application_agents" / "job_search",
    ROOT / "functions",
    ROOT / "deploy" / "firestore",
)


def run(command: list[str]) -> bool:
    if command[:4] == [sys.executable, "-m", "unittest", "discover"]:
        test_root = Path(command[command.index("-s") + 1])
        if not any(test_root.glob("test_*.py")):
            print(f"SKIP {test_root}: no test files")
            return True
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
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(directory),
            "-p",
            "test_*.py",
            "-v",
        ]
        # auto_apply contains a package subdirectory (`drivers`) whose
        # relative imports require unittest's repository top-level context.
        if directory == ROOT / "job_application_agents" / "auto_apply":
            command[command.index("-p"):command.index("-p")] = ["-t", str(ROOT)]
        ok = run(command) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
