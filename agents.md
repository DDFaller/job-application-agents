# Job Application Agents — Architecture & System Map

`job-application-agents` is an agentic AI pair-programming system designed to extract public job postings, tailor evidence-backed LaTeX application packages (resumes, cover letters), compile them via sandboxed XeLaTeX daemons, synchronize state with multi-tenant Google Cloud Firestore, and track applications on private Notion Kanban boards.

---

## 1. High-Level System Architecture

```mermaid
graph TD
    User([User / Developer]) --> Agent[AI Coding Agent<br>Codex]

    subgraph Agent Skills Layer [1. Agent Skills & Prompts Layer]
        Agent --> Skills[.agents/skills/<br>• prepare-job-application<br>• extract-job-opening<br>• tailor-application-bundle<br>• notion-track-application]
    end

    subgraph Core Python Engine [2. Core Python Business Logic]
        Skills --> RenderClient[render_service/<br>LaTeX Compilation]
        Skills --> SyncService[sync/<br>Firestore Cloud Sync]
        Skills --> NotionPlugin[plugins/notion/<br>Notion REST & Queue]
    end

    subgraph Background Daemons & Cloud [3. Cloud Infrastructure & Storage]
        RenderClient --> LWorker[deploy/docker/latex-worker<br>XeLaTeX Engine]
        SyncService --> Firestore[(Firestore: configured project<br>/users/{userId}/...)]
        NotionPlugin --> NotionJobsQueue[(Firestore notionJobs)]
        NotionJobsQueue --> NWorker[deploy/docker/notion-worker<br>Notion Queue Daemon]
        NWorker --> NotionCloud[(Notion Workspace & S3 CDN)]
    end

    subgraph Private Data Layer [4. Private Candidate Data]
        Skills --> LocalData[(External Data Root<br>job-search/ or ~/Documents/job-search)]
    end
```

---

## 2. Subcomponent Architecture Map

Each subsystem in the repository maintains its own dedicated `architecture.md` detailing its models, interfaces, protocols, and execution topology:

| Subsystem | Location | Architecture Document | Core Responsibilities |
|---|---|---|---|
| **Agent Skills** | `.agents/skills/` | [`.agents/skills/architecture.md`](file:///home/falluba/job-application-agents/.agents/skills/architecture.md) | Prompt instructions, clean-context subagents, extraction, tailoring, and quality gates. |
| **LaTeX Render Service** | `job_application_agents/render_service/` | [`render_service/architecture.md`](file:///home/falluba/job-application-agents/job_application_agents/render_service/architecture.md) | Content-addressed artifact store, XeLaTeX compilation engine, worker daemon, and HTTP server. |
| **Firestore Cloud Sync** | `job_application_agents/sync/` | [`sync/architecture.md`](file:///home/falluba/job-application-agents/job_application_agents/sync/architecture.md) | Multi-tenant tenant isolation (`/users/{userId}`), version subcollections, bidirectional drift detection. |
| **Notion Integration & Worker** | `job_application_agents/plugins/notion/` | [`plugins/notion/architecture.md`](file:///home/falluba/job-application-agents/job_application_agents/plugins/notion/architecture.md) | 2-step Notion file uploads, transactional queue leases, dynamic per-user database routing. |
| **Auto-Apply Engine** | `job_application_agents/auto_apply/` | [`auto_apply/architecture.md`](file:///home/falluba/job-application-agents/job_application_agents/auto_apply/architecture.md) | Playwright browser automation, ATS form drivers (Lever, Ashby, Greenhouse), document upload, receipts. |
| **Deployment & Infrastructure** | `deploy/` | [`deploy/architecture.md`](file:///home/falluba/job-application-agents/deploy/architecture.md) | Dockerfiles, Compose setups (local vs live), Firestore security rules, and composite indexes. |


---

## 3. Data Flow & Execution Lifecycle

```
1. Extraction:
   Public Job URL ──► extract-job-opening ──► Normalized job.json + source.md

2. Tailoring:
   job.json + master-curriculum ──► tailor-application-bundle ──► resume.tex + letter.tex

3. Compilation:
   resume.tex ──► render_service (XeLaTeX) ──► resume.pdf + quality gate validation

4. Cloud Persistence:
   Application Package ──► sync.py push ──► Firestore /users/{userId}/applications/{id}

5. Live Board Tracking:
   Firestore Queue ──► notion-worker ──► Notion Kanban Board (with PDFs & LaTeX ZIPs)
```

---

## 4. Security & Multi-Tenant Isolation
- **Private Data Partition**: Private candidate files in `job-search/` are ignored by git and resolved dynamically via `--data-root` or `JAA_DATA_ROOT`.
- **Database Rules**: Google Cloud Firestore requires authentication and strictly enforces `request.auth.uid == userId` for user-level reads and writes. Queue and incident collections are server-only, and clients cannot promote an application to `APPLIED`.
- **Notion Board Isolation**: Each user connects their private Notion database table, ensuring complete row-level isolation across multi-user environments.
