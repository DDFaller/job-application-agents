from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from job_application_agents.orchestration.contracts import ArtifactReference, StageResult, StageTask, WorkerProfile
from job_application_agents.orchestration.controller import (
    BatchController,
    JobSpec,
    StageDefinition,
    WorkflowLedger,
)
from job_application_agents.orchestration.executors import ExecutionHandle, ExecutionObservation


class FakeLedger:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def init(self, path, run_id, opening_url): self.events.append(("init", run_id))
    def start(self, path, event_id, stage, attempt): self.events.append(("start", event_id))
    def finish(self, path, event_id, status, details): self.events.append(("finish", event_id, status))
    def finalize(self, path, status): self.events.append(("finalize", status))


class FakeExecutor:
    def __init__(self) -> None:
        self.handles: list[ExecutionHandle] = []
        self.stopped: list[str] = []

    def launch(self, task_path, profile):
        task = StageTask.read(task_path)
        handle = ExecutionHandle("fake", str(len(self.handles)), str(task_path), task.result_path)
        self.handles.append(handle)
        return handle

    def poll(self, handle):
        return ExecutionObservation("succeeded") if Path(handle.result_path).exists() else ExecutionObservation("running")

    def stop(self, handle): self.stopped.append(handle.identifier)


class InvalidResultExecutor(FakeExecutor):
    def poll(self, handle):
        if Path(handle.result_path).exists():
            return ExecutionObservation("failed", "invalid task/result contract")
        return ExecutionObservation("running")


