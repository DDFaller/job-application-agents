from __future__ import annotations

from http.server import ThreadingHTTPServer
import io
import json
import shutil
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from uuid import uuid4

from job_application_agents.render_service.artifacts import ArtifactStore
from job_application_agents.render_service.client import (
    RenderJobFailure,
    RenderServiceClient,
    direct_worker_ready,
)
from job_application_agents.render_service import client as client_module
from job_application_agents.render_service.compiler import CompileFailure, compile_request
from job_application_agents.render_service.models import ArtifactRef, CompileDocument, RenderRequest
from job_application_agents.render_service.server import RenderHTTPRequestHandler


TOOLS_AVAILABLE = all(shutil.which(name) for name in ("xelatex", "pdfinfo", "pdftotext"))

ONE_PAGE = "\\documentclass{article}\\begin{document}Direct check.\\end{document}"
TWO_PAGES = (
    "\\documentclass{article}\\begin{document}Page one."
    "\\newpage Page two.\\end{document}"
)
WHITESPACE_ONLY = "\\documentclass{article}\\begin{document} \n\t \n\\end{document}"


def _engine_request(documents: tuple[CompileDocument, ...]) -> RenderRequest:
    return RenderRequest(
        request_id=str(uuid4()),
        input_artifact=ArtifactRef("objects/input.tar", "a" * 64, 1),
        documents=documents,
    )


@unittest.skipUnless(TOOLS_AVAILABLE, "local XeLaTeX tools are unavailable")
class DirectEngineEdgeTests(unittest.TestCase):
    """Edge cases against the real compile engine (no mocks)."""

    def _compile(self, filename: str, content: bytes | str, documents: tuple[CompileDocument, ...]) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "output"
            source.mkdir()
            if isinstance(content, bytes):
                (source / filename).write_bytes(content)
            else:
                (source / filename).write_text(content, encoding="utf-8")
            return compile_request(_engine_request(documents), source, output)

    def test_multipage_document_over_max_pages_raises_quality_error(self) -> None:
        with self.assertRaises(CompileFailure) as ctx:
            self._compile(
                "resume.tex", TWO_PAGES,
                (CompileDocument("resume.tex", "resume.pdf", passes=1, max_pages=1),),
            )
        self.assertEqual(ctx.exception.code, "QUALITY_ERROR")
        self.assertIn("rendered 2", str(ctx.exception))

    def test_multipage_document_within_max_pages_succeeds(self) -> None:
        result = self._compile(
            "resume.tex", TWO_PAGES,
            (CompileDocument("resume.tex", "resume.pdf", passes=1, max_pages=2),),
        )
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["documents"]["resume.pdf"]["pages"], 2)

    def test_empty_tex_source_raises_compile_error(self) -> None:
        with self.assertRaises(CompileFailure) as ctx:
            self._compile(
                "resume.tex", b"",
                (CompileDocument("resume.tex", "resume.pdf", passes=1),),
            )
        self.assertEqual(ctx.exception.code, "COMPILE_ERROR")

    def test_whitespace_only_document_raises_compile_error(self) -> None:
        # No pages of output: the TeX engine itself fails, so this is a
        # compile error rather than a quality-gate rejection.
        with self.assertRaises(CompileFailure) as ctx:
            self._compile(
                "resume.tex", WHITESPACE_ONLY,
                (CompileDocument("resume.tex", "resume.pdf", passes=1),),
            )
        self.assertEqual(ctx.exception.code, "COMPILE_ERROR")

    def test_empty_documents_rejected_by_model(self) -> None:
        with self.assertRaises(ValueError):
            _engine_request(())


