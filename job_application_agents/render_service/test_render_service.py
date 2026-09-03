from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
from uuid import UUID, uuid4

from job_application_agents.render_service.artifacts import ArtifactStore
from job_application_agents.render_service.client import (
    RenderJobFailure, RenderServiceClient, deterministic_key,
)
from job_application_agents.render_service.compiler import (
    CompileFailure, compile_request, run, tool_version,
)
from job_application_agents.render_service.config import artifact_root, firebase_project_id
from job_application_agents.render_service.models import (
    ArtifactRef, CompileDocument, RenderJob, RenderRequest, safe_relative_name,
)
from job_application_agents.render_service.worker import Worker, capabilities


class ModelTests(unittest.TestCase):
    def test_request_round_trip(self) -> None:
        request = RenderRequest(
            request_id=str(uuid4()),
            input_artifact=ArtifactRef("objects/a.tar", "a" * 64, 10),
            documents=(CompileDocument("resume.tex", "resume.pdf", extract_raw_text=True),),
        )
        self.assertEqual(RenderRequest.from_dict(request.to_dict()), request)

    def test_safe_relative_name_accepts_valid_paths(self) -> None:
        self.assertEqual(safe_relative_name("resume.tex", "source"), "resume.tex")
        self.assertEqual(safe_relative_name("sub/dir/resume.tex", "source"), "sub/dir/resume.tex")

    def test_safe_relative_name_rejects_empty_or_absolute_or_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "safe POSIX relative path"):
            safe_relative_name("", "source")
        with self.assertRaisesRegex(ValueError, "safe POSIX relative path"):
            safe_relative_name("/etc/passwd", "source")
        with self.assertRaisesRegex(ValueError, "safe POSIX relative path"):
            safe_relative_name("../escape.tex", "source")

    def test_artifact_ref_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid artifact reference"):
            ArtifactRef.from_dict({"key": "objects/a.tar", "sha256": "short", "bytes": 10})
        with self.assertRaisesRegex(ValueError, "invalid artifact reference"):
            ArtifactRef.from_dict({"key": "objects/a.tar", "sha256": "a" * 64, "bytes": -1})

    def test_compile_document_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "compile documents require .tex sources and .pdf outputs"):
            CompileDocument("resume.txt", "resume.pdf")
        with self.assertRaisesRegex(ValueError, "compile documents require .tex sources and .pdf outputs"):
            CompileDocument("resume.tex", "resume.docx")
        with self.assertRaisesRegex(ValueError, "passes must be between 1 and 3"):
            CompileDocument("resume.tex", "resume.pdf", passes=4)
        with self.assertRaisesRegex(ValueError, "max_pages must be between 1 and 10"):
            CompileDocument("resume.tex", "resume.pdf", max_pages=0)

    def test_render_request_validation(self) -> None:
        ref = ArtifactRef("objects/a.tar", "a" * 64, 10)
        doc = CompileDocument("resume.tex", "resume.pdf")
        with self.assertRaises(ValueError):
            RenderRequest(request_id="invalid-uuid", input_artifact=ref, documents=(doc,))
        with self.assertRaisesRegex(ValueError, "render request must contain 1-10 documents"):
            RenderRequest(request_id=str(uuid4()), input_artifact=ref, documents=())
        with self.assertRaisesRegex(ValueError, "required packages must be .sty filenames"):
            RenderRequest(request_id=str(uuid4()), input_artifact=ref, documents=(doc,), required_packages=("bad/pkg.sty",))
        with self.assertRaisesRegex(ValueError, "required packages must be .sty filenames"):
            RenderRequest(request_id=str(uuid4()), input_artifact=ref, documents=(doc,), required_packages=("geometry",))
        with self.assertRaisesRegex(ValueError, "required fonts must be non-empty"):
            RenderRequest(request_id=str(uuid4()), input_artifact=ref, documents=(doc,), required_fonts=("",))
        with self.assertRaisesRegex(ValueError, "document outputs must be unique"):
            RenderRequest(request_id=str(uuid4()), input_artifact=ref, documents=(doc, doc))
        with self.assertRaisesRegex(ValueError, "timeout_seconds must be between 30 and 600"):
            RenderRequest(request_id=str(uuid4()), input_artifact=ref, documents=(doc,), timeout_seconds=10)

    def test_render_job_validation(self) -> None:
        ref = ArtifactRef("objects/a.tar", "a" * 64, 10)
        req = RenderRequest(request_id=str(uuid4()), input_artifact=ref, documents=(CompileDocument("resume.tex", "resume.pdf"),))
        with self.assertRaises(ValueError):
            RenderJob(id="not-uuid", state="QUEUED", request=req, attempts=0, max_attempts=3)
        with self.assertRaisesRegex(ValueError, "invalid render job state"):
            RenderJob(id=str(uuid4()), state="INVALID_STATE", request=req, attempts=0, max_attempts=3)


