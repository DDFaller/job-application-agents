# LaTeX Render Service Architecture

The **LaTeX Render Service** (`job_application_agents/render_service`) is a deterministic, containerized XeLaTeX compilation engine that compiles tailored LaTeX resumes and motivation letters into standard PDF documents without requiring local TeXLive installations on developer machines.

---

## 1. Component Topology

```
┌────────────────────────┐
│      RenderClient      │ ◄─── Invoked by tailoring skills / CLI
└───────────┬────────────┘
            │
            ├── 1. Put Source Artifacts
            ▼
┌────────────────────────┐
│     ArtifactStore      │ ◄─── Content-addressed SHA-256 tar.gz storage
└───────────┬────────────┘
            │
            ├── 2. Enqueue RenderJob / REST Request
            ▼
┌────────────────────────┐
│     RenderWorker       │ ◄─── Headless XeLaTeX sandbox execution
│   (or HTTPS Server)    │      (pdftotext extraction & quality check)
└───────────┬────────────┘
            │
            ├── 3. Write PDF & Manifest
            ▼
┌────────────────────────┐
│    Compiled Artifacts  │ ───► resume.pdf, motivation-letter.pdf
└────────────────────────┘
```

---

## 2. Core Modules

| Module | Responsibility |
|---|---|
| [`models.py`](file:///home/falluba/job-application-agents/job_application_agents/render_service/models.py) | Immutable dataclasses (`RenderJob`, `RenderRequest`, `CompileDocument`, `ArtifactRef`). |
| [`artifact_store.py`](file:///home/falluba/job-application-agents/job_application_agents/render_service/artifact_store.py) | Content-addressed SHA-256 storage for source files and compiled PDFs with directory traversal protection. |
| [`compiler.py`](file:///home/falluba/job-application-agents/job_application_agents/render_service/compiler.py) | Direct wrapper around `xelatex` and `pdftotext` with timeout enforcement, error extraction, and sandboxing. |
| [`client.py`](file:///home/falluba/job-application-agents/job_application_agents/render_service/client.py) | Client interface offering preflight readiness checks, job polling, and deterministic SHA-256 keying. |
| [`worker.py`](file:///home/falluba/job-application-agents/job_application_agents/render_service/worker.py) | Long-running daemon leasing `renderJobs` from Firestore or processing local queue batches. |
| [`server.py`](file:///home/falluba/job-application-agents/job_application_agents/render_service/server.py) | HTTP REST microservice (`/healthz`, `/process-job`) for serverless cloud execution. |

---

## 3. Data Contracts

### Render Request Payload
```json
{
  "request_id": "req-uuid",
  "documents": [
    {
      "document_type": "resume",
      "target_file": "resume.pdf",
      "source_file": "resume.tex",
      "primary_tex": "resume.tex"
    }
  ],
  "source_artifact": {
    "uri": "sha256:abcd...",
    "digest": "abcd..."
  }
}
```

---

## 4. Key Architectural Decisions
1. **Content-Addressed Storage**: Inputs and outputs are keyed by SHA-256 hashes to enable zero-overhead caching and deduplication.
2. **Security Isolation**: XeLaTeX is run with `-no-shell-escape` and locked down file system access.
3. **Multi-Mode Execution**: Operates locally in CLI, as a background container via Docker Compose, or as a managed Cloud Run microservice.
