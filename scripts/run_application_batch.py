#!/usr/bin/env python3
"""Create or resume a durable flat-stage application batch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
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
    result.add_argument("--harness", choices=("agy", "codex", "opencode", "muse"), default="agy")
    result.add_argument("--interactive", action="store_true", default=True, help="Enable interactive co-pilot mode in tmux/agent-deck")
    result.add_argument("--no-interactive", dest="interactive", action="store_false", help="Disable interactive mode")
    result.add_argument(
        "--unattended",
        action="store_true",
        help="Shorthand for --no-interactive --auto-approve: workers run headless "
        "with pre-granted workspace permissions and never wait on prompts",
    )
    result.add_argument(
        "--launch-host",
        action="store_true",
        help="Create the batch from --jobs, then spawn an Agent Deck host session "
        "that runs the controller tick loop; per-stage subworkers launch as "
        "their own sessions under the shared --group",
    )
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


def resolve_profiles(args: argparse.Namespace) -> dict[str, WorkerProfile]:
    if args.profiles:
        return load_profiles(args.profiles)
    profile = WorkerProfile(
        args.harness, args.model, args.effort, auto_approve=args.auto_approve
    )
    return {stage.profile: profile for stage in DEFAULT_APPLICATION_STAGES}


def build_executor(
    args: argparse.Namespace, repository: Path
) -> AgentDeckExecutor | TmuxExecutor | LocalProcessExecutor:
    if args.executor == "agent-deck":
        return AgentDeckExecutor(
            repository,
            group=args.group,
            parent_session=args.parent_session,
            interactive=args.interactive,
        )
    if args.executor == "tmux":
        return TmuxExecutor(
            repository,
            interactive=args.interactive,
        )
    return LocalProcessExecutor(repository)


def build_host_argv(
    args: argparse.Namespace,
    data_root: Path,
    state_path: Path,
) -> list[str]:
    """Re-invoke this script inside the host session to run the tick loop."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--state",
        str(state_path.resolve()),
        "--data-root",
        str(data_root),
        "--executor",
        args.executor,
        "--group",
        args.group,
        "--max-active-jobs",
        str(args.max_active_jobs),
        "--max-stage-attempts",
        str(args.max_stage_attempts),
        "--interval",
        str(args.interval),
    ]
    if args.profiles:
        command.extend(("--profiles", str(args.profiles.resolve())))
    else:
        command.extend(("--harness", args.harness, "--model", args.model))
        if args.effort:
            command.extend(("--effort", args.effort))
    if args.auto_approve:
        command.append("--auto-approve")
    if not args.interactive:
        command.append("--no-interactive")
    if args.once:
        command.append("--once")
    return command


def launch_host_session(
    *,
    repository: Path,
    group: str,
    title: str,
    host_argv: list[str],
) -> str:
    """Spawn an Agent Deck host session running the controller loop."""
    command = [
        "agent-deck",
        "launch",
        str(repository),
        "--title",
        title,
        "--group",
        group,
        "--cmd",
        shlex.join(host_argv),
        "--no-wait",
        "--json",
    ]
    completed = subprocess.run(
        command, check=True, capture_output=True, text=True
    )
    payload = json.loads(completed.stdout)
    identifier = str(payload.get("id") or payload.get("session_id") or "")
    if not identifier:
        raise RuntimeError("Agent Deck host launch returned no session id")
    return identifier


def apply_unattended(args: argparse.Namespace) -> None:
    if args.unattended:
        args.interactive = False
        args.auto_approve = True


def main() -> int:
    args = parser().parse_args()
    apply_unattended(args)
    if args.launch_host and args.executor != "agent-deck":
        raise SystemExit("--launch-host requires --executor agent-deck")
    if args.launch_host and args.state is not None:
        raise SystemExit("--launch-host creates a new batch; pass --jobs, not --state")
    if not 0.25 <= args.interval <= 45:
        raise SystemExit("--interval must be between 0.25 and 45 seconds")
    repository = Path(__file__).resolve().parent.parent
    data_root = resolve_data_root(args.data_root, repository_root=repository)
    profiles = resolve_profiles(args)
    for profile in profiles.values():
        profile.validate()
    if any(profile.harness == "muse" for profile in profiles.values()):
        if shutil.which("muse") is None:
            raise SystemExit("Muse preflight failed; install the muse CLI or fix PATH")
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
        executor=build_executor(args, repository),
        profiles=profiles,
        stages=DEFAULT_APPLICATION_STAGES,
        max_active_jobs=args.max_active_jobs,
        max_stage_attempts=args.max_stage_attempts,
    )
    if args.launch_host:
        state_path = controller.create(
            load_jobs(args.jobs, default_role_profile=args.role_profile)
        )
        batch_id = json.loads(state_path.read_text(encoding="utf-8"))["batch_id"]
        host_argv = build_host_argv(args, data_root, state_path)
        host_id = launch_host_session(
            repository=repository,
            group=args.group,
            title=f"{batch_id}-host",
            host_argv=host_argv,
        )
        print(
            json.dumps(
                {
                    "event": "host-launched",
                    "batch": batch_id,
                    "state": str(state_path),
                    "host": host_id,
                }
            )
        )
        return 0
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