class ArtifactStoreTests(unittest.TestCase):
    def test_directory_round_trip_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "resume.tex").write_text("hello", encoding="utf-8")
            store = ArtifactStore(root / "store")
            first = store.put_directory(source)
            second = store.put_directory(source)
            self.assertEqual(first, second)
            output = root / "output"
            store.extract(first, output)
            self.assertEqual((output / "resume.tex").read_text(), "hello")

    def test_extract_rejects_traversal_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store")
            archive = store.objects / "bad.tar"
            with tarfile.open(archive, "w") as handle:
                value = b"bad"
                info = tarfile.TarInfo("../escape")
                info.size = len(value)
                handle.addfile(info, io.BytesIO(value))
            ref = ArtifactRef(
                key="objects/bad.tar", sha256=store.sha256(archive), bytes=archive.stat().st_size
            )
            with self.assertRaisesRegex(ValueError, "unsafe path"):
                store.extract(ref, root / "output")

    def test_put_directory_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "real.txt").write_text("real")
            (source / "link.txt").symlink_to(source / "real.txt")
            store = ArtifactStore(root / "store")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                store.put_directory(source)

    def test_verify_missing_artifact_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ArtifactStore(Path(temporary) / "store")
            ref = ArtifactRef("objects/missing.tar", "0" * 64, 100)
            with self.assertRaisesRegex(ValueError, "missing or corrupt"):
                store.verify(ref)

    def test_path_escaping_store_root_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ArtifactStore(Path(temporary) / "store")
            ref = ArtifactRef("../../etc/passwd", "0" * 64, 100)
            with self.assertRaisesRegex(ValueError, "escapes store root"):
                store.verify(ref)


class CompilerTests(unittest.TestCase):
    @unittest.skipUnless(
        all(shutil.which(name) for name in ("xelatex", "pdfinfo", "pdftotext")),
        "local XeLaTeX tools are unavailable",
    )
    def test_compile_only_contract_produces_pdf_text_and_manifest(self) -> None:
        document = "\\documentclass{article}\\begin{document}Worker check.\\end{document}"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "output"
            source.mkdir()
            (source / "resume.tex").write_text(document, encoding="utf-8")
            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=ArtifactRef("objects/input.tar", "a" * 64, 1),
                documents=(CompileDocument("resume.tex", "resume.pdf", extract_raw_text=True),),
            )
            result = compile_request(request, source, output)
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result["documents"]["resume.pdf"]["pages"], 1)
            self.assertTrue((output / "resume.pdf").is_file())
            self.assertTrue((output / "resume.raw.txt").is_file())
            self.assertEqual(json.loads((output / "result.json").read_text()), result)

    def test_missing_tools_raises_infrastructure_error(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=ArtifactRef("objects/input.tar", "a" * 64, 1),
                documents=(CompileDocument("resume.tex", "resume.pdf"),),
            )
            with self.assertRaises(CompileFailure) as ctx:
                compile_request(request, Path("/tmp"), Path("/tmp/out"))
            self.assertEqual(ctx.exception.code, "INFRASTRUCTURE_ERROR")
            self.assertTrue(ctx.exception.retryable)

    def test_missing_source_tex_raises_invalid_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "output"
            source.mkdir()
            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=ArtifactRef("objects/input.tar", "a" * 64, 1),
                documents=(CompileDocument("nonexistent.tex", "resume.pdf"),),
            )
            with mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"):
                with self.assertRaises(CompileFailure) as ctx:
                    compile_request(request, source, output)
                self.assertEqual(ctx.exception.code, "INVALID_REQUEST")

    def test_missing_package_dependency_raises_missing_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "output"
            source.mkdir()
            (source / "resume.tex").write_text("dummy")
            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=ArtifactRef("objects/input.tar", "a" * 64, 1),
                documents=(CompileDocument("resume.tex", "resume.pdf"),),
                required_packages=("missing-package.sty",),
            )
            with mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess([], returncode=1, stdout="", stderr="")
                    with self.assertRaises(CompileFailure) as ctx:
                        compile_request(request, source, output)
                    self.assertEqual(ctx.exception.code, "MISSING_DEPENDENCY")
                    self.assertIn("missing-package.sty", str(ctx.exception))

    def test_xelatex_compilation_failure_raises_compile_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "output"
            source.mkdir()
            (source / "resume.tex").write_text("invalid tex")
            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=ArtifactRef("objects/input.tar", "a" * 64, 1),
                documents=(CompileDocument("resume.tex", "resume.pdf"),),
            )
            with mock.patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}"):
                with mock.patch("job_application_agents.render_service.compiler.run") as mock_run:
                    mock_run.return_value = subprocess.CompletedProcess(
                        [], returncode=1, stdout="! Undefined control sequence", stderr=""
                    )
                    with self.assertRaises(CompileFailure) as ctx:
                        compile_request(request, source, output)
                    self.assertEqual(ctx.exception.code, "COMPILE_ERROR")

    def test_run_timeout_raises_timeout_failure(self) -> None:
        with self.assertRaises(CompileFailure) as ctx:
            run(["sleep", "10"], Path("."), deadline=0.0)
        self.assertEqual(ctx.exception.code, "TIMEOUT")

    def test_tool_version_helper(self) -> None:
        version = tool_version(["python3", "--version"])
        self.assertTrue(version.startswith("Python") or version != "unknown")


