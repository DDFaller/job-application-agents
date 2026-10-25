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

from .contracts import (
    UNCHANGED_SOURCES_CONSTRAINT,
    ArtifactReference,
    StageResult,
    StageTask,
    WorkerProfile,
    atomic_json_write,
    fingerprint_artifacts,
)
from .executors import ExecutionHandle, StageExecutor


BATCH_SCHEMA_VERSION = 2
TERMINAL_JOB_STATUSES = frozenset({"prepared", "needs_input", "failed", "cancelled", "skipped"})


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
    StageDefinition("profile-selection", "job-application-agents:select-application-profile", "writer"),
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
        self.configured_stages = stages
        self.max_active_jobs = max_active_jobs
        self.max_stage_attempts = max_stage_attempts
        self.ledger = ledger or WorkflowLedger(self.repository_root)
        self.state_root = self.data_root / ".orchestration" / "batches"

    def create(self, jobs: Iterable[JobSpec], *, batch_id: str | None = None,
               junior_tailoring_instruction: Path | None = None,
               review_fit: bool = True, prepare_selected: bool = False,
               automatic_fit_threshold: int | None = None) -> Path:
        from job_application_agents.job_search.fit import automatic_eligibility
        automatic_eligibility({}, automatic_fit_threshold)
        self.stages = self.configured_stages
        shared_artifacts = BatchPreflight(self.repository_root, self.data_root).run()
        if junior_tailoring_instruction is not None:
            from job_application_agents.positioning import digest, read_reference
            authority = junior_tailoring_instruction.expanduser().resolve(strict=True)
            ref = ArtifactReference('junior-tailoring-instruction.txt', str(authority), digest(authority))
            read_reference(asdict(ref), self.data_root)
            if not authority.read_text(encoding='utf-8').strip():
                raise ValueError('junior tailoring instruction must not be empty')
            shared_artifacts += (ref,)
        if any(stage.name == "profile-selection" for stage in self.stages):
            from job_application_agents.positioning import load_active_library, digest
            library_path, library = load_active_library(self.data_root)
            shared_artifacts += (ArtifactReference("positioning-library.json", str(library_path), digest(library_path)),)
            shared_artifacts += tuple(
                ArtifactReference("source:positioning:" + ref["name"], ref["path"], ref["sha256"])
                for ref in library["sources"]
            )
            known_profiles = {profile["id"] for profile in library["profiles"]}
            jobs = list(jobs)
            if any(job.role_profile and job.role_profile not in known_profiles for job in jobs):
                raise ValueError("explicit role profile is not in the approved positioning library")
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
            "stages": [asdict(stage) for stage in self.stages],
            "batch_id": identifier,
            "status": "running",
            "shared_candidate_artifacts": [],
            "fit_policy": {
                "enabled": review_fit,
                "prepare_selected": prepare_selected,
                "automatic_fit_threshold": automatic_fit_threshold,
                "submission_authorized": False,
            },
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
        elif statuses <= TERMINAL_JOB_STATUSES | {"awaiting_fit_review"}:
            state["status"] = "awaiting_fit_review"
        else:
            state["status"] = "running"
        atomic_json_write(state_path, state)
        return state

    def review_fit(self, state_path: Path, job_key: str, decision: str, *, selection_sha256: str) -> dict[str, Any]:
        """Record an explicit choice about exact reviewed evidence, never submit."""
        if decision not in {"prepare", "skip"}:
            raise ValueError("fit decision must be prepare or skip")
        state = self._load(state_path)
        job = state["jobs"].get(job_key)
        if job is None or job["status"] != "awaiting_fit_review" or job["active"]:
            raise ValueError("job is not waiting for fit review")
        ref = next(a for a in job["artifacts"] if a["name"] == "profile-selection.json")
        if ref["sha256"] != selection_sha256:
            raise ValueError("fit review refers to a different selection revision")
        selection = self._selection(job)
        from job_application_agents.positioning import assess_fit
        job["fit_report"] = assess_fit(selection, self.data_root,
            threshold=state.get("fit_policy", {}).get("automatic_fit_threshold"))
        job["fit_decision"] = {
            "decision": decision, "source": "user", "selection_sha256": selection_sha256,
            "submission_authorized": False,
        }
        job["blocker"] = None
        if decision == "skip":
            job["status"] = "skipped"
            self.ledger.finalize(Path(job["ledger_path"]), "skipped")
        elif job["stage_index"] >= len(self.stages):
            job["status"] = "prepared"
            self.ledger.finalize(Path(job["ledger_path"]), "prepared")
        else:
            job["status"] = "queued"
        state["status"] = "running"
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
        version = state.get("schema_version")
        if version not in {1, BATCH_SCHEMA_VERSION}:
            raise ValueError("unsupported batch-state schema")
        if version == 1:
            # Schema 1 did not store its stage sequence. Preserve the legacy
            # caller's sequence, excluding the new selection stage. Custom
            # legacy workflows must still pass their original stages.
            self.stages = tuple(s for s in self.configured_stages if s.name != "profile-selection")
        else:
            stored = state.get("stages")
            if not isinstance(stored, list) or not stored:
                raise ValueError("batch state is missing its persisted stage sequence")
            self.stages = tuple(StageDefinition(**item) for item in stored)
        if not self.stages or {s.profile for s in self.stages} - self.profiles.keys():
            raise ValueError("worker configuration cannot resume this batch's stored stages")
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
        inputs = tuple(ArtifactReference(**item) for item in job["artifacts"])
        source_fingerprint = fingerprint_artifacts(job["artifacts"], source_only=True)
        constraints = [
            "No nested agents or delegation",
            "No application submission, employer contact, or APPLIED status",
            "No Notion credentials or master-curriculum mutation",
        ]
        selection_stages = {"bundle-writing", "copy-humanization", "independent-review", "render-promotion"}
        if stage.name == "profile-selection":
            constraints.append("Explicit requested_profile: " + json.dumps(job.get("role_profile")))
            if state.get("fit_policy", {}).get("enabled"):
                constraints.append(
                    "Write profile-selection schema_version 2. Return decision review with the best "
                    "evidence-backed profile even with unknown/unmet requirements or weak duties. "
                    "Do not skip or invent scores. The controller calculates and exposes fit, then "
                    "records the user's preparation decision separately."
                )
        if any(a.name == 'junior-tailoring-instruction.txt' for a in inputs):
            constraints.append(
                "Read the direct user instruction in junior-tailoring-instruction.txt. For actual entry/junior "
                "scope, use junior_tailoring_override with scope prepare_only and the exact authority reference/quote "
                "to prepare a CV despite weak experience. Keep unmet/unknown checks truthful. This authorizes "
                "document preparation, not invented study experience, skills, language levels or submission answers. "
                "For non-junior scope omit the override and use normal qualification."
            )
        if stage.name in selection_stages and any(a.name == "positioning-library.json" for a in inputs):
            selection = self._selection(job)
            if selection["schema_version"] == 2:
                approved = job.get("fit_decision", {})
                selection_ref = next(a for a in job["artifacts"] if a["name"] == "profile-selection.json")
                if approved.get("decision") != "prepare" or approved.get("selection_sha256") != selection_ref["sha256"]:
                    raise ValueError("preparation requires a decision on this exact fit assessment")
                constraints.append("Preserve all fit-report.json gaps and unknowns. Preparation approval is not evidence that requirements are met.")
            if selection["decision"] not in {"use", "review"}:
                raise ValueError("skipped profile selection cannot launch document work")
            library = json.loads(Path(selection["library"]["path"]).read_text())
            profile = next(p for p in library["profiles"] if p["id"] == selection["selected_profile_id"])
            constraints.extend([
                "Bind the bundle to profile-selection.json using inputs.profile_selection_json and inputs.profile_selection_sha256. "
                "Use its selected_profile_id exactly, use source_profile " + profile["source_profile"] +
                ", and use the approved headline exactly: " + profile["headline"],
                "Profile positioning: " + json.dumps(profile, ensure_ascii=False),
                "Apply these candidate-approved editorial rules: " + json.dumps(library["editorial_rules"], ensure_ascii=False),
                "Explain professional identity, evidence and intended contribution. No invented personal passion. "
                "Reject generic interchangeable summaries. Keep a readable one-page CV, body text at least 10pt, "
                "with flexible length; select evidence by relevance rather than fixed employer bullet caps.",
            ])
        fingerprints = job.setdefault("stage_fingerprints", {})
        if (
            attempt > 1
            and fingerprints.get(stage.name) == source_fingerprint
            and job["artifacts"]
        ):
            # Relaunch with byte-identical inputs: the worker must revise the
            # previously accepted artifacts instead of re-extracting data.
            constraints.append(
                UNCHANGED_SOURCES_CONSTRAINT.format(fingerprint=source_fingerprint[:16])
            )
        fingerprints[stage.name] = source_fingerprint
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
            inputs=inputs,
            constraints=tuple(constraints),
            source_fingerprint=source_fingerprint,
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
            job["blocker"] = {
                "code": "worker_launch_failed", "message": str(exc),
                "retryable": False,
                "user_action": "Resolve the worker launch failure before starting a new run.",
                "restart_stage": None,
            }
            self._retry_or_fail(job, stage, attempt, str(exc), retryable=False, blocked=True)
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
                try:
                    if any(a["name"] == "positioning-library.json" for a in job["artifacts"]):
                        protected = {"positioning-library.json", "junior-tailoring-instruction.txt", "fit-report.json"}
                        if stage.name != "job-extraction":
                            protected.add("job.json")
                        if stage.name != "profile-selection":
                            protected.add("profile-selection.json")
                        originals = {a["name"]: a for a in job["artifacts"]}
                        for artifact in result_artifacts:
                            if artifact["name"] in protected:
                                original = originals.get(artifact["name"])
                                if original is None or artifact["sha256"] != original["sha256"]:
                                    raise ValueError("stage attempted to replace protected positioning input")
                        # Rendered bundles carry byte-identical provenance copies.
                        # Retain canonical paths used by the selection's bindings.
                        result_artifacts = [
                            a for a in result_artifacts if a["name"] not in protected
                        ]
                    self._merge_artifacts(job, result_artifacts)
                    if stage.name == "profile-selection":
                        selection = self._selection(job)
                        job["selection_reason"] = selection["reason"]
                        job["selected_profile_id"] = selection["selected_profile_id"]
                        policy = state.get("fit_policy", {})
                        if policy.get("enabled") and selection["schema_version"] != 2:
                            raise ValueError("new batches require profile-selection schema 2 for fit review")
                        if selection["schema_version"] == 2:
                            from job_application_agents.positioning import assess_fit
                            report = assess_fit(selection, self.data_root,
                                threshold=policy.get("automatic_fit_threshold"))
                            job["fit_report"] = report
                            job["match_score"] = report["assessment"]["score"]
                            job["match_breakdown"] = report["assessment"]
                            report_path = Path(handle.result_path).parent / "fit-report.json"
                            atomic_json_write(report_path, report)
                            self._merge_artifacts(job, [{
                                "name": "fit-report.json", "path": str(report_path),
                                "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                            }])
                            if not policy.get("prepare_selected"):
                                job["stage_index"] += 1
                                job["status"] = "awaiting_fit_review"
                                job["blocker"] = None
                                atomic_json_write(state_path, state)
                                continue
                            job["fit_decision"] = {
                                "decision": "prepare", "source": "explicit_batch_selection",
                                "selection_sha256": next(a["sha256"] for a in job["artifacts"] if a["name"] == "profile-selection.json"),
                                "submission_authorized": False,
                            }
                        if selection["decision"] == "skip":
                            job["status"] = "skipped"
                            job["blocker"] = None
                            self.ledger.finalize(Path(job["ledger_path"]), "skipped")
                            atomic_json_write(state_path, state)
                            continue
                    elif stage.name in {"bundle-writing", "copy-humanization", "independent-review", "render-promotion"} and any(a["name"] == "positioning-library.json" for a in job["artifacts"]):
                        from job_application_agents.positioning import read_reference, validate_bundle_binding
                        bundle_ref = next(a for a in job["artifacts"] if a["name"] == "bundle.json")
                        validate_bundle_binding(json.loads(read_reference(bundle_ref, self.data_root).read_text()), self._selection(job), self.data_root)
                except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
                    job["blocker"] = {"code": "invalid_profile_binding", "message": str(exc), "retryable": False, "user_action": None}
                    self._retry_or_fail(job, stage, attempt, str(exc), retryable=False, blocked=True)
                    atomic_json_write(state_path, state)
                    continue
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
            # A runtime failure alone does not establish that retrying is safe.
            retryable = False
            if Path(handle.result_path).is_file():
                try:
                    result = StageResult.read(Path(handle.result_path))
                    result.validate_for(StageTask.read(Path(handle.task_path)))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    result = None
                    retryable = True
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
            else:
                job["blocker"] = {
                    "code": "missing_result_contract",
                    "message": observation.details or "worker stopped without a result contract",
                    "retryable": False,
                    "user_action": "Inspect the worker trace and resolve the missing StageResult before starting a new run.",
                    "restart_stage": None,
                }
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

    def _selection(self, job: dict[str, Any]) -> dict[str, Any]:
        from job_application_agents.positioning import read_reference, validate_selection
        refs = {a["name"]: a for a in job["artifacts"]}
        path = read_reference(refs["profile-selection.json"], self.data_root)
        selection = json.loads(path.read_text())
        for key, artifact_name in (("library", "positioning-library.json"), ("job", "job.json")):
            bound = selection[key]
            expected = refs[artifact_name]
            if bound["sha256"] != expected["sha256"] or Path(bound["path"]).resolve() != Path(expected["path"]).resolve():
                raise ValueError("selection does not match the batch's " + key)
        if selection.get("requested_profile") != job.get("role_profile"):
            raise ValueError("selection changed the explicit profile request")
        override = selection.get('junior_tailoring_override')
        if override is not None:
            expected = refs.get('junior-tailoring-instruction.txt')
            bound = override.get('user_instruction', {})
            if expected is None or bound.get('sha256') != expected['sha256'] or bound.get('path') != expected['path']:
                raise ValueError('junior override does not match the controller-supplied user instruction')
        validate_selection(selection, self.data_root)
        return selection

    @staticmethod
    def _merge_artifacts(job: dict[str, Any], artifacts: list[dict[str, Any]]) -> None:
        merged = {item["name"]: item for item in job["artifacts"]}
        merged.update({item["name"]: item for item in artifacts})
        job["artifacts"] = list(merged.values())


__all__ = [
    "BatchController", "BatchPreflight", "DEFAULT_APPLICATION_STAGES", "JobSpec",
    "StageDefinition", "WorkflowLedger",
]
