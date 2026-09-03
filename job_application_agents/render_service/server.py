from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any
from uuid import uuid4

from .artifacts import ArtifactStore
from .compiler import CompileFailure, compile_request
from .config import artifact_root, firebase_project_id
from .firestore import FirestoreRenderJobRepository
from .models import CompileDocument, RenderRequest
from .worker import Worker, capabilities


class RenderHTTPRequestHandler(BaseHTTPRequestHandler):
    """Lightweight HTTP server for Google Cloud Run and health probes."""

    repository: FirestoreRenderJobRepository | None = None
    artifacts: ArtifactStore | None = None
    worker_id: str = f"cloud-run-{uuid4()}"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in {"/", "/healthz", "/health"}:
            caps = capabilities()
            ready = all(caps.get(k) is True for k in ("xelatex", "pdfinfo", "pdftotext"))
            status = 200 if ready else 503
            self._send_json(status, {
                "status": "READY" if ready else "DEGRADED",
                "worker_id": self.worker_id,
                "capabilities": caps,
            })
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self) -> None:
        path = self.path.split("?")[0]

        # 1. Process specific or next queued Firestore job
        if path in {"/process-job", "/process"}:
            try:
                body = self._read_json()
                job_id = body.get("job_id")
                if not self.repository or not self.artifacts:
                    self._send_json(500, {"error": "Repository or artifact store uninitialized"})
                    return

                worker = Worker(
                    repository=self.repository,
                    artifacts=self.artifacts,
                    worker_id=self.worker_id,
                )
                if job_id:
                    # Specific job execution
                    job = self.repository.get(job_id)
                    worker.process(job)
                    self._send_json(200, {"job_id": job_id, "processed": True})
                else:
                    # Claim next job in queue
                    claimed_job = self.repository.claim(self.worker_id)
                    if claimed_job:
                        worker.process(claimed_job)
                        self._send_json(200, {"status": "PROCESSED", "job_id": claimed_job.id})
                    else:
                        self._send_json(200, {"status": "NO_JOBS_QUEUED"})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        # 2. Direct compile endpoint (synchronous)
        if path in {"/compile"}:
            try:
                body = self._read_json()
                request_data = body.get("request")
                if not request_data:
                    self._send_json(400, {"error": "missing 'request' in body"})
                    return
                request = RenderRequest.from_dict(request_data)
                if not self.artifacts:
                    self._send_json(500, {"error": "Artifact store uninitialized"})
                    return

                import tempfile
                with tempfile.TemporaryDirectory(prefix="cloud-run-compile-") as temporary:
                    source_dir = Path(temporary) / "source"
                    output_dir = Path(temporary) / "output"
                    source_dir.mkdir()
                    output_dir.mkdir()
                    self.artifacts.extract(request.input_artifact, source_dir)
                    manifest = compile_request(request, source_dir, output_dir)
                    out_artifact = self.artifacts.put_directory(output_dir)
                    self._send_json(200, {
                        "result": manifest,
                        "output_artifact": out_artifact.to_dict(),
                    })
            except CompileFailure as exc:
                self._send_json(422, {"error_code": exc.code, "error_detail": str(exc)})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        self._send_json(404, {"error": "Not Found"})


def run_server(port: int = 8080, host: str = "0.0.0.0") -> None:
    art_store = ArtifactStore(artifact_root())
    repo: FirestoreRenderJobRepository | None = None
    try:
        repo = FirestoreRenderJobRepository(firebase_project_id())
    except Exception as exc:
        print(f"Note: Firestore repository not initialized: {exc}", file=sys.stderr)

    RenderHTTPRequestHandler.artifacts = art_store
    RenderHTTPRequestHandler.repository = repo

    worker = None
    worker_thread = None
    if repo is not None:
        worker = Worker(repo, art_store, RenderHTTPRequestHandler.worker_id)
        worker_thread = threading.Thread(target=worker.run, name="render-queue-worker", daemon=True)
        worker_thread.start()

    server = HTTPServer((host, port), RenderHTTPRequestHandler)
    print(f"Render server listening on {host}:{port} (Worker ID: {RenderHTTPRequestHandler.worker_id})...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down render server.")
    finally:
        if worker is not None:
            worker.stopping.set()
        if worker_thread is not None:
            worker_thread.join(timeout=5)
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud Run / HTTP Render Service Entrypoint")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)), help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind")
    args = parser.parse_args()
    run_server(port=args.port, host=args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