class ControllerTests(unittest.TestCase):
    @staticmethod
    def complete(handle: ExecutionHandle, name: str) -> None:
        task = StageTask.read(Path(handle.task_path))
        artifact = Path(task.output_dir) / f"{name}.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}\n")
        reference = ArtifactReference(
            name, str(artifact), hashlib.sha256(artifact.read_bytes()).hexdigest()
        )
        StageResult(
            task.run_id, task.job_key, task.stage, task.attempt,
            "succeeded", True, (reference,),
        ).write(Path(task.result_path))

    def test_capacity_stage_progression_and_controller_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = base / "repo"
            data = base / "data"
            repository.mkdir()
            data.mkdir()
            executor = FakeExecutor()
            ledger = FakeLedger()
            controller = BatchController(
                repository, data, executor=executor,
                profiles={"worker": WorkerProfile("codex", "test")},
                stages=(StageDefinition("extract", "extract-job-opening", "worker"),),
                max_active_jobs=1, ledger=ledger,
            )
            with patch(
                "job_application_agents.orchestration.controller.BatchPreflight.run",
                return_value=(),
            ):
                state_path = controller.create(
                    [JobSpec("one", "https://example.com/1"), JobSpec("two", "https://example.com/2")],
                    batch_id="batch",
                )
            state = controller.tick(state_path)
            self.assertEqual(len(executor.handles), 1)
            self.assertEqual(state["jobs"]["two"]["status"], "queued")

            handle = executor.handles[0]
            task = StageTask.read(Path(handle.task_path))
            artifact = Path(task.output_dir) / "opening.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("{}\n")
            reference = ArtifactReference("opening", str(artifact), hashlib.sha256(artifact.read_bytes()).hexdigest())
            StageResult(task.run_id, task.job_key, task.stage, task.attempt, "succeeded", True, (reference,)).write(Path(task.result_path))
            state = controller.tick(state_path)
            self.assertEqual(state["jobs"]["one"]["status"], "prepared")
            self.assertEqual(state["jobs"]["two"]["status"], "running")
            self.assertIn(("finalize", "prepared"), ledger.events)

    def test_cancel_stops_only_active_worker_and_finalizes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository, data = base / "repo", base / "data"
            repository.mkdir()
            data.mkdir()
            executor, ledger = FakeExecutor(), FakeLedger()
            controller = BatchController(
                repository, data, executor=executor,
                profiles={"worker": WorkerProfile("codex", "test")},
                stages=(StageDefinition("extract", "extract-job-opening", "worker"),),
                ledger=ledger,
            )
            with patch(
                "job_application_agents.orchestration.controller.BatchPreflight.run",
                return_value=(),
            ):
                state_path = controller.create(
                    [JobSpec("one", "https://example.com/1")], batch_id="cancel"
                )
            controller.tick(state_path)
            state = controller.cancel(state_path)
            self.assertEqual(executor.stopped, ["0"])
            self.assertEqual(state["jobs"]["one"]["status"], "cancelled")
            self.assertIn(("finalize", "cancelled"), ledger.events)

    def test_candidate_evidence_runs_once_and_is_shared_across_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository, data = base / "repo", base / "data"
            repository.mkdir()
            data.mkdir()
            executor, ledger = FakeExecutor(), FakeLedger()
            controller = BatchController(
                repository, data, executor=executor,
                profiles={"worker": WorkerProfile("codex", "test")},
                stages=(
                    StageDefinition("extract", "extract-job-opening", "worker"),
                    StageDefinition("candidate-evidence", "map-candidate-evidence", "worker"),
                ),
                max_active_jobs=2, ledger=ledger,
            )
            with patch(
                "job_application_agents.orchestration.controller.BatchPreflight.run",
                return_value=(),
            ):
                state_path = controller.create(
                    [JobSpec("one", "https://example.com/1"), JobSpec("two", "https://example.com/2")],
                    batch_id="shared",
                )
            controller.tick(state_path)
            self.complete(executor.handles[0], "job-one")
            self.complete(executor.handles[1], "job-two")
            controller.tick(state_path)
            self.assertEqual(len(executor.handles), 3)
            self.complete(executor.handles[2], "candidate-evidence")
            state = controller.tick(state_path)
            self.assertEqual(len(executor.handles), 3)
            self.assertEqual(state["jobs"]["one"]["status"], "prepared")
            self.assertEqual(state["jobs"]["two"]["status"], "prepared")

    def test_workflow_ledger_terminal_operations_are_restart_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            repository = Path(__file__).resolve().parents[2]
            ledger = WorkflowLedger(repository)
            stage = StageDefinition("extract", "extract-job-opening", "worker")
            ledger.init(path, "run", "https://example.com/job")
            ledger.start(path, "extract-attempt-1", stage, 1)
            ledger.start(path, "extract-attempt-1", stage, 1)
            ledger.finish(path, "extract-attempt-1", "completed", "done")
            ledger.finish(path, "extract-attempt-1", "completed", "done")
            ledger.finalize(path, "prepared")
            ledger.finalize(path, "prepared")

    def test_malformed_result_contract_retries_without_crashing_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository, data = base / "repo", base / "data"
            repository.mkdir()
            data.mkdir()
            executor, ledger = InvalidResultExecutor(), FakeLedger()
            controller = BatchController(
                repository, data, executor=executor,
                profiles={"worker": WorkerProfile("codex", "test")},
                stages=(StageDefinition("extract", "extract-job-opening", "worker"),),
                max_stage_attempts=2, ledger=ledger,
            )
            with patch(
                "job_application_agents.orchestration.controller.BatchPreflight.run",
                return_value=(),
            ):
                state_path = controller.create(
                    [JobSpec("one", "https://example.com/1")], batch_id="malformed"
                )
            controller.tick(state_path)
            Path(executor.handles[0].result_path).write_text(
                '{"artifacts":["not-an-object"]}\n', encoding="utf-8"
            )
            state = controller.tick(state_path)
            self.assertEqual(state["jobs"]["one"]["status"], "running")
            self.assertEqual(state["jobs"]["one"]["attempts"]["extract"], 2)

    def test_missing_result_does_not_retry_runtime_success_or_permission_failure(self) -> None:
        observations = (
            ExecutionObservation("failed", "worker exited without a result contract", "SUCCESS"),
            ExecutionObservation("failed", "permission denied by runtime", "ERROR"),
        )
        for observation in observations:
            with self.subTest(observation=observation), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repository, data = base / "repo", base / "data"
                repository.mkdir()
                data.mkdir()
                executor, ledger = FakeExecutor(), FakeLedger()
                controller = BatchController(
                    repository, data, executor=executor,
                    profiles={"worker": WorkerProfile("agy", "gemini-3.8-flash-high")},
                    stages=(StageDefinition("extract", "extract-job-opening", "worker"),),
                    max_stage_attempts=2, ledger=ledger,
                )
                with patch(
                    "job_application_agents.orchestration.controller.BatchPreflight.run",
                    return_value=(),
                ):
                    state_path = controller.create(
                        [JobSpec("one", "https://example.com/1")], batch_id="missing-result"
                    )
                controller.tick(state_path)
                with patch.object(executor, "poll", return_value=observation):
                    state = controller.tick(state_path)
                    self.assertEqual(controller.tick(state_path), state)
                job = state["jobs"]["one"]
                self.assertEqual(job["status"], "failed")
                self.assertEqual(job["attempts"]["extract"], 1)
                self.assertEqual(len(executor.handles), 1)
                self.assertEqual(job["blocker"]["code"], "missing_result_contract")
                self.assertFalse(job["blocker"]["retryable"])
                self.assertIsNone(job["blocker"]["restart_stage"])
                self.assertIn(("finalize", "failed"), ledger.events)

    def test_launch_exception_requires_input_without_retry(self) -> None:
        for error in (PermissionError("command approval denied"), OSError("launcher failed")):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repository, data = base / "repo", base / "data"
                repository.mkdir()
                data.mkdir()
                executor, ledger = FakeExecutor(), FakeLedger()
                controller = BatchController(
                    repository, data, executor=executor,
                    profiles={"worker": WorkerProfile("agy", "gemini-3.8-flash-high")},
                    stages=(StageDefinition("extract", "extract-job-opening", "worker"),),
                    max_stage_attempts=2, ledger=ledger,
                )
                with patch(
                    "job_application_agents.orchestration.controller.BatchPreflight.run",
                    return_value=(),
                ):
                    state_path = controller.create(
                        [JobSpec("one", "https://example.com/1")], batch_id="launch-failure"
                    )
                with patch.object(executor, "launch", side_effect=error) as launch:
                    state = controller.tick(state_path)
                    self.assertEqual(controller.tick(state_path), state)
                    self.assertEqual(launch.call_count, 1)
                job = state["jobs"]["one"]
                self.assertEqual(job["status"], "needs_input")
                self.assertEqual(job["attempts"]["extract"], 1)
                self.assertEqual(job["blocker"]["code"], "worker_launch_failed")
                self.assertFalse(job["blocker"]["retryable"])
                self.assertIsNone(job["blocker"]["restart_stage"])
                self.assertEqual(job["blocker"]["message"], str(error))
                self.assertIn(("finalize", "needs_input"), ledger.events)

    def test_load_jobs_supports_list_of_urls(self) -> None:
        from scripts.run_application_batch import load_jobs
        with tempfile.TemporaryDirectory() as directory:
            jobs_file = Path(directory) / "jobs.json"
            jobs_file.write_text(
                json.dumps([
                    "https://www.linkedin.com/jobs/view/4311177547/",
                    "https://example.com/jobs/backend-engineer?ref=feed",
                    "https://example.com/jobs/backend-engineer",
                ]),
                encoding="utf-8",
            )
            jobs = load_jobs(jobs_file, default_role_profile="default-profile")
            self.assertEqual(len(jobs), 3)
            self.assertEqual(jobs[0].opening_url, "https://www.linkedin.com/jobs/view/4311177547/")
            self.assertTrue(jobs[0].key.startswith("4311177547-"))
            self.assertEqual(jobs[0].role_profile, "default-profile")

            self.assertEqual(jobs[1].opening_url, "https://example.com/jobs/backend-engineer?ref=feed")
            self.assertEqual(jobs[2].opening_url, "https://example.com/jobs/backend-engineer")
            # Keys must be unique even if slugs/urls are similar
            self.assertNotEqual(jobs[1].key, jobs[2].key)

    def test_load_jobs_supports_legacy_dict_objects(self) -> None:
        from scripts.run_application_batch import load_jobs
        with tempfile.TemporaryDirectory() as directory:
            jobs_file = Path(directory) / "jobs.json"
            jobs_file.write_text(
                json.dumps([
                    {"key": "job-custom-1", "opening_url": "https://example.com/1", "role_profile": "role-1"},
                    {"opening_url": "https://example.com/2"},
                ]),
                encoding="utf-8",
            )
            jobs = load_jobs(jobs_file, default_role_profile="default-role")
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0].key, "job-custom-1")
            self.assertEqual(jobs[0].opening_url, "https://example.com/1")
            self.assertEqual(jobs[0].role_profile, "role-1")
            self.assertEqual(jobs[1].opening_url, "https://example.com/2")
            self.assertEqual(jobs[1].role_profile, "default-role")


    def test_review_restart_revises_without_reparsing_extraction(self) -> None:
        from job_application_agents.orchestration.contracts import StageBlocker

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository, data = base / "repo", base / "data"
            repository.mkdir()
            data.mkdir()
            class ReviewBlockingExecutor(FakeExecutor):
                def poll(self, handle):
                    task = StageTask.read(Path(handle.task_path))
                    if task.stage == "review" and Path(handle.result_path).exists():
                        return ExecutionObservation("blocked", "revise tone")
                    return super().poll(handle)

            executor, ledger = ReviewBlockingExecutor(), FakeLedger()
            controller = BatchController(
                repository, data, executor=executor,
                profiles={"worker": WorkerProfile("codex", "test")},
                stages=(
                    StageDefinition("extract", "extract-job-opening", "worker"),
                    StageDefinition("write", "tailor-application-bundle", "worker"),
                    StageDefinition("review", "review-application-bundle", "worker"),
                ),
                max_active_jobs=1, ledger=ledger,
            )
            with patch(
                "job_application_agents.orchestration.controller.BatchPreflight.run",
                return_value=(),
            ):
                state_path = controller.create(
                    [JobSpec("one", "https://example.com/1")], batch_id="reparse",
                )
            controller.tick(state_path)  # launch extract
            self.complete(executor.handles[0], "job")
            controller.tick(state_path)  # collect extract, launch write
            first_write = StageTask.read(Path(executor.handles[1].task_path))
            self.complete(executor.handles[1], "bundle")
            controller.tick(state_path)  # collect write, launch review
            review_task = StageTask.read(Path(executor.handles[2].task_path))
            review_artifact = Path(review_task.output_dir) / "review.json"
            review_artifact.parent.mkdir(parents=True, exist_ok=True)
            review_artifact.write_text("{}\n", encoding="utf-8")
            StageResult(
                review_task.run_id, review_task.job_key, review_task.stage,
                review_task.attempt, "blocked", False,
                (ArtifactReference(
                    "review.json", str(review_artifact),
                    hashlib.sha256(review_artifact.read_bytes()).hexdigest(),
                ),),
                blocker=StageBlocker(
                    code="needs_rewrite", message="revise tone",
                    retryable=True, restart_stage="write",
                ),
            ).write(Path(review_task.result_path))
            state = controller.tick(state_path)  # review restart -> write attempt 2
            job = state["jobs"]["one"]
            self.assertEqual(job["attempts"]["extract"], 1)
            self.assertEqual(job["attempts"]["write"], 2)
            second_write = StageTask.read(Path(executor.handles[3].task_path))
            self.assertEqual(second_write.source_fingerprint, first_write.source_fingerprint)
            self.assertTrue(second_write.source_fingerprint)
            self.assertTrue(
                any("do not re-extract" in item for item in second_write.constraints),
                second_write.constraints,
            )
            self.assertFalse(
                any("do not re-extract" in item for item in first_write.constraints),
            )


if __name__ == "__main__":
    unittest.main()
