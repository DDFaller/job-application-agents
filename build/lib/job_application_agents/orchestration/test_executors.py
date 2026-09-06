import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from job_application_agents.orchestration.contracts import (
    ArtifactReference,
    StageResult,
    StageTask,
    WorkerProfile,
)
from job_application_agents.orchestration.executors import (
    AgentDeckExecutor,
    ExecutionHandle,
    TmuxExecutor,
)


class Runner:
    def __init__(self, outputs, returncodes=None):
        self.outputs = iter(outputs)
        self.returncodes = iter(returncodes) if returncodes is not None else None
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        class Completed:
            pass
        completed = Completed()
        completed.stdout = next(self.outputs)
        completed.returncode = next(self.returncodes) if self.returncodes is not None else 0
        return completed


class AgentDeckExecutorTests(unittest.TestCase):
    def make_task(self, root: Path) -> Path:
        task = StageTask(
            "batch", "run", "job", "https://example.com", "extract", 1,
            "extract-job-opening", str(root), str(root / "out"), str(root / "result.json"),
        )
        path = root / "task.json"
        task.write(path)
        return path

    def test_launch_uses_wrapper_not_prompt_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner(["[]", json.dumps({"id": "session-1"})])
            executor = AgentDeckExecutor(root / "repo", runner=runner, python_executable="python3")
            handle = executor.launch(self.make_task(root), WorkerProfile("agy", "gemini-flash"))
            command = runner.commands[1]
            self.assertEqual(handle.identifier, "session-1")
            self.assertIn("--cmd", command)
            self.assertNotIn("--message", command)
            self.assertNotIn("--message-file", command)

    def test_launch_groups_under_parent_using_job_company_and_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job_path = root / "job.json"
            job_path.write_text(json.dumps({"company": "Acme, Inc."}), encoding="utf-8")
            artifact = ArtifactReference(
                "job.json",
                str(job_path),
                hashlib.sha256(job_path.read_bytes()).hexdigest(),
            )
            task = StageTask(
                "batch", "run", "acme-python-engineer", "https://example.com", "bundle-writing", 1,
                "tailor-application-bundle", str(root), str(root / "out"), str(root / "result.json"),
                inputs=(artifact,),
            )
            task_path = root / "task.json"
            task.write(task_path)
            runner = Runner(["[]", json.dumps({"id": "session-1"})])
            executor = AgentDeckExecutor(root / "repo", runner=runner, python_executable="python3")
            executor.launch(task_path, WorkerProfile("agy", "gemini-flash"))
            command = runner.commands[1]
            group_index = command.index("--group") + 1
            self.assertEqual(
                command[group_index],
                "job-applications/acme-inc/bundle-writing/acme-python-engineer",
            )

    def test_launch_interactive_appends_interactive_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner(["[]", json.dumps({"id": "session-1"})])
            executor = AgentDeckExecutor(root / "repo", runner=runner, interactive=True)
            handle = executor.launch(self.make_task(root), WorkerProfile("agy", "gemini-flash"))
            command = runner.commands[1]
            cmd_index = command.index("--cmd") + 1
            self.assertIn("--interactive", command[cmd_index])

    def test_interactive_idle_allows_copilot_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner([json.dumps([{"id": "session-1", "status": "idle"}])])
            executor = AgentDeckExecutor(root / "repo", runner=runner, interactive=True)
            handle = ExecutionHandle(
                "agent-deck", "session-1", str(self.make_task(root)), str(root / "result.json")
            )
            self.assertEqual(executor.poll(handle).state, "running")

    def test_launch_adopts_existing_attempt_by_deterministic_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner([json.dumps([{
                "id": "existing", "title": "batch-job-extract-a1", "status": "running"
            }])])
            executor = AgentDeckExecutor(root / "repo", runner=runner)
            handle = executor.launch(self.make_task(root), WorkerProfile("codex", "test"))
            self.assertEqual(handle.identifier, "existing")
            self.assertEqual(len(runner.commands), 1)

    def test_idle_without_result_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner([json.dumps([{"id": "session-1", "status": "idle"}])])
            executor = AgentDeckExecutor(root / "repo", runner=runner)
            handle = ExecutionHandle(
                "agent-deck", "session-1", str(self.make_task(root)), str(root / "result.json")
            )
            self.assertEqual(executor.poll(handle).state, "failed")

    def test_terminal_status_rechecks_result_to_avoid_completion_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            task_path = self.make_task(root)
            task = StageTask.read(task_path)
            artifact_path = root / "out" / "job.json"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("{}\n", encoding="utf-8")

            class RacingRunner:
                def __call__(self, command, **kwargs):
                    StageResult(
                        run_id=task.run_id,
                        job_key=task.job_key,
                        stage=task.stage,
                        attempt=task.attempt,
                        status="succeeded",
                        validated=True,
                        artifacts=(ArtifactReference(
                            "job.json",
                            str(artifact_path),
                            hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                        ),),
                    ).write(Path(task.result_path))

                    class Completed:
                        stdout = json.dumps([{"id": "session-1", "status": "error"}])

                    return Completed()

            executor = AgentDeckExecutor(root / "repo", runner=RacingRunner())
            handle = ExecutionHandle(
                "agent-deck", "session-1", str(task_path), str(root / "result.json")
            )
            self.assertEqual(executor.poll(handle).state, "succeeded")

    def test_running_session_does_not_accept_an_early_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            task_path = self.make_task(root)
            task = StageTask.read(task_path)
            artifact_path = root / "out" / "job.json"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("{}\n", encoding="utf-8")
            StageResult(
                run_id=task.run_id,
                job_key=task.job_key,
                stage=task.stage,
                attempt=task.attempt,
                status="succeeded",
                validated=True,
                artifacts=(ArtifactReference(
                    "job.json",
                    str(artifact_path),
                    hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                ),),
            ).write(Path(task.result_path))
            runner = Runner([json.dumps([{"id": "session-1", "status": "waiting"}])])
            executor = AgentDeckExecutor(root / "repo", runner=runner)
            handle = ExecutionHandle(
                "agent-deck", "session-1", str(task_path), str(root / "result.json")
            )
            self.assertEqual(executor.poll(handle).state, "running")


