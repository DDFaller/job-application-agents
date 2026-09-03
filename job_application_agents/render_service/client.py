from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from .artifacts import ArtifactStore
from .models import CompileDocument, RenderRequest
from .repository import RenderJobRepository


class RenderJobFailure(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class RenderServiceClient:
    def __init__(self, repository: RenderJobRepository, artifacts: ArtifactStore):
        self.repository = repository
        self.artifacts = artifacts

    def preflight(self) -> None:
        if not self.repository.worker_ready(90):
            raise RuntimeError("no compatible XeLaTeX worker has reported ready in the last 90 seconds")

    def compile_and_wait(
        self,
        source_directory: Path,
        documents: tuple[CompileDocument, ...],
        destination: Path,
        *,
        idempotency_key: str,
        required_packages: tuple[str, ...] = (),
        required_fonts: tuple[str, ...] = (),
        user_id: str | None = None,
        wait_seconds: int = 330,
    ) -> dict:
        input_artifact = self.artifacts.put_directory(source_directory)
        request = RenderRequest(
            request_id=str(uuid4()), input_artifact=input_artifact,
            documents=documents, required_packages=required_packages,
            required_fonts=required_fonts, timeout_seconds=300,
            user_id=user_id,
        )
        job = self.repository.enqueue(request, idempotency_key)
        deadline = time.monotonic() + wait_seconds
        while job.state in {"QUEUED", "RUNNING"}:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for render job {job.id}")
            time.sleep(1)
            job = self.repository.get(job.id)
        if job.state != "SUCCEEDED" or not job.output_artifact or not job.result:
            detail = job.error_detail or "render job failed without an error detail"
            raise RenderJobFailure(job.error_code or "RENDER_FAILED", detail)
        with tempfile.TemporaryDirectory(prefix="render-result-") as temporary:
            extracted = Path(temporary)
            self.artifacts.extract(job.output_artifact, extracted)
            manifest_path = extracted / "result.json"
            if not manifest_path.is_file():
                raise RuntimeError("render worker output is missing result.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest != job.result or manifest.get("request_id") != job.request.request_id:
                raise RuntimeError("render worker result does not match the claimed job")
            destination.mkdir(parents=True, exist_ok=True)
            for path in extracted.rglob("*"):
                if not path.is_file():
                    continue
                target = destination / path.relative_to(extracted)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        return job.result


def deterministic_key(prefix: str, *paths: Path, options: dict | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(prefix.encode("utf-8"))
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    if options:
        digest.update(json.dumps(options, sort_keys=True).encode("utf-8"))
    return f"{prefix}:{digest.hexdigest()}"
