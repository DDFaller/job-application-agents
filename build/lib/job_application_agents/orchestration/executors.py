"""Execution adapters for durable stage tasks."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
from typing import Callable, Literal, Protocol

from .contracts import StageResult, StageTask, WorkerProfile
from .worker_command import INTEGRATION_SECRET_NAMES, sanitized_worker_environment


ExecutionState = Literal["running", "succeeded", "blocked", "failed", "stopped"]


@dataclass(frozen=True)
class ExecutionHandle:
    executor: str
    identifier: str
    task_path: str
    result_path: str
    pid: int | None = None


@dataclass(frozen=True)
class ExecutionObservation:
    state: ExecutionState
    details: str | None = None
    raw_status: str | None = None


class StageExecutor(Protocol):
    def launch(self, task_path: Path, profile: WorkerProfile) -> ExecutionHandle: ...
    def poll(self, handle: ExecutionHandle) -> ExecutionObservation: ...
    def stop(self, handle: ExecutionHandle) -> None: ...


def _result_observation(handle: ExecutionHandle) -> ExecutionObservation | None:
    result_path = Path(handle.result_path)
    if not result_path.is_file():
        return None
    try:
        task = StageTask.read(Path(handle.task_path))
        result = StageResult.read(result_path)
        result.validate_for(task)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return ExecutionObservation("failed", f"invalid task/result contract: {exc}")
    return ExecutionObservation(result.status, result.details, result.status)


class AgentDeckExecutor:
    """Launch one Agent Deck session per task; result files are authoritative."""

    def __init__(
        self,
        repository_root: Path,
        *,
        group: str = "job-applications",
        parent_session: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        python_executable: str = sys.executable,
        interactive: bool = False,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.group = group
        self.parent_session = parent_session
        self.runner = runner
        self.python_executable = python_executable
        self.interactive = interactive

    @staticmethod
    def _group_component(value: str) -> str:
        """Make a stable, readable Agent Deck group component."""
        component = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
        return component or "unknown"

    def _task_group(self, task: StageTask) -> str:
        """Return company/stage/job grouping without adding job metadata to the contract."""
        company = ""
        for artifact in task.inputs:
            if artifact.name != "job.json":
                continue
            try:
                payload = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                company = str(payload.get("company") or payload.get("employer") or "").strip()
            if company:
                break
        if not company:
            # Extraction has no normalized job.json yet; the job key is the
            # only durable identifier available at launch time.
            company = task.job_key
        parent = self.group.strip("/") or "job-applications"
        return "/".join(
            (
                parent,
                self._group_component(company),
                self._group_component(task.stage),
                self._group_component(task.job_key),
            )
        )

    def launch(self, task_path: Path, profile: WorkerProfile) -> ExecutionHandle:
        task = StageTask.read(task_path)
        title = f"{task.batch_id}-{task.job_key}-{task.stage}-a{task.attempt}"
        wrapper = ["env"]
        for secret_name in INTEGRATION_SECRET_NAMES:
            wrapper.extend(("-u", secret_name))
        wrapper.extend([
            self.python_executable,
            "-m",
            "job_application_agents.orchestration.worker_command",
            "--task",
            str(task_path.resolve()),
            "--repository-root",
            str(self.repository_root),
            "--harness",
            profile.harness,
            "--model",
            profile.model,
        ])
        if profile.effort:
            wrapper.extend(("--effort", profile.effort))
        if profile.auto_approve:
            wrapper.append("--auto-approve")
        if self.interactive:
            wrapper.append("--interactive")
        existing = self.runner(
            ["agent-deck", "list", "--json"], check=True, capture_output=True, text=True
        )
        sessions = json.loads(existing.stdout)
        session = next((item for item in sessions if item.get("title") == title), None)
        if session is not None:
            return ExecutionHandle(
                executor="agent-deck",
                identifier=str(session["id"]),
                task_path=str(task_path.resolve()),
                result_path=task.result_path,
            )
        command = [
            "agent-deck",
            "launch",
            str(self.repository_root),
            "--title",
            title,
            "--group",
            self._task_group(task),
            "--cmd",
            shlex.join(wrapper),
            "--no-assert-done",
            "--no-wait",
            "--json",
        ]
        if self.parent_session:
            command.extend(("--parent", self.parent_session))
        completed = self.runner(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=sanitized_worker_environment(),
        )
        payload = json.loads(completed.stdout)
        identifier = str(payload.get("id") or payload.get("session_id") or "")
        if not identifier:
            raise RuntimeError("Agent Deck launch returned no session id")
        return ExecutionHandle(
            executor="agent-deck",
            identifier=identifier,
            task_path=str(task_path.resolve()),
            result_path=task.result_path,
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionObservation:
        completed = self.runner(
            ["agent-deck", "list", "--json"], check=True, capture_output=True, text=True
        )
        sessions = json.loads(completed.stdout)
        session = next((item for item in sessions if str(item.get("id")) == handle.identifier), None)
        if session is None:
            result = _result_observation(handle)
            if result:
                return result
            return ExecutionObservation("failed", "Agent Deck session disappeared", "missing")
        status = str(session.get("status", "unknown"))
        if status in {"error", "dead", "stopped", "killed", "idle", "waiting"}:
            result = _result_observation(handle)
            if result:
                return result
        if status in {"error", "dead"}:
            return ExecutionObservation("failed", "worker exited without a result contract", status)
        if status in {"stopped", "killed"}:
            return ExecutionObservation("stopped", "worker stopped without a result contract", status)
        if status in {"idle", "waiting"}:
            if self.interactive:
                return ExecutionObservation("running", raw_status=status)
            return ExecutionObservation("failed", "worker became idle without a result contract", status)
        return ExecutionObservation("running", raw_status=status)

    def stop(self, handle: ExecutionHandle) -> None:
        self.runner(["agent-deck", "session", "stop", handle.identifier], check=False)


class TmuxExecutor:
    """Direct native tmux session adapter with clean, accessible session names."""

    def __init__(
        self,
        repository_root: Path,
        *,
        prefix: str = "jaa",
        python_executable: str = sys.executable,
        interactive: bool = True,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.prefix = prefix
        self.python_executable = python_executable
        self.interactive = interactive
        self.runner = runner

    def session_name(self, task: StageTask) -> str:
        clean_key = task.job_key.replace("/", "-").replace(":", "-")
        return f"{self.prefix}-{clean_key}-{task.stage}-a{task.attempt}"

    def launch(self, task_path: Path, profile: WorkerProfile) -> ExecutionHandle:
        task = StageTask.read(task_path)
        name = self.session_name(task)
        check = self.runner(
            ["tmux", "has-session", "-t", name],
            check=False,
            capture_output=True,
            text=True,
        )
        if check.returncode == 0:
            return ExecutionHandle(
                executor="tmux",
                identifier=name,
                task_path=str(task_path.resolve()),
                result_path=task.result_path,
            )

        wrapper = ["env"]
        for secret_name in INTEGRATION_SECRET_NAMES:
            wrapper.extend(("-u", secret_name))
        wrapper.extend([
            self.python_executable,
            "-m",
            "job_application_agents.orchestration.worker_command",
            "--task",
            str(task_path.resolve()),
            "--repository-root",
            str(self.repository_root),
            "--harness",
            profile.harness,
            "--model",
            profile.model,
        ])
        if profile.effort:
            wrapper.extend(("--effort", profile.effort))
        if profile.auto_approve:
            wrapper.append("--auto-approve")
        if self.interactive:
            wrapper.append("--interactive")

        command = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            name,
            "-c",
            str(self.repository_root),
            shlex.join(wrapper),
        ]
        self.runner(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=sanitized_worker_environment(),
        )
        return ExecutionHandle(
            executor="tmux",
            identifier=name,
            task_path=str(task_path.resolve()),
            result_path=task.result_path,
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionObservation:
        result = _result_observation(handle)
        if result:
            return result
        check = self.runner(
            ["tmux", "has-session", "-t", handle.identifier],
            check=False,
            capture_output=True,
            text=True,
        )
        if check.returncode != 0:
            result = _result_observation(handle)
            if result:
                return result
            return ExecutionObservation("failed", "tmux session exited without a result contract", "missing")
        return ExecutionObservation("running")

    def stop(self, handle: ExecutionHandle) -> None:
        self.runner(["tmux", "kill-session", "-t", handle.identifier], check=False)


class LocalProcessExecutor:
    """Optional direct-process adapter using the same contracts as Agent Deck."""

    def __init__(self, repository_root: Path, *, python_executable: str = sys.executable) -> None:
        self.repository_root = repository_root.resolve()
        self.python_executable = python_executable
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def launch(self, task_path: Path, profile: WorkerProfile) -> ExecutionHandle:
        task = StageTask.read(task_path)
        command = [
            self.python_executable,
            "-m",
            "job_application_agents.orchestration.worker_command",
            "--task",
            str(task_path.resolve()),
            "--repository-root",
            str(self.repository_root),
            "--harness",
            profile.harness,
            "--model",
            profile.model,
        ]
        if profile.effort:
            command.extend(("--effort", profile.effort))
        if profile.auto_approve:
            command.append("--auto-approve")
        process = subprocess.Popen(
            command,
            cwd=self.repository_root,
            text=True,
            env=sanitized_worker_environment(),
        )
        identifier = str(process.pid)
        self._processes[identifier] = process
        return ExecutionHandle("local", identifier, str(task_path.resolve()), task.result_path, process.pid)

    def poll(self, handle: ExecutionHandle) -> ExecutionObservation:
        process = self._processes.get(handle.identifier)
        if process is not None:
            returncode = process.poll()
            if returncode is None:
                return ExecutionObservation("running")
            result = _result_observation(handle)
            if result:
                return result
            return ExecutionObservation("failed", f"worker exited {returncode} without a result")
        if handle.pid:
            try:
                os.kill(handle.pid, 0)
                return ExecutionObservation("running")
            except ProcessLookupError:
                pass
            except PermissionError:
                return ExecutionObservation("running")
        result = _result_observation(handle)
        if result:
            return result
        return ExecutionObservation("failed", "worker process disappeared without a result")

    def stop(self, handle: ExecutionHandle) -> None:
        process = self._processes.get(handle.identifier)
        if process and process.poll() is None:
            process.terminate()
        elif handle.pid:
            try:
                os.kill(handle.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
