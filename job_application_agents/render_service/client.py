from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import tempfile
import time
import urllib.error
import urllib.request
from uuid import uuid4

from .artifacts import ArtifactStore
from .models import ArtifactRef, CompileDocument, RenderRequest
from .repository import RenderJobRepository


class RenderJobFailure(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# Error codes that only mean "try the direct worker again later" (or fall
# back to the queue path); everything else is a property of the request.
RETRYABLE_DIRECT_CODES = frozenset({"WORKER_BUSY", "TIMEOUT", "DIRECT_UNAVAILABLE"})

# Module-level opener that bypasses proxy env vars: the direct worker is
# always loopback or container-network addressed.
_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def direct_worker_ready(base_url: str, timeout_seconds: float = 5.0) -> bool:
    """Return True when a direct render worker answers /healthz as READY."""
    url = base_url.rstrip("/") + "/healthz"
    try:
        with _direct_opener.open(url, timeout=timeout_seconds) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    if payload.get("status") != "READY":
        return False
    capabilities = payload.get("capabilities") or {}
    return all(capabilities.get(name) is True for name in ("xelatex", "pdfinfo", "pdftotext"))


class RenderServiceClient:
    def __init__(self, repository: RenderJobRepository | None, artifacts: ArtifactStore):
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
        return self._collect_result(job.output_artifact, job.result, job.request.request_id, destination)

    def _collect_result(
        self,
        output_artifact: ArtifactRef,
        result: dict,
        request_id: str,
        destination: Path,
    ) -> dict:
        """Extract an output artifact and verify it matches the claimed result."""
        with tempfile.TemporaryDirectory(prefix="render-result-") as temporary:
            extracted = Path(temporary)
            self.artifacts.extract(output_artifact, extracted)
            manifest_path = extracted / "result.json"
            if not manifest_path.is_file():
                raise RuntimeError("render worker output is missing result.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest != result or manifest.get("request_id") != request_id:
                raise RuntimeError("render worker result does not match the claimed job")
            destination.mkdir(parents=True, exist_ok=True)
            for path in extracted.rglob("*"):
                if not path.is_file():
                    continue
                target = destination / path.relative_to(extracted)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        return result

    @staticmethod
    def _direct_error(exc: urllib.error.HTTPError) -> RenderJobFailure:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if exc.code in (429, 503):
            detail = body.get("error") or f"worker busy (HTTP {exc.code})"
            retry_after = exc.headers.get("Retry-After", "?") if exc.headers else "?"
            return RenderJobFailure("WORKER_BUSY", f"{detail}; retry after {retry_after}s")
        code = body.get("error_code") or f"HTTP_{exc.code}"
        detail = body.get("error_detail") or body.get("error") or f"HTTP {exc.code}"
        return RenderJobFailure(str(code), str(detail))

    def compile_direct(
        self,
        base_url: str,
        source_directory: Path,
        documents: tuple[CompileDocument, ...],
        destination: Path,
        *,
        request_id: str | None = None,
        required_packages: tuple[str, ...] = (),
        required_fonts: tuple[str, ...] = (),
        timeout_seconds: int = 300,
        user_id: str | None = None,
    ) -> dict:
        """Compile via a direct worker's /compile endpoint (no Firestore).

        Sources are staged with put_directory into the shared artifact root,
        then compiled synchronously. Raises RenderJobFailure with code
        DIRECT_UNAVAILABLE when the worker is unreachable, WORKER_BUSY when
        saturated, or the engine's own error code on compile failure.
        """
        request = RenderRequest(
            request_id=request_id or str(uuid4()),
            input_artifact=self.artifacts.put_directory(source_directory),
            documents=documents, required_packages=required_packages,
            required_fonts=required_fonts, timeout_seconds=timeout_seconds,
            user_id=user_id,
        )
        payload = json.dumps({"request": request.to_dict()}).encode("utf-8")
        http_request = urllib.request.Request(
            base_url.rstrip("/") + "/compile", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with _direct_opener.open(http_request, timeout=timeout_seconds + 60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise self._direct_error(exc) from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            raise RenderJobFailure(
                "DIRECT_UNAVAILABLE", f"direct render worker unreachable: {exc}"
            ) from exc
        if not isinstance(body, dict):
            raise RenderJobFailure("DIRECT_UNAVAILABLE", "direct render worker returned malformed response")
        try:
            output_artifact = ArtifactRef.from_dict(body["output_artifact"])
            result = body["result"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RenderJobFailure(
                "DIRECT_UNAVAILABLE", f"direct render worker returned malformed response: {exc}"
            ) from exc
        if not isinstance(result, dict):
            raise RenderJobFailure("DIRECT_UNAVAILABLE", "direct render worker returned malformed response")
        return self._collect_result(output_artifact, result, request.request_id, destination)


def deterministic_key(prefix: str, *paths: Path, options: dict | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(prefix.encode("utf-8"))
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    if options:
        digest.update(json.dumps(options, sort_keys=True).encode("utf-8"))
    return f"{prefix}:{digest.hexdigest()}"