class WorkerTests(unittest.TestCase):
    def test_capabilities(self) -> None:
        caps = capabilities()
        self.assertIn("xelatex", caps)
        self.assertIn("pdfinfo", caps)
        self.assertIn("pdftotext", caps)
        self.assertIsInstance(caps["xelatex"], bool)

    def test_worker_process_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store")
            source_dir = root / "source"
            source_dir.mkdir()
            (source_dir / "resume.tex").write_text("content")
            input_ref = store.put_directory(source_dir)

            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=input_ref,
                documents=(CompileDocument("resume.tex", "resume.pdf"),),
            )
            job = RenderJob(id=str(uuid4()), state="RUNNING", request=request, attempts=1, max_attempts=3)
            mock_repo = mock.MagicMock()
            worker = Worker(mock_repo, store, "worker-test-1")

            fake_result = {"status": "SUCCEEDED", "documents": {"resume.pdf": {"pages": 1}}}
            def fake_compile(_req, _src, out):
                (out / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
                (out / "result.json").write_text(json.dumps(fake_result))
                return fake_result

            with mock.patch("job_application_agents.render_service.worker.compile_request", side_effect=fake_compile):
                worker.process(job)

            mock_repo.succeed.assert_called_once()
            call_args = mock_repo.succeed.call_args[0]
            self.assertEqual(call_args[0], job.id)
            self.assertEqual(call_args[1], "worker-test-1")
            self.assertIsInstance(call_args[2], ArtifactRef)
            self.assertEqual(call_args[3], fake_result)
            self.assertIsNone(worker.current_job)

    def test_worker_process_compile_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store")
            source_dir = root / "source"
            source_dir.mkdir()
            (source_dir / "resume.tex").write_text("content")
            input_ref = store.put_directory(source_dir)

            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=input_ref,
                documents=(CompileDocument("resume.tex", "resume.pdf"),),
            )
            job = RenderJob(id=str(uuid4()), state="RUNNING", request=request, attempts=1, max_attempts=3)
            mock_repo = mock.MagicMock()
            worker = Worker(mock_repo, store, "worker-test-2")

            with mock.patch(
                "job_application_agents.render_service.worker.compile_request",
                side_effect=CompileFailure("COMPILE_ERROR", "TeX syntax error", retryable=False),
            ):
                worker.process(job)

            mock_repo.fail.assert_called_once_with(
                job.id, "worker-test-2", "COMPILE_ERROR", "TeX syntax error", False
            )
            self.assertIsNone(worker.current_job)

    def test_worker_process_infrastructure_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root / "store")
            source_dir = root / "source"
            source_dir.mkdir()
            (source_dir / "resume.tex").write_text("content")
            input_ref = store.put_directory(source_dir)

            request = RenderRequest(
                request_id=str(uuid4()),
                input_artifact=input_ref,
                documents=(CompileDocument("resume.tex", "resume.pdf"),),
            )
            job = RenderJob(id=str(uuid4()), state="RUNNING", request=request, attempts=1, max_attempts=3)
            mock_repo = mock.MagicMock()
            worker = Worker(mock_repo, store, "worker-test-3")

            with mock.patch(
                "job_application_agents.render_service.worker.compile_request",
                side_effect=OSError("disk read error"),
            ):
                worker.process(job)

            mock_repo.fail.assert_called_once_with(
                job.id, "worker-test-3", "INFRASTRUCTURE_ERROR", "disk read error", True
            )
            self.assertIsNone(worker.current_job)

    def test_worker_run_once_processes_claimed_job(self) -> None:
        mock_repo = mock.MagicMock()
        mock_store = mock.MagicMock()
        job = RenderJob(
            id=str(uuid4()), state="RUNNING",
            request=RenderRequest(
                request_id=str(uuid4()),
                input_artifact=ArtifactRef("objects/a.tar", "a" * 64, 1),
                documents=(CompileDocument("resume.tex", "resume.pdf"),),
            ),
            attempts=1, max_attempts=3,
        )
        mock_repo.claim.return_value = job
        worker = Worker(mock_repo, mock_store, "worker-test-run")

        with mock.patch("job_application_agents.render_service.worker.capabilities", return_value={"xelatex": True, "pdfinfo": True, "pdftotext": True}):
            with mock.patch.object(worker, "process") as mock_process:
                worker.run(once=True)
                mock_repo.register_worker.assert_called()
                mock_repo.claim.assert_called_once_with("worker-test-run")
                mock_process.assert_called_once_with(job)

    def test_worker_run_raises_when_capabilities_missing(self) -> None:
        mock_repo = mock.MagicMock()
        mock_store = mock.MagicMock()
        worker = Worker(mock_repo, mock_store, "worker-test-missing")
        with mock.patch("job_application_agents.render_service.worker.capabilities", return_value={"xelatex": False, "pdfinfo": True, "pdftotext": True}):
            with self.assertRaisesRegex(RuntimeError, "missing required rendering tools"):
                worker.run(once=True)


