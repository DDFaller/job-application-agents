from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest import mock
from uuid import UUID, uuid4

from job_application_agents.render_service.firestore import (
    FirestoreRenderJobRepository, JOB_COLLECTION, WORKER_COLLECTION,
)
from job_application_agents.render_service.models import ArtifactRef, CompileDocument, RenderRequest


class FirestoreUnitTests(unittest.TestCase):
    """Unit tests for Firestore queue logic that do not require an active emulator."""

    def test_job_id_for_key_is_deterministic(self) -> None:
        key = "test-job-key-12345"
        first = FirestoreRenderJobRepository.job_id_for_key(key)
        second = FirestoreRenderJobRepository.job_id_for_key(key)
        self.assertEqual(first, second)
        self.assertEqual(UUID(first).version, 5)

    def test_job_id_for_key_rejects_empty_and_oversized_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "1-200 characters"):
            FirestoreRenderJobRepository.job_id_for_key("")
        with self.assertRaisesRegex(ValueError, "1-200 characters"):
            FirestoreRenderJobRepository.job_id_for_key("a" * 201)

    def test_init_requires_non_empty_project_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "Firebase project ID is required"):
            FirestoreRenderJobRepository("")

    def test_job_parsing_from_valid_snapshot(self) -> None:
        mock_snapshot = mock.MagicMock()
        mock_snapshot.id = str(uuid4())
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            "state": "QUEUED",
            "request": {
                "schema_version": 1,
                "request_id": str(uuid4()),
                "input_artifact": {"key": "objects/in.tar", "sha256": "a" * 64, "bytes": 100},
                "documents": [{"source": "resume.tex", "output": "resume.pdf"}],
                "required_packages": ["geometry.sty"],
                "required_fonts": [],
                "timeout_seconds": 300,
            },
            "attempts": 1,
            "max_attempts": 3,
            "output_artifact": {"key": "objects/out.tar", "sha256": "b" * 64, "bytes": 200},
            "result": {"status": "SUCCEEDED"},
            "error_code": None,
            "error_detail": None,
            "created_at": datetime.now(timezone.utc),
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
        }
        job = FirestoreRenderJobRepository._job(mock_snapshot)
        self.assertEqual(job.id, mock_snapshot.id)
        self.assertEqual(job.state, "QUEUED")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.max_attempts, 3)
        self.assertIsNotNone(job.output_artifact)
        self.assertEqual(job.output_artifact.sha256, "b" * 64)
        self.assertEqual(job.result, {"status": "SUCCEEDED"})

    def test_job_parsing_nonexistent_snapshot_raises_key_error(self) -> None:
        mock_snapshot = mock.MagicMock()
        mock_snapshot.id = "nonexistent-job-id"
        mock_snapshot.exists = False
        with self.assertRaisesRegex(KeyError, "unknown render job"):
            FirestoreRenderJobRepository._job(mock_snapshot)

    def test_client_emulator_mode_uses_anonymous_credentials(self) -> None:
        with mock.patch.dict(os.environ, {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"}):
            mock_google = mock.MagicMock()
            mock_client_cls = mock.MagicMock()
            mock_google.cloud.firestore.Client = mock_client_cls
            with mock.patch.dict("sys.modules", {
                "google": mock_google,
                "google.auth": mock.MagicMock(),
                "google.auth.credentials": mock.MagicMock(),
                "google.cloud": mock_google.cloud,
                "google.cloud.firestore": mock_google.cloud.firestore,
            }):
                FirestoreRenderJobRepository._client("demo-project")
                mock_client_cls.assert_called_once()
                _, kwargs = mock_client_cls.call_args
                self.assertEqual(kwargs.get("project"), "demo-project")


@unittest.skipUnless(os.environ.get("FIRESTORE_EMULATOR_HOST"), "Firestore emulator is unavailable")
class FirestoreRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = FirestoreRenderJobRepository("demo-job-application-agents")

    def setUp(self) -> None:
        self.documents: list[tuple[str, str]] = []

    def tearDown(self) -> None:
        for collection, document in self.documents:
            self.repository.client.collection(collection).document(document).delete()

    def request(self) -> RenderRequest:
        return RenderRequest(
            request_id=str(uuid4()),
            input_artifact=ArtifactRef("objects/input.tar", "a" * 64, 10),
            documents=(CompileDocument("resume.tex", "resume.pdf"),),
        )

    def enqueue(self):
        key = f"test:{uuid4()}"
        job = self.repository.enqueue(self.request(), key)
        self.documents.append((JOB_COLLECTION, job.id))
        return key, job

    def test_enqueue_is_idempotent(self) -> None:
        key, first = self.enqueue()
        second = self.repository.enqueue(self.request(), key)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.request, second.request)

    def test_two_workers_cannot_claim_the_same_job(self) -> None:
        _, job = self.enqueue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(self.repository.claim, ("worker-a", "worker-b")))
        claimed = [candidate for candidate in claims if candidate is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].id, job.id)

    def test_lease_owner_controls_heartbeat_and_success(self) -> None:
        _, queued = self.enqueue()
        claimed = self.repository.claim("owner")
        self.assertEqual(claimed.id, queued.id)
        self.assertFalse(self.repository.heartbeat(queued.id, "intruder"))
        self.assertTrue(self.repository.heartbeat(queued.id, "owner"))
        with self.assertRaisesRegex(RuntimeError, "lease was lost"):
            self.repository.succeed(
                queued.id, "intruder", ArtifactRef("objects/out.tar", "b" * 64, 20), {}
            )

    def test_retry_and_terminal_failure(self) -> None:
        _, job = self.enqueue()
        for attempt in range(1, 4):
            claimed = self.repository.claim("worker")
            self.assertIsNotNone(claimed)
            self.repository.fail(job.id, "worker", "INFRASTRUCTURE_ERROR", "temporary", True)
            state = self.repository.get(job.id)
            self.assertEqual(state.attempts, attempt)
            self.assertEqual(state.state, "QUEUED" if attempt < 3 else "FAILED")

    def test_non_retryable_failure_transitions_to_failed_immediately(self) -> None:
        _, job = self.enqueue()
        claimed = self.repository.claim("worker")
        self.assertIsNotNone(claimed)
        self.repository.fail(job.id, "worker", "COMPILE_ERROR", "permanent syntax error", False)
        state = self.repository.get(job.id)
        self.assertEqual(state.attempts, 1)
        self.assertEqual(state.state, "FAILED")
        self.assertEqual(state.error_code, "COMPILE_ERROR")
        self.assertEqual(state.error_detail, "permanent syntax error")

    def test_expired_lease_is_requeued(self) -> None:
        _, job = self.enqueue()
        self.repository.claim("lost-worker")
        self.repository.client.collection(JOB_COLLECTION).document(job.id).update({
            "lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        })
        self.assertEqual(self.repository.requeue_expired(), 1)
        recovered = self.repository.get(job.id)
        self.assertEqual(recovered.state, "QUEUED")
        self.assertEqual(recovered.error_code, "WORKER_LOST")

    def test_expired_lease_fails_after_max_attempts(self) -> None:
        _, job = self.enqueue()
        for _ in range(3):
            self.repository.claim("lost-worker")
            self.repository.client.collection(JOB_COLLECTION).document(job.id).update({
                "lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            })
            self.repository.requeue_expired()
        final_state = self.repository.get(job.id)
        self.assertEqual(final_state.state, "FAILED")
        self.assertEqual(final_state.error_code, "WORKER_LOST")

    def test_recent_compatible_worker_is_ready(self) -> None:
        worker_id = f"test-worker-{uuid4()}"
        self.documents.append((WORKER_COLLECTION, worker_id))
        self.repository.register_worker(worker_id, "test", {
            "xelatex": True, "pdfinfo": True, "pdftotext": True,
        })
        self.assertTrue(self.repository.worker_ready())

    def test_worker_ready_returns_false_when_missing_capabilities(self) -> None:
        worker_id = f"test-worker-{uuid4()}"
        self.documents.append((WORKER_COLLECTION, worker_id))
        self.repository.register_worker(worker_id, "test", {
            "xelatex": True, "pdfinfo": False, "pdftotext": True,
        })
        self.assertFalse(self.repository.worker_ready())


if __name__ == "__main__":
    unittest.main()
