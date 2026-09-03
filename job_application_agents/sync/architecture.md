# Cloud Sync & Multi-Tenant Firestore Architecture

The **Sync Engine** (`job_application_agents/sync`) provides multi-tenant persistence, atomic versioning, and bidirectional synchronization between local workspace application bundles and a configured Google Cloud Firestore project.

---

## 1. Multi-Tenant Firestore Schema

All user data is partitioned under `/users/{userId}` to enforce strict tenant isolation via Firestore Security Rules:

```
firestore/
├── users/
│   └── {userId}/
│       │
│       ├── (user root document: metadata, notion_config)
│       │
│       ├── curriculum/
│       │   ├── current (Canonical markdown evidence & digests)
│       │   └── versions/{versionId}
│       │
│       ├── profiles/
│       │   ├── current (Approved role-profile catalog)
│       │   └── versions/{versionId}
│       │
│       └── applications/
│           └── {applicationId}/
│               ├── (app document: status, company, role, notion_page_id, url, sync)
│               └── versions/
│                   └── {versionId} (resume.tex, match-analysis.md, documents)
│
└── notionJobs/ (Server-only transactional queue)
    └── {jobId} (state: QUEUED | RUNNING | SUCCEEDED | FAILED)
└── notionWebhookEvents/ (deduplication ledger)
    └── {eventId}
```

---

## 2. Core Modules

| Module | Responsibility |
|---|---|
| [`models.py`](file:///home/falluba/job-application-agents/job_application_agents/sync/models.py) | Snapshot data classes (`ApplicationSyncSnapshot`, `ApplicationVersionSnapshot`, `CurriculumSyncSnapshot`, `ProfileSyncSnapshot`). |
| [`firestore.py`](file:///home/falluba/job-application-agents/job_application_agents/sync/firestore.py) | Firestore client repository handling subcollections, per-user Notion configuration, and atomic batch syncs. |
| [`service.py`](file:///home/falluba/job-application-agents/job_application_agents/sync/service.py) | High-level synchronization service orchestrating bidirectional `push`, `pull`, and drift detection. |

---

## 3. Synchronization Protocols

### 1. Push Workflow (Local ➔ Cloud)
1. Hashes local source files in `--data-root` (`sources/`, `master-curriculum/profiles/`, `applications/`).
2. Checks cloud version digests to prevent redundant network writes.
3. Commits application snapshots and version subcollections in atomic Firestore transactions.
4. Triggers Notion sync jobs when application documents change.

### 2. Pull Workflow (Cloud ➔ Local)
1. Queries `/users/{userId}/applications` with subcollection streams.
2. Reconstructs local directory tree: `job-search/applications/{company}/{role}/{job_id}/{version}/`.
3. Writes `current.json`, `job.json`, `manifest.json`, and `.tex` source files.

### 3. Automatic Firestore ⇄ Notion Application Sync
1. Firebase Functions observe application document writes and enqueue an
   idempotent `notionJobs` projection job.
2. The queue is drained by the existing worker or the scheduled Firebase
   queue-drainer.
3. Notion signed webhooks retrieve the latest page, accept only lifecycle
   fields (`Status`, `Applied At`, `Next Action At`, `Notes`), and write those
   values back to Firestore.
4. Firestore remains canonical; newer Firestore changes win and are requeued
   as projection repairs. An hourly reconciliation repairs missed events.

### 3. Tenant Isolation & Security
- **Security Rules**: Enforced at database engine level (`request.auth.uid == userId`).
- **Data Privacy**: Users cannot read, list, or write another user's curriculum or applications.