class TmuxExecutorTests(unittest.TestCase):
    def make_task(self, root: Path) -> Path:
        task = StageTask(
            "batch", "run", "linkedin/123", "https://example.com", "bundle-writing", 1,
            "tailor-application-bundle", str(root), str(root / "out"), str(root / "result.json"),
        )
        path = root / "task.json"
        task.write(path)
        return path

    def test_launch_creates_clean_named_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner(["", ""], returncodes=[1, 0])
            executor = TmuxExecutor(root / "repo", runner=runner, interactive=True)
            handle = executor.launch(self.make_task(root), WorkerProfile("agy", "gemini-flash"))
            self.assertEqual(handle.identifier, "jaa-linkedin-123-bundle-writing-a1")
            self.assertEqual(runner.commands[0][:3], ["tmux", "has-session", "-t"])
            self.assertEqual(runner.commands[1][:4], ["tmux", "new-session", "-d", "-s"])
            self.assertEqual(runner.commands[1][4], "jaa-linkedin-123-bundle-writing-a1")
            self.assertIn("--interactive", runner.commands[1][-1])

    def test_launch_adopts_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner([""], returncodes=[0])
            executor = TmuxExecutor(root / "repo", runner=runner)
            handle = executor.launch(self.make_task(root), WorkerProfile("agy", "gemini-flash"))
            self.assertEqual(handle.identifier, "jaa-linkedin-123-bundle-writing-a1")
            self.assertEqual(len(runner.commands), 1)

    def test_poll_returns_running_when_session_alive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner([""], returncodes=[0])
            executor = TmuxExecutor(root / "repo", runner=runner)
            handle = ExecutionHandle("tmux", "jaa-session", str(self.make_task(root)), str(root / "result.json"))
            self.assertEqual(executor.poll(handle).state, "running")

    def test_poll_returns_succeeded_when_result_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            task_path = self.make_task(root)
            task = StageTask.read(task_path)
            artifact_path = root / "out" / "bundle.json"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("{}\n", encoding="utf-8")
            StageResult(
                run_id=task.run_id,
                job_key=task.job_key,
                stage=task.stage,
                attempt=task.attempt,
                status="succeeded",
                validated=True,
                artifacts=(ArtifactReference(
                    "bundle.json",
                    str(artifact_path),
                    hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                ),),
            ).write(Path(task.result_path))

            runner = Runner([])
            executor = TmuxExecutor(root / "repo", runner=runner)
            handle = ExecutionHandle("tmux", "jaa-session", str(task_path), str(root / "result.json"))
            self.assertEqual(executor.poll(handle).state, "succeeded")

    def test_poll_returns_failed_when_session_exited_without_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner([""], returncodes=[1])
            executor = TmuxExecutor(root / "repo", runner=runner)
            handle = ExecutionHandle("tmux", "jaa-session", str(self.make_task(root)), str(root / "result.json"))
            self.assertEqual(executor.poll(handle).state, "failed")

    def test_stop_kills_tmux_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner([""])
            executor = TmuxExecutor(root / "repo", runner=runner)
            handle = ExecutionHandle("tmux", "jaa-session", str(self.make_task(root)), str(root / "result.json"))
            executor.stop(handle)
            self.assertEqual(runner.commands[0], ["tmux", "kill-session", "-t", "jaa-session"])


if __name__ == "__main__":
    unittest.main()
