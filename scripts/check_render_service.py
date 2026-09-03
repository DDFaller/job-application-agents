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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", action="store_true", help="remove this smoke test's Firebase records")
    parser.add_argument("--cleanup-only", action="store_true", help="remove smoke-test records without compiling")
    args = parser.parse_args()
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
            (source / "resume.tex").write_text(DOCUMENT, encoding="utf-8")
            (source / "letter.tex").write_text(DOCUMENT, encoding="utf-8")
            result = client.compile_and_wait(
                source,
                (
                    CompileDocument("resume.tex", "resume.pdf", extract_raw_text=True),
                    CompileDocument("letter.tex", "motivation-letter.pdf"),
                ),
                output,
                idempotency_key=idempotency_key,
                required_packages=REQUIRED_PACKAGES,
            )
            if result.get("status") != "SUCCEEDED":
                raise RuntimeError("render service did not report success")
            for name in ("resume.pdf", "motivation-letter.pdf", "result.json"):
                if not (output / name).is_file():
                    raise RuntimeError(f"render service output is missing {name}")
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
