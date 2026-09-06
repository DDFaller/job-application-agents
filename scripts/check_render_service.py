#!/usr/bin/env python3
"""Exercise the Firestore queue and Dockerized XeLaTeX worker end to end."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from job_application_agents.render_service.artifacts import ArtifactStore
from job_application_agents.render_service.client import RenderServiceClient
from job_application_agents.render_service.config import artifact_root, firebase_project_id
from job_application_agents.render_service.firestore import (
    FirestoreRenderJobRepository, JOB_COLLECTION, WORKER_COLLECTION,
)
from job_application_agents.render_service.models import CompileDocument


DOCUMENT = r"""\documentclass{article}
\usepackage{fontspec}
\usepackage{fontawesome5}
\usepackage{mfirstuc}
\usepackage{tikz}
\usepackage{adjustbox}
\begin{document}
\faGithub\ Render service integration check.
\end{document}
"""

REQUIRED_PACKAGES = (
    "fontspec.sty", "fontawesome5.sty", "mfirstuc.sty", "tikz.sty", "adjustbox.sty",
)


def _write_sources(source: Path) -> None:
    (source / "resume.tex").write_text(DOCUMENT, encoding="utf-8")
    (source / "letter.tex").write_text(DOCUMENT, encoding="utf-8")


def _documents() -> tuple:
    return (
        CompileDocument("resume.tex", "resume.pdf", extract_raw_text=True),
        CompileDocument("letter.tex", "motivation-letter.pdf"),
    )


def _verify_output(output: Path) -> None:
    for name in ("resume.pdf", "motivation-letter.pdf", "result.json"):
        if not (output / name).is_file():
            raise RuntimeError(f"render service output is missing {name}")


def _deterministic_summary(result: dict) -> dict:
    """Comparable subset of a result manifest (excludes timestamps/hashes)."""
    return {
        name: {
            "pages": info.get("pages"),
            "normalized_text_sha256": info.get("normalized_text_sha256"),
        }
        for name, info in (result.get("documents") or {}).items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", action="store_true", help="remove this smoke test's Firebase records")
    parser.add_argument("--cleanup-only", action="store_true", help="remove smoke-test records without compiling")
    parser.add_argument("--direct", action="store_true",
                        help="compile via the direct worker (no Firestore records)")
    parser.add_argument("--parity", action="store_true",
                        help="compile via queue and direct paths and compare deterministic outputs")
    args = parser.parse_args()
    if args.direct:
        from job_application_agents.render_service.client import (
            RenderServiceClient, direct_worker_ready,
        )
        from job_application_agents.render_service.config import render_url
        url = render_url()
        if not direct_worker_ready(url, timeout_seconds=10):
            raise RuntimeError(f"direct render worker is not ready at {url}")
        store = ArtifactStore(artifact_root())
        client = RenderServiceClient(None, store)
        with tempfile.TemporaryDirectory(prefix="render-check-source-") as source_temp, \
                tempfile.TemporaryDirectory(prefix="render-check-output-") as output_temp:
            source, output = Path(source_temp), Path(output_temp)
            _write_sources(source)
            result = client.compile_direct(
                url, source, _documents(), output,
                request_id=uuid4().hex,
                required_packages=REQUIRED_PACKAGES,
            )
            if result.get("status") != "SUCCEEDED":
                raise RuntimeError("direct render did not report success")
            _verify_output(output)
        print("direct render check ready")
        return 0
    repository = FirestoreRenderJobRepository(firebase_project_id())
    store = ArtifactStore(artifact_root())
    client = RenderServiceClient(repository, store)
    run_id = os.environ.get("JAA_INTEGRATION_ID") or str(uuid4())
    idempotency_key = f"render-service-integration:{run_id}"
    job_id = repository.job_id_for_key(idempotency_key)
    if args.cleanup_only:
        repository.client.collection(JOB_COLLECTION).document(job_id).delete()
        worker_id = os.environ.get("JAA_WORKER_ID")
        if worker_id:
            repository.client.collection(WORKER_COLLECTION).document(worker_id).delete()
        print("render service smoke records removed")
        return 0
    deadline = time.monotonic() + 60
    while True:
        try:
            client.preflight()
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    try:
        with tempfile.TemporaryDirectory(prefix="render-check-source-") as source_temp, \
                tempfile.TemporaryDirectory(prefix="render-check-output-") as output_temp:
            source, output = Path(source_temp), Path(output_temp)
            _write_sources(source)
            result = client.compile_and_wait(
                source,
                _documents(),
                output,
                idempotency_key=idempotency_key,
                required_packages=REQUIRED_PACKAGES,
            )
            if result.get("status") != "SUCCEEDED":
                raise RuntimeError("render service did not report success")
            _verify_output(output)
            if args.parity:
                from job_application_agents.render_service.client import direct_worker_ready
                from job_application_agents.render_service.config import render_url
                url = render_url()
                if not direct_worker_ready(url, timeout_seconds=10):
                    raise RuntimeError(f"direct render worker is not ready at {url}")
                direct_client = RenderServiceClient(None, store)
                with tempfile.TemporaryDirectory(prefix="render-check-direct-") as direct_temp:
                    direct_output = Path(direct_temp)
                    direct_result = direct_client.compile_direct(
                        url, source, _documents(), direct_output,
                        request_id=uuid4().hex,
                        required_packages=REQUIRED_PACKAGES,
                    )
                    if direct_result.get("status") != "SUCCEEDED":
                        raise RuntimeError("direct render did not report success")
                    queue_summary = _deterministic_summary(result)
                    direct_summary = _deterministic_summary(direct_result)
                    if queue_summary != direct_summary:
                        raise RuntimeError(
                            "queue and direct outputs differ: "
                            f"{queue_summary} != {direct_summary}"
                        )
                    print("queue/direct parity confirmed")
    finally:
        if args.cleanup:
            repository.client.collection(JOB_COLLECTION).document(job_id).delete()
            worker_id = os.environ.get("JAA_WORKER_ID")
            if worker_id:
                repository.client.collection(WORKER_COLLECTION).document(worker_id).delete()
    print("render service integration ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
