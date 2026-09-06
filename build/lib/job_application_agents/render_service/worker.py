from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import tempfile
import threading
import time

from .artifacts import ArtifactStore
from .compiler import CompileFailure, compile_request
from .config import artifact_root, firebase_project_id
from .firestore import FirestoreRenderJobRepository
from .repository import RenderJobRepository


PROTOCOL_VERSION = 1
IMAGE_VERSION = os.environ.get("JAA_RENDER_IMAGE_VERSION", "development")


def capabilities() -> dict[str, bool]:
    return {name: shutil.which(name) is not None for name in ("xelatex", "pdfinfo", "pdftotext")}


class Worker:
    def __init__(self, repository: RenderJobRepository, artifacts: ArtifactStore, worker_id: str):
        self.repository = repository
        self.artifacts = artifacts
        self.worker_id = worker_id
        self.current_job: str | None = None
        self.stopping = threading.Event()

    def heartbeat_loop(self) -> None:
        elapsed = 0
        while not self.stopping.wait(30):
            try:
                if self.current_job:
                    self.repository.heartbeat(self.current_job, self.worker_id)
                elapsed += 30
                if elapsed >= 60:
                    self.repository.register_worker(self.worker_id, IMAGE_VERSION, capabilities())
                    elapsed = 0
            except Exception:
                pass

    def process(self, job) -> None:
        self.current_job = job.id
        try:
            with tempfile.TemporaryDirectory(prefix="latex-input-") as input_temp, \
                    tempfile.TemporaryDirectory(prefix="latex-output-") as output_temp:
                input_root, output_root = Path(input_temp), Path(output_temp)
                self.artifacts.extract(job.request.input_artifact, input_root)
                result = compile_request(job.request, input_root, output_root)
                output = self.artifacts.put_directory(output_root)
                self.repository.succeed(job.id, self.worker_id, output, result)
        except CompileFailure as exc:
            self.repository.fail(job.id, self.worker_id, exc.code, str(exc), exc.retryable)
        except Exception as exc:
            self.repository.fail(job.id, self.worker_id, "INFRASTRUCTURE_ERROR", str(exc), True)
        finally:
            self.current_job = None

    def run(self, once: bool = False) -> int:
        self.repository.register_worker(self.worker_id, IMAGE_VERSION, capabilities())
        if not all(capabilities().values()):
            raise RuntimeError("worker image is missing required rendering tools")
        heartbeat = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat.start()
        last_expiry_check = 0.0
        while not self.stopping.is_set():
            now = time.monotonic()
            if now - last_expiry_check >= 60:
                self.repository.requeue_expired()
                last_expiry_check = now
            job = self.repository.claim(self.worker_id)
            if job:
                self.process(job)
                if once:
                    break
            elif once:
                break
            else:
                self.stopping.wait(5)
        self.stopping.set()
        heartbeat.join(timeout=2)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile queued XeLaTeX packages")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        return 0 if all(capabilities().values()) else 1
    worker_id = os.environ.get("JAA_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
    worker = Worker(
        FirestoreRenderJobRepository(firebase_project_id()), ArtifactStore(artifact_root()), worker_id
    )
    signal.signal(signal.SIGTERM, lambda *_: worker.stopping.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stopping.set())
    return worker.run(args.once)


if __name__ == "__main__":
    raise SystemExit(main())
