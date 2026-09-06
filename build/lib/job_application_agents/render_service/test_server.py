from __future__ import annotations

from http.server import HTTPServer
import json
from pathlib import Path
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from uuid import uuid4

from job_application_agents.render_service.artifacts import ArtifactStore
from job_application_agents.render_service.firestore import FirestoreRenderJobRepository
from job_application_agents.render_service.server import RenderHTTPRequestHandler


class ServerUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mock_repo = mock.MagicMock(spec=FirestoreRenderJobRepository)
        cls.mock_artifacts = mock.MagicMock(spec=ArtifactStore)

        RenderHTTPRequestHandler.repository = cls.mock_repo
        RenderHTTPRequestHandler.artifacts = cls.mock_artifacts

        # Bind to localhost port 0 (ephemeral free port)
        cls.server = HTTPServer(("127.0.0.1", 0), RenderHTTPRequestHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        # Build opener that does not route through environment HTTP_PROXY
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    @mock.patch("job_application_agents.render_service.server.capabilities")
    def test_healthz_endpoint_returns_200(self, mock_caps: mock.MagicMock) -> None:
        mock_caps.return_value = {"xelatex": True, "pdfinfo": True, "pdftotext": True}
        url = f"http://127.0.0.1:{self.port}/healthz"
        with self.opener.open(url) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["status"], "READY")
            self.assertTrue(data["capabilities"]["xelatex"])

    def test_root_endpoint_returns_200(self) -> None:
        url = f"http://127.0.0.1:{self.port}/"
        with self.opener.open(url) as response:
            self.assertEqual(response.status, 200)

    def test_unknown_endpoint_returns_404(self) -> None:
        url = f"http://127.0.0.1:{self.port}/unknown-path"
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self.opener.open(url)
        self.assertEqual(exc_info.exception.code, 404)

    def test_process_job_post_endpoint(self) -> None:
        url = f"http://127.0.0.1:{self.port}/process-job"
        payload = json.dumps({"job_id": "test-job-123"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

        mock_job = mock.MagicMock()
        mock_job.id = "test-job-123"
        self.mock_repo.get.return_value = mock_job

        with mock.patch("job_application_agents.render_service.server.Worker") as mock_worker_cls:
            mock_worker_instance = mock_worker_cls.return_value
            mock_worker_instance.process.return_value = None

            with self.opener.open(req) as response:
                self.assertEqual(response.status, 200)
                data = json.loads(response.read().decode("utf-8"))
                self.assertEqual(data["job_id"], "test-job-123")
                self.assertTrue(data["processed"])


if __name__ == "__main__":
    unittest.main()
