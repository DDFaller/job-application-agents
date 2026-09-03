# Notion Integration Plugin & Worker Architecture

The **Notion Plugin** (`job_application_agents/plugins/notion`) connects the application lifecycle to Notion workspaces, producing live Kanban tracking cards, embedding real PDFs, and uploading LaTeX source ZIP packages.

---

## 1. Component Topology

```
┌────────────────────────┐
│  Sync / Agent Trigger  │ ──► On application create / update
└───────────┬────────────┘
            │
            ▼ Enqueue Job (action: CREATE_OR_UPDATE | DELETE)
┌────────────────────────────────────────────────────────┐
│         Firestore `notionJobs` Collection              │
│   • Transactional queue with 5-minute lease locks      │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ Claim Lease
┌────────────────────────────────────────────────────────┐
│                    NotionWorker                        │
│   1. Resolves user's private Notion Database ID        │
│   2. Streams 2-step PDF & ZIP binary uploads           │
│   3. Creates or updates Notion card & blocks           │
│   4. Updates Firestore application with Notion URL     │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│               Notion Database & Workspace              │
│   • Kanban Board categorized by `Status`               │
│   • Native PDF inline viewer                           │
│   • Downloadable LaTeX source ZIP archives             │
└────────────────────────────────────────────────────────┘
```

Firestore Functions also expose the `notion_webhook` HTTPS endpoint and an
hourly reconciliation job. Notion webhook deliveries are authenticated with
the connection verification token and deduplicated in
`notionWebhookEvents`; the payload is only a change signal, so the handler
retrieves the current page before applying allowed lifecycle fields.

---

## 2. Core Modules

| Module | Responsibility |
|---|---|
| [`client.py`](file:///home/falluba/job-application-agents/job_application_agents/plugins/notion/client.py) | Low-level Notion REST API client implementing 2-step file uploads, block chunking (<=2000 chars), and property adapters. |
| [`models.py`](file:///home/falluba/job-application-agents/job_application_agents/plugins/notion/models.py) | Typed payload models (`NotionCardPayload`, `NotionSyncJob`). |
| [`firestore.py`](file:///home/falluba/job-application-agents/job_application_agents/plugins/notion/firestore.py) | `FirestoreNotionJobRepository` implementing transactional queue claims, lease management, and auto-requeue. |
| [`worker.py`](file:///home/falluba/job-application-agents/job_application_agents/plugins/notion/worker.py) | Multi-tenant worker daemon processing queued jobs, resolving per-user database configs, and updating cloud records. |
| [`__init__.py`](file:///home/falluba/job-application-agents/job_application_agents/plugins/notion/__init__.py) | Lifecycle hook listeners (`on_application_saved`, `on_application_deleted`). |

---

## 3. Key Technical Protocols

### A. 2-Step Notion File Upload Protocol
To attach actual `.pdf` and `.zip` files into Notion pages:
1. **Init (`POST /v1/file_uploads`)**: Request an upload slot and receive a `file_id` and upload URL.
2. **Binary Upload (`POST <upload_url>`)**: Stream multipart binary data with `Notion-Version: 2022-06-28`.
3. **Embed Block**: Add `pdf` or `file` block referencing the uploaded `file_id`.

### B. Multi-Tenant Notion Routing
- Notion does not support row-level permissions within a single database table.
- To guarantee 100% privacy, each user configures their private database ID in Firestore (`/users/{userId}/notion_config`).
- The worker dynamically inspects the job's `user_id`, queries their configured database ID, and writes cards exclusively to their private board.
