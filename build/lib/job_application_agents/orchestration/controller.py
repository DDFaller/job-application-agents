"""Durable single-writer controller for flat job-application stage DAGs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable
from uuid import uuid4

from job_application_agents.config import resolve_data_root

from .contracts import ArtifactReference, StageResult, StageTask, WorkerProfile, atomic_json_write
from .executors import ExecutionHandle, StageExecutor


BATCH_SCHEMA_VERSION = 1
TERMINAL_JOB_STATUSES = frozenset({"prepared", "needs_input", "failed", "cancelled"})


@dataclass(frozen=True)
class JobSpec:
    key: str
    opening_url: str
    role_profile: str | None = None


@dataclass(frozen=True)
class StageDefinition:
    name: str
    skill: str
    profile: str


DEFAULT_APPLICATION_STAGES = (
    StageDefinition("job-extraction", "job-application-agents:extract-job-opening", "extractor"),
    StageDefinition("bundle-writing", "job-application-agents:tailor-application-bundle", "writer"),
    StageDefinition("copy-humanization", "job-application-agents:humanize-application-copy", "humanizer"),
    StageDefinition("independent-review", "job-application-agents:review-application-bundle", "reviewer"),
    StageDefinition("render-promotion", "job-application-agents:render-application-bundle", "renderer"),
)


class BatchPreflight:
    """Validate shared sources and tools before spending any model capacity."""

    def __init__(self, repository_root: Path, data_root: Path) -> None:
        self.repository_root = repository_root.resolve()
        self.data_root = resolve_data_root(data_root, repository_root=self.repository_root)

    def run(self) -> tuple[ArtifactReference, ...]:
        if not self.data_root.is_dir():
            raise ValueError(f"data root does not exist: {self.data_root}")
        sources_dir = self.data_root / "sources"
        if not sources_dir.is_dir():
            raise ValueError(f"sources directory does not exist: {sources_dir}")

        render_script = self.repository_root / "skills/tailor-application-bundle/scripts/render_bundle.py"
        if render_script.is_file():
            subprocess.run(
                ["python3", str(render_script), "--preflight"],
                cwd=self.repository_root,
                check=True,
                capture_output=True,
                text=True,
            )

        from job_application_agents.sources import (
            PREFORMATTED_CV_FILENAMES,
            STANDARD_SOURCE_FILES,
            list_role_profiles,
        )

        profiles = list_role_profiles(sources_dir)
        artifacts: list[ArtifactReference] = []
        if profiles:
            for profile in profiles:
                pdir = sources_dir / profile
                for fname in (*STANDARD_SOURCE_FILES, *PREFORMATTED_CV_FILENAMES):
                    fpath = pdir / fname
                    if fpath.is_file():
                        digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
                        artifacts.append(
                            ArtifactReference(f"source:{profile}:{fname}", str(fpath.resolve()), digest)
                        )
        else:
            for fname in (*STANDARD_SOURCE_FILES, *PREFORMATTED_CV_FILENAMES):
                fpath = sources_dir / fname
                if fpath.is_file():
                    digest = hashlib.sha256(fpath.read_bytes()).hexdigest()
                    artifacts.append(
                        ArtifactReference(f"candidate-source:{fname}", str(fpath.resolve()), digest)
                    )

        for artifact in artifacts:
            artifact.validate(data_root=self.data_root)
        return tuple(artifacts)


class WorkflowLedger:
    """Controller-only adapter around the immutable timing-ledger script."""

    def __init__(self, repository_root: Path) -> None:
        self.script = repository_root.resolve() / (
            "skills/manage-job-applications/scripts/workflow_timing.py"
        )

    def _run(self, *arguments: str) -> None:
        subprocess.run(["python3", str(self.script), *arguments], check=True, capture_output=True)

    def init(self, path: Path, run_id: str, opening_url: str) -> None:
        self._run("init", "--file", str(path), "--run-id", run_id, "--opening-url", opening_url)

    def start(self, path: Path, event_id: str, stage: StageDefinition, attempt: int) -> None:
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
            if any(item.get("event_id") == event_id for item in record.get("events", [])):
                return
        self._run(
            "start", "--file", str(path), "--event-id", event_id,
            "--skill", stage.skill, "--stage", stage.name,
            "--attempt", str(attempt), "--parallel-group", "application-batch",
            "--kind", "active",
        )

    def finish(self, path: Path, event_id: str, status: str, details: str | None) -> None:
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
            event = next(
                (item for item in record.get("events", []) if item.get("event_id") == event_id),
                None,
            )
            if event is not None and event.get("ended_at") is not None:
                return
        arguments = ["finish", "--file", str(path), "--event-id", event_id, "--status", status]
        if details:
            arguments.extend(("--details", details))
        self._run(*arguments)

    def finalize(self, path: Path, status: str) -> None:
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("ended_at") is not None:
                return
        self._run("finalize", "--file", str(path), "--status", status)


class BatchController:
    """Advance persisted jobs while keeping every worker stateless and isolated."""

    def __init__(
        self,
        repository_root: Path,
        data_root: Path,
        *,
        executor: StageExecutor,
        profiles: dict[str, WorkerProfile],
        stages: tuple[StageDefinition, ...],
        max_active_jobs: int = 3,
        max_stage_attempts: int = 3,
        ledger: WorkflowLedger | None = None,
    ) -> None:
        if not stages:
            raise ValueError("at least one stage is required")
        if max_active_jobs < 1 or max_stage_attempts < 1:
            raise ValueError("capacity and retry limit must be positive")
        missing = {stage.profile for stage in stages} - profiles.keys()
        if missing:
            raise ValueError(f"undefined worker profiles: {', '.join(sorted(missing))}")
        self.repository_root = repository_root.resolve()
        self.data_root = resolve_data_root(data_root, repository_root=self.repository_root)
        self.executor = executor
        self.profiles = profiles
        self.stages = stages
        self.max_active_jobs = max_active_jobs
        self.max_stage_attempts = max_stage_attempts
        self.ledger = ledger or WorkflowLedger(self.repository_root)
        self.state_root = self.data_root / ".orchestration" / "batches"

    def create(self, jobs: Iterable[JobSpec], *, batch_id: str | None = None) -> Path:
        shared_artifacts = BatchPreflight(self.repository_root, self.data_root).run()
        identifier = batch_id or uuid4().hex
        state_path = self.state_root / f"{identifier}.json"
        if state_path.exists():
            raise ValueError(f"batch already exists: {identifier}")
        records: dict[str, Any] = {}
        for job in jobs:
            if not job.key or not job.opening_url or job.key in records:
                raise ValueError("jobs require unique non-empty keys and opening URLs")
            run_id = f"{identifier}-{job.key}"
            ledger_path = self.data_root / "applications/.workflow-runs" / f"{run_id}.json"
            self.ledger.init(ledger_path, run_id, job.opening_url)
            records[job.key] = {
                "opening_url": job.opening_url,
                "role_profile": job.role_profile,
                "run_id": run_id,
                "ledger_path": str(ledger_path),
                "status": "queued",
                "stage_index": 0,
                "attempts": {},
                "artifacts": [asdict(item) for item in shared_artifacts],
                "active": None,
                "blocker": None,
            }
        if not records:
            raise ValueError("batch requires at least one job")
        atomic_json_write(state_path, {
            "schema_version": BATCH_SCHEMA_VERSION,
            "batch_id": identifier,
            "status": "running",
            "shared_candidate_artifacts": [],
            "jobs": records,
        })
        return state_path

    def tick(self, state_path: Path) -> dict[str, Any]:
        state = self._load(state_path)
        for job in state["jobs"].values():
            if job["status"] == "launching" and job["active"] and not job["active"].get("handle"):
                self._activate(state_path, state, job)
        self._collect(state_path, state)
        active = sum(1 for job in state["jobs"].values() if job["active"])
        for key, job in state["jobs"].items():
            if active >= self.max_active_jobs:
                break
            if job["status"] != "queued" or job["active"]:
                continue
            self._launch(state_path, state, state["batch_id"], key, job)
            if job["active"]:
                active += 1
        statuses = {job["status"] for job in state["jobs"].values()}
        if statuses and statuses <= TERMINAL_JOB_STATUSES:
            state["status"] = "complete"
        atomic_json_write(state_path, state)
        return state

    def cancel(self, state_path: Path, *, job_key: str | None = None) -> dict[str, Any]:
        """Stop active stage sessions and durably cancel selected unfinished jobs."""
        state = self._load(state_path)
        if job_key is not None and job_key not in state["jobs"]:
            raise ValueError(f"unknown application: {job_key}")
        for key, job in state["jobs"].items():
            if job_key is not None and key != job_key:
                continue
            if job["status"] in TERMINAL_JOB_STATUSES:
                continue
            active = job.get("active")
            if active and active.get("handle"):
                self.executor.stop(ExecutionHandle(**active["handle"]))
                self.ledger.finish(
                    Path(job["ledger_path"]), active["event_id"], "cancelled",
                    "Cancelled by the batch controller.",
                )
            job["active"] = None
            job["status"] = "cancelled"
            self.ledger.finalize(Path(job["ledger_path"]), "cancelled")
        statuses = {job["status"] for job in state["jobs"].values()}
        if statuses <= TERMINAL_JOB_STATUSES:
            state["status"] = "complete"
        atomic_json_write(state_path, state)
        return state

    def _load(self, path: Path) -> dict[str, Any]:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema_version") != BATCH_SCHEMA_VERSION:
            raise ValueError("unsupported batch-state schema")
        return state

    def _launch(
        self, state_path: Path, state: dict[str, Any], batch_id: str,
        key: str, job: dict[str, Any],
    ) -> None:
        stage = self.stages[job["stage_index"]]
        if stage.name == "candidate-evidence":
            shared = state.get("shared_candidate_artifacts", [])
            if shared:
                self._merge_artifacts(job, shared)
                job["attempts"][stage.name] = 1
                event_id = "candidate-evidence-shared"
                self.ledger.start(Path(job["ledger_path"]), event_id, stage, 1)
                self.ledger.finish(
                    Path(job["ledger_path"]), event_id, "completed",
                    "Reused the batch-shared validated candidate-evidence artifacts.",
                )
                job["stage_index"] += 1
                if job["stage_index"] == len(self.stages):
                    job["status"] = "prepared"
                    self.ledger.finalize(Path(job["ledger_path"]), "prepared")
                atomic_json_write(state_path, state)
                return
            if any(
                other is not job
                and other.get("active")
                and other.get("stage_index", 0) < len(self.stages)
                and self.stages[other["stage_index"]].name == "candidate-evidence"
                for other in state["jobs"].values()
            ):
                return
        attempt = int(job["attempts"].get(stage.name, 0)) + 1
        job["attempts"][stage.name] = attempt
        job["blocker"] = None
        stage_root = self.state_root / batch_id / key / stage.name / f"attempt-{attempt}"
        result_path = stage_root / "result.json"
        task = StageTask(
            batch_id=batch_id,
            run_id=job["run_id"],
            job_key=key,
            opening_url=job["opening_url"],
            stage=stage.name,
            attempt=attempt,
            skill=stage.skill,
            data_root=str(self.data_root),
            output_dir=str(stage_root / "outputs"),
            result_path=str(result_path),
            inputs=tuple(ArtifactReference(**item) for item in job["artifacts"]),
            constraints=(
                "No nested agents or delegation",
                "No application submission, employer contact, or APPLIED status",
                "No Notion credentials or master-curriculum mutation",
            ),
        )
        task_path = stage_root / "task.json"
        task.write(task_path)
        event_id = f"{stage.name}-attempt-{attempt}"
        job["active"] = {
            "handle": None,
            "event_id": event_id,
            "task_path": str(task_path),
        }
        job["status"] = "launching"
        atomic_json_write(state_path, state)
        self._activate(state_path, state, job)

    def _activate(self, state_path: Path, state: dict[str, Any], job: dict[str, Any]) -> None:
        stage = self.stages[job["stage_index"]]
        attempt = int(job["attempts"][stage.name])
        task_path = Path(job["active"]["task_path"])
        event_id = job["active"]["event_id"]
        self.ledger.start(Path(job["ledger_path"]), event_id, stage, attempt)
        try:
            handle = self.executor.launch(task_path, self.profiles[stage.profile])
        except Exception as exc:
            self.ledger.finish(Path(job["ledger_path"]), event_id, "failed", str(exc))
            job["active"] = None
            self._retry_or_fail(job, stage, attempt, str(exc), retryable=True, blocked=False)
            atomic_json_write(state_path, state)
            return
        job["active"]["handle"] = asdict(handle)
        job["status"] = "running"
        atomic_json_write(state_path, state)

    def _collect(self, state_path: Path, state: dict[str, Any]) -> None:
        for job in state["jobs"].values():
            if not job["active"]:
                continue
            if not job["active"].get("handle"):
                continue
            handle = ExecutionHandle(**job["active"]["handle"])
            observation = self.executor.poll(handle)
            if observation.state == "running":
                continue
            stage = self.stages[job["stage_index"]]
            attempt = int(job["attempts"][stage.name])
            event_id = job["active"]["event_id"]
            self.ledger.finish(
                Path(job["ledger_path"]), event_id,
                "completed" if observation.state == "succeeded" else observation.state,
                observation.details,
            )
            job["active"] = None
            if observation.state == "stopped":
                job["status"] = "cancelled"
                job["blocker"] = {
                    "code": "worker_stopped", "message": observation.details or "worker stopped",
                    "retryable": False, "user_action": None, "restart_stage": None,
                }
                self.ledger.finalize(Path(job["ledger_path"]), "cancelled")
                atomic_json_write(state_path, state)
                continue
            if observation.state == "succeeded":
                result = StageResult.read(Path(handle.result_path))
                result.validate_for(StageTask.read(Path(handle.task_path)))
                result_artifacts = [asdict(item) for item in result.artifacts]
                self._merge_artifacts(job, result_artifacts)
                job["blocker"] = None
                if stage.name == "candidate-evidence":
                    state["shared_candidate_artifacts"] = result_artifacts
                    for other in state["jobs"].values():
                        self._merge_artifacts(other, result_artifacts)
                job["stage_index"] += 1
                if job["stage_index"] == len(self.stages):
                    job["status"] = "prepared"
                    self.ledger.finalize(Path(job["ledger_path"]), "prepared")
                else:
                    job["status"] = "queued"
                atomic_json_write(state_path, state)
                continue
            retryable = observation.state == "failed"
            if Path(handle.result_path).is_file():
                try:
                    result = StageResult.read(Path(handle.result_path))
                    result.validate_for(StageTask.read(Path(handle.task_path)))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    result = None
                    job["blocker"] = {
                        "code": "invalid_result_contract",
                        "message": str(exc),
                        "retryable": True,
                        "user_action": None,
                        "restart_stage": stage.name,
                    }
                if result is not None:
                    retryable = bool(result.blocker and result.blocker.retryable)
                    job["blocker"] = asdict(result.blocker) if result.blocker else None
                if result is not None and result.blocker and result.blocker.restart_stage:
                    target = next(
                        (index for index, item in enumerate(self.stages)
                         if item.name == result.blocker.restart_stage),
                        None,
                    )
                    if target is None:
                        retryable = False
                        job["blocker"]["message"] += " (unknown restart stage)"
                    elif retryable:
                        self._merge_artifacts(
                            job, [asdict(artifact) for artifact in result.artifacts]
                        )
                        target_stage = self.stages[target]
                        target_attempts = int(job["attempts"].get(target_stage.name, 0))
                        if target_attempts < self.max_stage_attempts:
                            job["stage_index"] = target
                            job["status"] = "queued"
                            atomic_json_write(state_path, state)
                            continue
            if (
                stage.name == "candidate-evidence"
                and not (retryable and attempt < self.max_stage_attempts)
            ):
                self._propagate_shared_failure(
                    state,
                    source_job=job,
                    status="needs_input" if observation.state == "blocked" else "failed",
                    blocker=job["blocker"] or {
                        "code": "candidate_evidence_failed",
                        "message": observation.details or "shared candidate evidence failed",
                        "retryable": retryable,
                        "user_action": None,
                        "restart_stage": None,
                    },
                )
            self._retry_or_fail(
                job, stage, attempt, observation.details,
                retryable=retryable, blocked=observation.state == "blocked",
            )
            atomic_json_write(state_path, state)

    def _retry_or_fail(
        self, job: dict[str, Any], stage: StageDefinition, attempt: int,
        details: str | None, *, retryable: bool, blocked: bool,
    ) -> None:
        if retryable and attempt < self.max_stage_attempts:
            job["status"] = "queued"
            return
        job["status"] = "needs_input" if blocked else "failed"
        job["blocker"] = job["blocker"] or {
            "code": "stage_execution_failed", "message": details or "stage failed",
            "retryable": retryable, "user_action": None,
        }
        self.ledger.finalize(Path(job["ledger_path"]), job["status"])

    def _propagate_shared_failure(
        self,
        state: dict[str, Any],
        *,
        source_job: dict[str, Any],
        status: str,
        blocker: dict[str, Any],
    ) -> None:
        for other in state["jobs"].values():
            if other is source_job or other["status"] in TERMINAL_JOB_STATUSES:
                continue
            active = other.get("active")
            if active and active.get("handle"):
                self.executor.stop(ExecutionHandle(**active["handle"]))
                self.ledger.finish(
                    Path(other["ledger_path"]), active["event_id"], "cancelled",
                    "Stopped because the batch-shared candidate evidence failed.",
                )
            other["active"] = None
            other["status"] = status
            other["blocker"] = dict(blocker)
            self.ledger.finalize(Path(other["ledger_path"]), status)

    @staticmethod
    def _merge_artifacts(job: dict[str, Any], artifacts: list[dict[str, Any]]) -> None:
        merged = {item["name"]: item for item in job["artifacts"]}
        merged.update({item["name"]: item for item in artifacts})
        job["artifacts"] = list(merged.values())


__all__ = [
    "BatchController", "BatchPreflight", "DEFAULT_APPLICATION_STAGES", "JobSpec",
    "StageDefinition", "WorkflowLedger",
]