@unittest.skipUnless(TOOLS_AVAILABLE, "local XeLaTeX tools are unavailable")
class DirectEndToEndTests(unittest.TestCase):
    """Full path: real HTTP server + real store + real engine, no Firestore."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="direct-e2e-")
        cls.store = ArtifactStore(Path(cls._temporary.name) / "artifacts")
        RenderHTTPRequestHandler.repository = mock.MagicMock()
        RenderHTTPRequestHandler.artifacts = cls.store
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RenderHTTPRequestHandler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.client = RenderServiceClient(None, cls.store)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls._temporary.cleanup()

    def _compile_source(self, filename: str, content: str | bytes, output_name: str,
                        max_pages: int = 1) -> tuple[Path, Path]:
        case = Path(tempfile.mkdtemp(prefix="direct-case-"))
        source = case / "source"
        source.mkdir()
        if isinstance(content, bytes):
            (source / filename).write_bytes(content)
        else:
            (source / filename).write_text(content, encoding="utf-8")
        return source, case / "output"

    def test_end_to_end_success_returns_verified_pdf(self) -> None:
        source, output = self._compile_source("resume.tex", ONE_PAGE, "resume.pdf")
        self.addCleanup(shutil.rmtree, source.parent, True)
        result = self.client.compile_direct(
            self.base_url, source,
            (CompileDocument("resume.tex", "resume.pdf", passes=1),),
            output, request_id=str(uuid4()), timeout_seconds=120,
        )
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertTrue((output / "resume.pdf").is_file())
        self.assertTrue((output / "result.json").is_file())
        self.assertEqual(json.loads((output / "result.json").read_text()), result)

    def test_end_to_end_multipage_returns_quality_error_code(self) -> None:
        source, output = self._compile_source("resume.tex", TWO_PAGES, "resume.pdf")
        self.addCleanup(shutil.rmtree, source.parent, True)
        with self.assertRaises(RenderJobFailure) as ctx:
            self.client.compile_direct(
                self.base_url, source,
                (CompileDocument("resume.tex", "resume.pdf", passes=1, max_pages=1),),
                output, request_id=str(uuid4()), timeout_seconds=120,
            )
        self.assertEqual(ctx.exception.code, "QUALITY_ERROR")

    def test_end_to_end_empty_tex_returns_compile_error_code(self) -> None:
        source, output = self._compile_source("resume.tex", b"", "resume.pdf")
        self.addCleanup(shutil.rmtree, source.parent, True)
        with self.assertRaises(RenderJobFailure) as ctx:
            self.client.compile_direct(
                self.base_url, source,
                (CompileDocument("resume.tex", "resume.pdf", passes=1),),
                output, request_id=str(uuid4()), timeout_seconds=120,
            )
        self.assertEqual(ctx.exception.code, "COMPILE_ERROR")


class DirectClientUnitTests(unittest.TestCase):
    """Client mapping without any network: mocked HTTP, real artifact store."""

    def _client_with_output(self, manifest: dict) -> tuple[RenderServiceClient, dict]:
        temporary = tempfile.TemporaryDirectory(prefix="direct-client-")
        self.addCleanup(temporary.cleanup)
        store = ArtifactStore(Path(temporary.name) / "artifacts")
        outdir = Path(temporary.name) / "out"
        outdir.mkdir()
        (outdir / "result.json").write_text(json.dumps(manifest), encoding="utf-8")
        (outdir / "resume.pdf").write_bytes(b"%PDF-1.4 fake\n")
        return RenderServiceClient(None, store), store.put_directory(outdir).to_dict()

    @staticmethod
    def _fake_response(status: int, payload: dict):
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        return response

    def test_success_collects_and_verifies_result(self) -> None:
        request_id = str(uuid4())
        manifest = {"request_id": request_id, "status": "SUCCEEDED"}
        client, out_ref = self._client_with_output(manifest)
        fake = self._fake_response(200, {"result": manifest, "output_artifact": out_ref})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "resume.tex").write_text(ONE_PAGE, encoding="utf-8")
            with mock.patch.object(client_module, "_direct_opener") as opener:
                opener.open.return_value.__enter__.return_value = fake
                result = client.compile_direct(
                    "http://worker:8000", root / "src",
                    (CompileDocument("resume.tex", "resume.pdf"),),
                    root / "out", request_id=request_id,
                )
                self.assertEqual(result, manifest)
                self.assertTrue((root / "out" / "resume.pdf").is_file())

    def test_result_mismatch_raises_runtime_error(self) -> None:
        manifest = {"request_id": "someone-else", "status": "SUCCEEDED"}
        client, out_ref = self._client_with_output(manifest)
        fake = self._fake_response(200, {"result": manifest, "output_artifact": out_ref})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "resume.tex").write_text(ONE_PAGE, encoding="utf-8")
            with mock.patch.object(client_module, "_direct_opener") as opener:
                opener.open.return_value.__enter__.return_value = fake
                with self.assertRaises(RuntimeError):
                    client.compile_direct(
                        "http://worker:8000", root / "src",
                        (CompileDocument("resume.tex", "resume.pdf"),),
                        root / "out", request_id=str(uuid4()),
                    )

    def test_rate_limited_maps_to_worker_busy(self) -> None:
        client, _ = self._client_with_output({"request_id": "x"})
        error = urllib.error.HTTPError(
            "http://worker:8000/compile", 429, "Too Many Requests", {"Retry-After": "30"},
            io.BytesIO(b"{}"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "resume.tex").write_text(ONE_PAGE, encoding="utf-8")
            with mock.patch.object(client_module, "_direct_opener") as opener:
                opener.open.side_effect = error
                with self.assertRaises(RenderJobFailure) as ctx:
                    client.compile_direct(
                        "http://worker:8000", root / "src",
                        (CompileDocument("resume.tex", "resume.pdf"),),
                        root / "out",
                    )
        self.assertEqual(ctx.exception.code, "WORKER_BUSY")

    def test_engine_error_code_passes_through(self) -> None:
        client, _ = self._client_with_output({"request_id": "x"})
        body = {"error_code": "COMPILE_ERROR", "error_detail": "boom", "retryable": False}
        error = urllib.error.HTTPError(
            "http://worker:8000/compile", 500, "Internal Error", {},
            io.BytesIO(json.dumps(body).encode()),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "resume.tex").write_text(ONE_PAGE, encoding="utf-8")
            with mock.patch.object(client_module, "_direct_opener") as opener:
                opener.open.side_effect = error
                with self.assertRaises(RenderJobFailure) as ctx:
                    client.compile_direct(
                        "http://worker:8000", root / "src",
                        (CompileDocument("resume.tex", "resume.pdf"),),
                        root / "out",
                    )
        self.assertEqual(ctx.exception.code, "COMPILE_ERROR")

    def test_unreachable_worker_maps_to_direct_unavailable(self) -> None:
        client, _ = self._client_with_output({"request_id": "x"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "resume.tex").write_text(ONE_PAGE, encoding="utf-8")
            with mock.patch.object(client_module, "_direct_opener") as opener:
                opener.open.side_effect = urllib.error.URLError("refused")
                with self.assertRaises(RenderJobFailure) as ctx:
                    client.compile_direct(
                        "http://worker:8000", root / "src",
                        (CompileDocument("resume.tex", "resume.pdf"),),
                        root / "out",
                    )
        self.assertEqual(ctx.exception.code, "DIRECT_UNAVAILABLE")

    def test_health_probe_ready_and_degraded(self) -> None:
        ready = self._fake_response(200, {
            "status": "READY",
            "capabilities": {"xelatex": True, "pdfinfo": True, "pdftotext": True},
        })
        degraded = self._fake_response(200, {
            "status": "DEGRADED",
            "capabilities": {"xelatex": True, "pdfinfo": False, "pdftotext": True},
        })
        with mock.patch.object(client_module, "_direct_opener") as opener:
            opener.open.return_value.__enter__.return_value = ready
            self.assertTrue(direct_worker_ready("http://worker:8000"))
            opener.open.return_value.__enter__.return_value = degraded
            self.assertFalse(direct_worker_ready("http://worker:8000"))
            opener.open.side_effect = urllib.error.URLError("refused")
            self.assertFalse(direct_worker_ready("http://worker:8000"))


class CompileWithFallbackTests(unittest.TestCase):
    """Direct-first with queue fallback (no tools required)."""

    def _client(self):
        store = mock.Mock()
        repo = mock.Mock()
        return RenderServiceClient(repo, store)

    def test_direct_path_wins_when_ready(self) -> None:
        client = self._client()
        with mock.patch.object(client_module, "direct_worker_ready", return_value=True), \
                mock.patch.object(client, "compile_direct", return_value={"ok": True}) as direct, \
                mock.patch.object(client, "compile_and_wait") as queued:
            result, path = client.compile_with_fallback(
                "http://worker:8000", Path("/src"), (), Path("/dst"),
                idempotency_key="k",
            )
        self.assertEqual((result, path), ({"ok": True}, "direct"))
        direct.assert_called_once()
        queued.assert_not_called()

    def test_queue_fallback_on_unreachable_direct(self) -> None:
        client = self._client()
        with mock.patch.object(client_module, "direct_worker_ready", return_value=True), \
                mock.patch.object(
                    client, "compile_direct",
                    side_effect=RenderJobFailure("DIRECT_UNAVAILABLE", "down"),
                ), \
                mock.patch.object(client, "compile_and_wait", return_value={"ok": True}) as queued:
            result, path = client.compile_with_fallback(
                "http://worker:8000", Path("/src"), (), Path("/dst"),
                idempotency_key="k",
            )
        self.assertEqual((result, path), ({"ok": True}, "queue"))
        queued.assert_called_once()

    def test_queue_used_when_no_direct_url(self) -> None:
        client = self._client()
        with mock.patch.object(client, "compile_and_wait", return_value={"ok": True}) as queued:
            _, path = client.compile_with_fallback(
                None, Path("/src"), (), Path("/dst"), idempotency_key="k",
            )
        self.assertEqual(path, "queue")
        queued.assert_called_once()

    def test_compile_errors_are_not_swallowed(self) -> None:
        client = self._client()
        with mock.patch.object(client_module, "direct_worker_ready", return_value=True), \
                mock.patch.object(
                    client, "compile_direct",
                    side_effect=RenderJobFailure("COMPILE_ERROR", "bad tex"),
                ), \
                mock.patch.object(client, "compile_and_wait") as queued:
            with self.assertRaises(RenderJobFailure):
                client.compile_with_fallback(
                    "http://worker:8000", Path("/src"), (), Path("/dst"),
                    idempotency_key="k",
                )
        queued.assert_not_called()


if __name__ == "__main__":
    unittest.main()
