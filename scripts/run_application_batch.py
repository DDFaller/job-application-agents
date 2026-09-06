#!/usr/bin/env python3
"""Create or resume a durable flat-stage application batch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from job_application_agents.config import resolve_data_root
from job_application_agents.orchestration import (
    AgentDeckExecutor,
    BatchController,
    DEFAULT_APPLICATION_STAGES,
    JobSpec,
    LocalProcessExecutor,
    TmuxExecutor,
    WorkerProfile,
)
from job_application_agents.orchestration.worker_command import resolve_opencode_binary


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    source = result.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--jobs",
        type=Path,
        help="JSON file with list of job URLs (strings) or {key, opening_url} objects",
    )
    source.add_argument("--state", type=Path, help="existing batch state JSON")
    result.add_argument(
        "--data-root",
        type=Path,
        default=Path.home() / "Documents" / "job-search",
        help="Private working directory for candidate sources and generated applications (default: ~/Documents/job-search)",
    )
    result.add_argument("--role-profile", help="Default role profile to use for jobs (e.g. backend-engineer)")
    result.add_argument("--executor", choices=("agent-deck", "tmux", "local"), default="agent-deck")
    result.add_argument("--harness", choices=("agy", "codex", "opencode"), default="agy")
    result.add_argument("--interactive", action="store_true", default=True, help="Enable interactive co-pilot mode in tmux/agent-deck")
    result.add_argument("--no-interactive", dest="interactive", action="store_false", help="Disable interactive mode")
    result.add_argument("--model", default="gpt-5.6-luna")
    result.add_argument("--effort", choices=("low", "medium", "high"))
    result.add_argument(
        "--profiles",
        type=Path,
        help="JSON object mapping extractor/writer/humanizer/reviewer/renderer to WorkerProfile fields",
    )
    result.add_argument("--auto-approve", action="store_true")
    result.add_argument("--max-active-jobs", type=int, default=3)
    result.add_argument("--max-stage-attempts", type=int, default=3)
    result.add_argument("--group", default="job-applications")
    result.add_argument("--parent-session")
    result.add_argument("--once", action="store_true", help="advance once and exit")
    result.add_argument("--cancel", action="store_true", help="cancel unfinished jobs in --state")
    result.add_argument("--interval", type=float, default=5.0)
    return result


def _url_to_key(url: str, index: int) -> str:
    path = url.split("?", 1)[0].rstrip("/")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path.rsplit("/", 1)[-1]).strip("-").lower()
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    if slug:
        return f"{slug}-{url_hash}"
    return f"job-{index + 1}-{url_hash}"


def load_jobs(path: Path, default_role_profile: str | None = None) -> list[JobSpec]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("jobs file must contain a JSON list")
    jobs: list[JobSpec] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, str):
            opening_url = item.strip()
            if not opening_url:
                raise ValueError(f"empty URL at index {index}")
            key = _url_to_key(opening_url, index)
            role_profile = default_role_profile
        elif isinstance(item, dict):
            opening_url = item["opening_url"]
            key = item.get("key") or _url_to_key(opening_url, index)
            role_profile = item.get("role_profile", default_role_profile)
        else:
            raise ValueError(f"unsupported job entry at index {index}: {type(item).__name__}")

        # Ensure uniqueness across generated or duplicate keys
        candidate_key = key
        counter = 2
        while candidate_key in seen_keys:
            candidate_key = f"{key}-{counter}"
            counter += 1
        seen_keys.add(candidate_key)

        jobs.append(
            JobSpec(
                key=candidate_key,
                opening_url=opening_url,
                role_profile=role_profile,
            )
        )
    return jobs


def snapshot(state: dict) -> dict[str, str]:
    return {key: job["status"] for key, job in state["jobs"].items()}


def load_profiles(path: Path) -> dict[str, WorkerProfile]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("profiles file must contain a JSON object")
    profiles = {name: WorkerProfile(**settings) for name, settings in value.items()}
    for profile in profiles.values():
        profile.validate()
    return profiles


def main() -> int:
    args = parser().parse_args()
    if not 0.25 <= args.interval <= 45:
        raise SystemExit("--interval must be between 0.25 and 45 seconds")
    repository = Path(__file__).resolve().parent.parent
    data_root = resolve_data_root(args.data_root, repository_root=repository)
    if args.executor == "agent-deck":
        executor = AgentDeckExecutor(
            repository,
            group=args.group,
            parent_session=args.parent_session,
            interactive=args.interactive,
        )
    elif args.executor == "tmux":
        executor = TmuxExecutor(
            repository,
            interactive=args.interactive,
        )
    else:
        executor = LocalProcessExecutor(repository)
    if args.profiles:
        profiles = load_profiles(args.profiles)
    else:
        profile = WorkerProfile(
            args.harness, args.model, args.effort, auto_approve=args.auto_approve
        )
        profiles = {stage.profile: profile for stage in DEFAULT_APPLICATION_STAGES}
    for profile in profiles.values():
        profile.validate()
    if any(profile.harness == "opencode" for profile in profiles.values()):
        executable = resolve_opencode_binary()
        try:
            subprocess.run(
                [executable, "--version"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise SystemExit(
                f"OpenCode preflight failed for {executable!r}; install it or set OPENCODE_BIN: {exc}"
            ) from exc
    controller = BatchController(
        repository,
        data_root,
        executor=executor,
        profiles=profiles,
        stages=DEFAULT_APPLICATION_STAGES,
        max_active_jobs=args.max_active_jobs,
        max_stage_attempts=args.max_stage_attempts,
    )
    state_path = args.state
    if state_path is None:
        if args.cancel:
            raise SystemExit("--cancel requires --state")
        state_path = controller.create(load_jobs(args.jobs, default_role_profile=args.role_profile))
        print(json.dumps({"event": "created", "state": str(state_path)}))
    if args.cancel:
        state = controller.cancel(state_path)
        print(json.dumps({"event": "cancelled", "batch": state["batch_id"], "jobs": snapshot(state)}))
        return 0
    previous: dict[str, str] | None = None
    last_report = 0.0
    while True:
        state = controller.tick(state_path)
        current = snapshot(state)
        now = time.monotonic()
        if current != previous or now - last_report >= 45:
            print(json.dumps({"event": "status", "batch": state["batch_id"], "jobs": current}))
            previous = current
            last_report = now
        if args.once or state["status"] == "complete":
            return 0 if all(value == "prepared" for value in current.values()) else 2
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
