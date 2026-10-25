from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest

from job_application_agents.orchestration.contracts import (
    ArtifactReference,
    StageBlocker,
    StageResult,
    StageTask,
    WorkerProfile,
    fingerprint_artifacts,
    is_source_artifact,
)


class ContractTests(unittest.TestCase):
    def test_round_trip_and_artifact_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            artifact = root / "output.json"
            artifact.write_text("{}\n", encoding="utf-8")
            reference = ArtifactReference("opening", str(artifact), hashlib.sha256(artifact.read_bytes()).hexdigest())
            task = StageTask(
                "batch", "run", "job", "https://example.com/job", "extract", 1,
                "extract-job-opening", str(root), str(root / "out"), str(root / "result.json"),
            )
            task_path = root / "task.json"
            task.write(task_path)
            result = StageResult("run", "job", "extract", 1, "succeeded", True, (reference,))
            result_path = root / "result.json"
            result.write(result_path)
            StageResult.read(result_path).validate_for(StageTask.read(task_path))

            artifact.write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                StageResult.read(result_path).validate_for(task)

    def test_result_identity_must_match_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            task = StageTask(
                "batch", "run", "job", "https://example.com/job", "extract", 1,
                "extract-job-opening", str(root), str(root / "out"), str(root / "result.json"),
            )
            result = StageResult("other", "job", "extract", 1, "failed", False)
            with self.assertRaisesRegex(ValueError, "does not match"):
                result.validate_for(task, verify_files=False)

    def test_restart_stage_requires_retryable_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            task = StageTask(
                "batch", "run", "job", "https://example.com/job", "review", 1,
                "review-application-bundle", str(root), str(root / "out"), str(root / "result.json"),
            )
            result = StageResult(
                "run", "job", "review", 1, "blocked", True,
                blocker=StageBlocker("revise", "revision needed", False, restart_stage="bundle-writing"),
            )
            with self.assertRaisesRegex(ValueError, "requires a retryable"):
                result.validate_for(task, verify_files=False)

    def test_source_fingerprint_ignores_derived_outputs(self) -> None:
        base = [
            {"name": "source:backend:experience.md", "path": "/d/exp.md", "sha256": "a"},
            {"name": "job.json", "path": "/d/job.json", "sha256": "b"},
        ]
        same_sources = [
            {"name": "job.json", "path": "/d/job.json", "sha256": "CHANGED"},
            {"name": "review.json", "path": "/d/review.json", "sha256": "c"},
            {"name": "source:backend:experience.md", "path": "/d/exp.md", "sha256": "a"},
        ]
        changed_source = [
            {"name": "source:backend:experience.md", "path": "/d/exp.md", "sha256": "ZZZ"},
        ]
        self.assertTrue(is_source_artifact("source:backend:experience.md"))
        self.assertTrue(is_source_artifact("candidate-source:skills.md"))
        self.assertFalse(is_source_artifact("job.json"))
        self.assertEqual(
            fingerprint_artifacts(base, source_only=True),
            fingerprint_artifacts(same_sources, source_only=True),
        )
        self.assertNotEqual(
            fingerprint_artifacts(base, source_only=True),
            fingerprint_artifacts(changed_source, source_only=True),
        )

    def test_worker_extra_args_cannot_override_managed_flags(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot override"):
            WorkerProfile("codex", "test", extra_args=("resume",)).validate()
        with self.assertRaisesRegex(ValueError, "cannot override"):
            WorkerProfile("muse", "test", extra_args=("--workspace",)).validate()
        WorkerProfile("muse", "muse-spark", "low").validate()


if __name__ == "__main__":
    unittest.main()
