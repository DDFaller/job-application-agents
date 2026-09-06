from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_application_agents.orchestration.contracts import StageTask, WorkerProfile
from job_application_agents.orchestration.worker_command import build_worker_command, sanitized_worker_environment


class WorkerCommandTests(unittest.TestCase):
    def make_task(self, root: Path) -> Path:
        task = StageTask(
            "batch", "run", "job", "https://example.com/job", "job-extraction", 1,
            "job-application-agents:extract-job-opening",
            str(root), str(root / "out"), str(root / "result.json"),
        )
        path = root / "task.json"
        task.write(path)
        return path

    def test_agy_is_one_shot_and_receives_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = build_worker_command(
                WorkerProfile("agy", "gemini-flash", "low"), self.make_task(root),
                repository_root=root / "repo",
            )
            self.assertEqual(command[:3], ["agy", "--add-dir", str(root)])
            self.assertIn("--print", command)
            self.assertNotIn("--prompt-interactive", command)

    def test_agy_claude_rejects_effort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with self.assertRaisesRegex(ValueError, "do not accept"):
                build_worker_command(
                    WorkerProfile("agy", "claude-sonnet-4-6", "low"), self.make_task(root),
                    repository_root=root / "repo",
                )

    def test_codex_uses_exec_and_no_auto_approval_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = build_worker_command(
                WorkerProfile("codex", "gpt-5.6-luna", "low"), self.make_task(root),
                repository_root=root / "repo",
            )
            self.assertEqual(command[:3], ["codex", "--search", "exec"])
            self.assertIn("workspace-write", command)
            self.assertIn("sandbox_workspace_write.network_access=true", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertIn(
                str((root / "repo" / "skills" / "extract-job-opening" / "SKILL.md").resolve()),
                command[-1],
            )
            self.assertIn("keys are exactly name, path, and sha256", command[-1])
            self.assertIn("non-retryable blocker must set restart_stage to null", command[-1])
            self.assertIn("batch-shared artifact may reside under another job key", command[-1])

    def test_worker_environment_drops_integration_secrets(self) -> None:
        from unittest.mock import patch
        with patch.dict("os.environ", {"NOTION_TOKEN": "secret", "PATH": "/bin"}, clear=True):
            environment = sanitized_worker_environment()
        self.assertNotIn("NOTION_TOKEN", environment)
        self.assertEqual(environment["PATH"], "/bin")

    def test_agy_interactive_uses_dash_i(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = build_worker_command(
                WorkerProfile("agy", "gemini-flash", "low"), self.make_task(root),
                repository_root=root / "repo",
                interactive=True,
            )
            self.assertEqual(command[:3], ["agy", "--add-dir", str(root)])
            self.assertIn("-i", command)
            self.assertNotIn("--print", command)

    def test_codex_interactive_omits_exec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = build_worker_command(
                WorkerProfile("codex", "gpt-5.6-luna", "low"), self.make_task(root),
                repository_root=root / "repo",
                interactive=True,
            )
            self.assertEqual(command[:2], ["codex", "--search"])
            self.assertNotIn("exec", command)
            self.assertIn("workspace-write", command)

    def test_opencode_noninteractive_uses_run_json_and_scoped_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict("os.environ", {"OPENCODE_BIN": "opencode"}, clear=False):
                command = build_worker_command(
                    WorkerProfile("opencode", "openai/gpt-5.6", "medium"), self.make_task(root),
                    repository_root=root / "repo",
                )
            self.assertEqual(command[:11], [
                "opencode", "run", "--model", "openai/gpt-5.6",
                "--format", "json", "--dir", str((root / "repo").resolve()),
                "--pure", "--variant", "medium",
            ])
            self.assertIn("keys are exactly name, path, and sha256", command[-1])
            self.assertNotIn("--auto", command)

    def test_opencode_interactive_uses_tui_prompt_for_supervision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict("os.environ", {"OPENCODE_BIN": "opencode"}, clear=False):
                command = build_worker_command(
                    WorkerProfile("opencode", "openai/gpt-5.6"), self.make_task(root),
                    repository_root=root / "repo", interactive=True,
                )
            self.assertEqual(command[:5], [
                "opencode", "run", "--interactive", "--model", "openai/gpt-5.6",
            ])
            self.assertTrue(command[-1].startswith("Execute exactly one job-application workflow stage."))
            self.assertIn("--pure", command)
            self.assertNotIn("--format", command)

    def test_opencode_auto_approval_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict("os.environ", {"OPENCODE_BIN": "opencode"}, clear=False):
                command = build_worker_command(
                    WorkerProfile("opencode", "openai/gpt-5.6", auto_approve=True),
                    self.make_task(root), repository_root=root / "repo",
                )
            self.assertIn("--auto", command)

    def test_muse_uses_exec_with_data_root_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = build_worker_command(
                WorkerProfile("muse", "muse-spark", "medium"), self.make_task(root),
                repository_root=root / "repo",
            )
            self.assertEqual(
                command[:6],
                ["muse", "exec", "--workspace", str(root), "--model", "muse-spark"],
            )
            self.assertIn("--reasoning-effort", command)
            self.assertIn("medium", command)
            self.assertNotIn("--approval-mode", command)
            self.assertTrue(command[-1].startswith("Execute exactly one job-application workflow stage."))

    def test_muse_auto_approval_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = build_worker_command(
                WorkerProfile("muse", "muse-spark", auto_approve=True),
                self.make_task(root), repository_root=root / "repo",
            )
            self.assertIn("--approval-mode", command)
            self.assertIn("never", command)

    def test_muse_interactive_omits_exec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command = build_worker_command(
                WorkerProfile("muse", "muse-spark"), self.make_task(root),
                repository_root=root / "repo", interactive=True,
            )
            self.assertEqual(command[0], "muse")
            self.assertNotIn("exec", command)
            self.assertIn("--workspace", command)


if __name__ == "__main__":
    unittest.main()
