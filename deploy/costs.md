# Retirement applied — 5 October 2026

`tinder-jobs-4bf1b` cloud PDF rendering and automatic Notion synchronization
are retired. Cloud Run services, Cloud Functions, the two Scheduler jobs and
the application Eventarc trigger have been removed. Firestore, Hosting and
stored candidate artifacts remain. Use local rendering and Firestore-only
storage. Routine live deployment and smoke entrypoints now refuse to recreate
this project’s retired compute.

The project’s existing monthly alerts-only budget is EUR 8.91 (approximately
USD 10 using the 2 October ECB reference rate), with 50%, 80%, 100% actual
thresholds and a 100% forecast threshold. This is not a hard spending cap.

Recovery configuration and original function source archives are held privately
at `/home/falluba/jaa-2.0/.cache/firebase-retirement-20261005/`. Retain them and
the protected image digests through at least 4 November 2026. Do not commit
these archives. Restoration is manual and reintroduces cloud compute costs.

Remaining external cleanup: remove the retired webhook subscription in the
Notion connection’s Webhooks settings. The Google endpoint is already deleted.
Billing trends still need a 24–48 hour and seven-day follow-up.

The former planning baseline below is historical and does not describe the
current deployment.

---

# Live Cost Baseline (Phase 1)

Target: idle monthly spend ≈ $0 on a Blaze plan with scale-to-zero everywhere.
All figures are list-price expectations for a single-user workload; verify
against the Cloud Billing console after the phase-7 smoke test.

| Service | Configuration | Expected idle cost | Notes |
|---|---|---|---|
| Firestore | Native mode, single region | $0 | Free tier: 50k reads / 20k writes / 20k deletes per day. Single-user workload stays inside it. |
| Cloud Functions (gen2) `on_application_written` | `minInstances: 0`, 128–256MB | $0 | Invoked only on application writes. |
| Cloud Functions `notion_webhook` | `minInstances: 0` | $0 | Invoked on Gmail-push/Notion events only. |
| Cloud Scheduler sweeps | 30–60 min safety sweep + hourly reconcile (phase 6) | ~$0 | Scheduler: 3 free jobs/month; invocations billed as function calls, negligible at this cadence. The current 1-minute drain is removed in phase 6. |
| Cloud Run `latex-worker` | `minInstances: 0`, direct `POST /compile` (phase 5) | $0 idle | Billed per request CPU/memory; a render costs fractions of a cent. Cold start accepted, queue path is fallback. |
| Cloud Run `notion-worker` | `minInstances: 0` or Functions-only | $0 idle | Prefer running Notion work inside Functions; keep the worker image as fallback. |
| Playwright worker | `submission` profile only, never auto-started | $0 | Only runs for supervised submissions. |
| Firebase Hosting (PWA) | Static | $0 | Free tier: 10GB hosting storage + 360MB/day transfer. |
| Firebase Auth | Email/Google provider | $0 | Free tier covers single user trivially. |
| Artifact Registry (`jaa-workers`) | `europe-west1`, 3 images | ~$0 | $0.10/GB/month; three small images ≈ cents. Cleanup old tags. |
| Secret Manager (`NOTION_TOKEN`, unused in `firestore_only`) | 0–1 secrets | $0 | Free tier: 6 active secret versions. Notion secret dropped once `firestore_only` lands. |
| Gemini Flash (agent stages) | Low-effort default via model policy (phase 2) | pay-per-use | Heaviest variable cost; parse-once (phase 3) and push-ingest (phase 4) exist to minimize calls. |

Budget alerts to create (console, requires owner login): $0 (any spend),
$10, $50 — billing account alerts, not code.

Region choice: `europe-west1` (lowest latency for the user; Firestore +
Functions + Run co-located avoids cross-region egress).
