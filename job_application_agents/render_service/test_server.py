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
from job_application_agents.render_service.compiler import CompileFailure
from job_application_agents.render_service.firestore import FirestoreRenderJobRepository
from job_application_agents.render_service.models import ArtifactRef, CompileDocument, RenderRequest
from job_application_agents.render_service import server as server_module
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


class DirectCompileEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mock_repo = mock.MagicMock(spec=FirestoreRenderJobRepository)
        cls.mock_artifacts = mock.MagicMock(spec=ArtifactStore)

        RenderHTTPRequestHandler.repository = cls.mock_repo
        RenderHTTPRequestHandler.artifacts = cls.mock_artifacts

        cls.server = HTTPServer(("127.0.0.1", 0), RenderHTTPRequestHandler)
        cls.port = cls.server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def _request_dict(self) -> dict:
        request = RenderRequest(
            request_id=str(uuid4()),
            input_artifact=ArtifactRef(key="objects/abc.tar", sha256="a" * 64, bytes=10),
            documents=(CompileDocument("resume.tex", "resume.pdf"),),
        )
        return request.to_dict()

    def _post(self, payload: bytes) -> tuple[int, dict, dict]:
        url = f"http://127.0.0.1:{self.port}/compile"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req) as response:
                return response.status, json.loads(response.read().decode("utf-8")), dict(response.headers)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                return exc.code, json.loads(body) if body else {}, dict(exc.headers)
            finally:
                exc.close()

    def test_compile_success_returns_result_and_artifact(self) -> None:
        manifest = {"request_id": "rid", "status": "SUCCEEDED"}
        out_ref = ArtifactRef(key="objects/out.tar", sha256="b" * 64, bytes=20)
        self.mock_artifacts.put_directory.return_value = out_ref
        with mock.patch(
            "job_application_agents.render_service.server.compile_request",
            return_value=manifest,
        ) as mock_compile:
            status, data, _headers = self._post(json.dumps({"request": self._request_dict()}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(data["result"], manifest)
        self.assertEqual(data["output_artifact"], out_ref.to_dict())
        mock_compile.assert_called_once()

    def test_compile_missing_request_returns_400(self) -> None:
        status, _, _headers = self._post(json.dumps({}).encode())
        self.assertEqual(status, 400)

    def test_compile_invalid_request_returns_400_with_code(self) -> None:
        bad = self._request_dict()
        bad["documents"] = []
        status, data, _headers = self._post(json.dumps({"request": bad}).encode())
        self.assertEqual(status, 400)
        self.assertEqual(data["error_code"], "INVALID_REQUEST")

    def test_compile_failure_maps_status_but_keeps_code(self) -> None:
        cases = [
            ("INVALID_REQUEST", 400),
            ("MISSING_DEPENDENCY", 422),
            ("TIMEOUT", 504),
            ("COMPILE_ERROR", 500),
        ]
        for code, expected_status in cases:
            with self.subTest(code=code):
                with mock.patch(
                    "job_application_agents.render_service.server.compile_request",
                    side_effect=CompileFailure(code, "detail here"),
                ):
                    status, data, _headers = self._post(
                        json.dumps({"request": self._request_dict()}).encode()
                    )
                self.assertEqual(status, expected_status)
                self.assertEqual(data["error_code"], code)
                self.assertIn("retryable", data)

    def test_compile_saturated_returns_429(self) -> None:
        # Hold the real semaphore so the handler's non-blocking acquire fails.
        # The blocking drain absorbs any still-releasing request from an
        # earlier test instead of racing it; the test fails loudly on timeout
        # rather than flaking.
        acquired = server_module._DIRECT_SEMAPHORE.acquire(blocking=True, timeout=30)
        self.assertTrue(acquired, "timed out waiting for the compile semaphore")
        try:
            status, _, headers = self._post(
                json.dumps({"request": self._request_dict()}).encode()
            )
        finally:
            server_module._DIRECT_SEMAPHORE.release()
        self.assertEqual(status, 429)
        self.assertEqual(headers.get("Retry-After"), "30")

    def test_compile_oversized_body_returns_413(self) -> None:
        payload = json.dumps({"request": self._request_dict(), "pad": "x" * 100}).encode()
        url = f"http://127.0.0.1:{self.port}/compile"
        with mock.patch.object(server_module, "MAX_DIRECT_BODY_BYTES", 10):
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            try:
                with self.opener.open(req) as response:
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
        self.assertEqual(status, 413)


if __name__ == "__main__":
    unittest.main()