class ClientTests(unittest.TestCase):
    def test_preflight_success_when_worker_is_ready(self) -> None:
        mock_repo = mock.MagicMock()
        mock_repo.worker_ready.return_value = True
        client = RenderServiceClient(mock_repo, mock.MagicMock())
        client.preflight()
        mock_repo.worker_ready.assert_called_once_with(90)

    def test_preflight_fails_when_no_worker_is_ready(self) -> None:
        mock_repo = mock.MagicMock()
        mock_repo.worker_ready.return_value = False
        client = RenderServiceClient(mock_repo, mock.MagicMock())
        with self.assertRaisesRegex(RuntimeError, "no compatible XeLaTeX worker"):
            client.preflight()

    def test_compile_and_wait_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source"
            dest_dir = root / "destination"
            source_dir.mkdir()
            (source_dir / "resume.tex").write_text("hello")
            store = ArtifactStore(root / "store")

            output_dir = root / "output_staging"
            output_dir.mkdir()
            (output_dir / "resume.pdf").write_bytes(b"%PDF-1.4 test")
            req_id = str(uuid4())
            expected_result = {
                "schema_version": 1,
                "request_id": req_id,
                "status": "SUCCEEDED",
                "documents": {"resume.pdf": {"pages": 1}},
            }
            (output_dir / "result.json").write_text(json.dumps(expected_result))
            output_ref = store.put_directory(output_dir)

            mock_repo = mock.MagicMock()
            job_queued = RenderJob(
                id=str(uuid4()), state="QUEUED",
                request=RenderRequest(req_id, output_ref, (CompileDocument("resume.tex", "resume.pdf"),)),
                attempts=0, max_attempts=3,
            )
            job_succeeded = RenderJob(
                id=job_queued.id, state="SUCCEEDED",
                request=job_queued.request, attempts=1, max_attempts=3,
                output_artifact=output_ref, result=expected_result,
            )
            mock_repo.enqueue.return_value = job_queued
            mock_repo.get.return_value = job_succeeded

            client = RenderServiceClient(mock_repo, store)
            with mock.patch("uuid.uuid4", return_value=UUID(req_id)):
                result = client.compile_and_wait(
                    source_dir,
                    (CompileDocument("resume.tex", "resume.pdf"),),
                    dest_dir,
                    idempotency_key="test-key",
                )
            self.assertEqual(result, expected_result)
            self.assertTrue((dest_dir / "resume.pdf").is_file())
            self.assertTrue((dest_dir / "result.json").is_file())

    def test_compile_and_wait_failure_raises_render_job_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source"
            source_dir.mkdir()
            (source_dir / "resume.tex").write_text("hello")
            store = ArtifactStore(root / "store")

            mock_repo = mock.MagicMock()
            job_queued = RenderJob(
                id=str(uuid4()), state="QUEUED",
                request=RenderRequest(str(uuid4()), ArtifactRef("objects/a.tar", "a" * 64, 1), (CompileDocument("resume.tex", "resume.pdf"),)),
                attempts=0, max_attempts=3,
            )
            job_failed = RenderJob(
                id=job_queued.id, state="FAILED",
                request=job_queued.request, attempts=1, max_attempts=3,
                error_code="COMPILE_ERROR", error_detail="LaTeX syntax error",
            )
            mock_repo.enqueue.return_value = job_queued
            mock_repo.get.return_value = job_failed

            client = RenderServiceClient(mock_repo, store)
            with self.assertRaises(RenderJobFailure) as ctx:
                client.compile_and_wait(
                    source_dir, (CompileDocument("resume.tex", "resume.pdf"),),
                    root / "dest", idempotency_key="test-fail-key",
                )
            self.assertEqual(ctx.exception.code, "COMPILE_ERROR")
            self.assertEqual(ctx.exception.detail, "LaTeX syntax error")

    def test_compile_and_wait_timeout_raises_timeout_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source"
            source_dir.mkdir()
            (source_dir / "resume.tex").write_text("hello")
            store = ArtifactStore(root / "store")

            mock_repo = mock.MagicMock()
            job_running = RenderJob(
                id=str(uuid4()), state="RUNNING",
                request=RenderRequest(str(uuid4()), ArtifactRef("objects/a.tar", "a" * 64, 1), (CompileDocument("resume.tex", "resume.pdf"),)),
                attempts=1, max_attempts=3,
            )
            mock_repo.enqueue.return_value = job_running
            mock_repo.get.return_value = job_running

            client = RenderServiceClient(mock_repo, store)
            with self.assertRaises(TimeoutError):
                client.compile_and_wait(
                    source_dir, (CompileDocument("resume.tex", "resume.pdf"),),
                    root / "dest", idempotency_key="test-timeout-key",
                    wait_seconds=0,
                )

    def test_deterministic_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            file_a = Path(temporary) / "a.tex"
            file_a.write_text("content a")
            key1 = deterministic_key("test", file_a, options={"pages": 1})
            key2 = deterministic_key("test", file_a, options={"pages": 1})
            key3 = deterministic_key("test", file_a, options={"pages": 2})
            self.assertEqual(key1, key2)
            self.assertNotEqual(key1, key3)
            self.assertTrue(key1.startswith("test:"))


class ConfigTests(unittest.TestCase):
    def test_firebase_project_id_from_env_vars(self) -> None:
        with mock.patch.dict(os.environ, {"JAA_FIREBASE_PROJECT_ID": "my-jaa-project"}, clear=True):
            self.assertEqual(firebase_project_id(), "my-jaa-project")
        with mock.patch.dict(os.environ, {"GCLOUD_PROJECT": "gcloud-project"}, clear=True):
            self.assertEqual(firebase_project_id(), "gcloud-project")
        with mock.patch.dict(os.environ, {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"}, clear=True):
            self.assertEqual(firebase_project_id(), "demo-job-application-agents")

    def test_firebase_project_id_unconfigured_raises_runtime_error(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "set JAA_FIREBASE_PROJECT_ID"):
                firebase_project_id()

    def test_artifact_root_from_env_var_and_default(self) -> None:
        with mock.patch.dict(os.environ, {"JAA_ARTIFACT_ROOT": "/custom/artifacts"}):
            self.assertEqual(artifact_root(), Path("/custom/artifacts"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(str(artifact_root()).endswith(".render-service/artifacts"))


if __name__ == "__main__":
    unittest.main()
