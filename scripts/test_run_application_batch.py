import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("run_application_batch.py")
SPEC = importlib.util.spec_from_file_location("run_application_batch", SCRIPT)
run_application_batch = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(run_application_batch)


def make_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "executor": "agent-deck",
        "group": "job-applications",
        "max_active_jobs": 3,
        "max_stage_attempts": 3,
        "interval": 5.0,
        "profiles": None,
        "harness": "muse",
        "model": "muse-spark",
        "effort": "low",
        "auto_approve": False,
        "interactive": True,
        "once": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class BatchScriptTests(unittest.TestCase):
    def test_parser_accepts_muse_and_host_flags(self) -> None:
        args = run_application_batch.parser().parse_args(
            ["--jobs", "jobs.json", "--harness", "muse", "--unattended", "--launch-host"]
        )
        self.assertEqual(args.harness, "muse")
        self.assertTrue(args.unattended)
        self.assertTrue(args.launch_host)

    def test_apply_unattended_disables_prompts(self) -> None:
        args = make_args(unattended=True)
        run_application_batch.apply_unattended(args)
        self.assertFalse(args.interactive)
        self.assertTrue(args.auto_approve)

    def test_apply_unattended_is_noop_without_flag(self) -> None:
        args = make_args(unattended=False)
        run_application_batch.apply_unattended(args)
        self.assertTrue(args.interactive)
        self.assertFalse(args.auto_approve)

    def test_build_host_argv_carries_resolved_settings(self) -> None:
        args = make_args(unattended=True, once=True)
        run_application_batch.apply_unattended(args)
        command = run_application_batch.build_host_argv(
            args, Path("/data"), Path("/data/state.json")
        )
        self.assertIn("--state", command)
        self.assertIn("/data/state.json", command)
        self.assertIn("--harness", command)
        self.assertIn("muse", command)
        self.assertIn("--no-interactive", command)
        self.assertIn("--auto-approve", command)
        self.assertIn("--once", command)
        self.assertNotIn("--jobs", command)
        self.assertNotIn("--launch-host", command)

    def test_build_host_argv_prefers_profiles_file(self) -> None:
        args = make_args(profiles=Path("profiles.json"))
        command = run_application_batch.build_host_argv(
            args, Path("/data"), Path("/data/state.json")
        )
        self.assertIn("--profiles", command)
        self.assertNotIn("--harness", command)

    def test_launch_host_session_returns_agent_deck_id(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"id": "host-1"}), stderr=""
        )
        with patch.object(
            run_application_batch.subprocess, "run", return_value=completed
        ) as runner:
            identifier = run_application_batch.launch_host_session(
                repository=Path("/repo"),
                group="job-applications",
                title="batch-host",
                host_argv=["python3", "scripts/run_application_batch.py"],
            )
        self.assertEqual(identifier, "host-1")
        launched = runner.call_args.args[0]
        self.assertEqual(launched[:2], ["agent-deck", "launch"])
        self.assertIn("--no-wait", launched)

    def test_launch_host_session_rejects_empty_id(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({}), stderr=""
        )
        with patch.object(
            run_application_batch.subprocess, "run", return_value=completed
        ):
            with self.assertRaisesRegex(RuntimeError, "no session id"):
                run_application_batch.launch_host_session(
                    repository=Path("/repo"),
                    group="job-applications",
                    title="batch-host",
                    host_argv=["python3", "scripts/run_application_batch.py"],
                )

    def test_launch_host_rejects_non_agent_deck_executor(self) -> None:
        argv = ["run_application_batch.py", "--jobs", "jobs.json", "--executor", "tmux", "--launch-host"]
        with patch("sys.argv", argv):
            with self.assertRaisesRegex(SystemExit, "requires --executor agent-deck"):
                run_application_batch.main()


if __name__ == "__main__":
    unittest.main()
