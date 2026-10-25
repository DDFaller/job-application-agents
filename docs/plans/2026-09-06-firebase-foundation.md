## Goal

Turn this codebase into a live product on Firebase at the lowest sustainable cost: one Blaze project where ingestion, evidence, pipeline, rendering, and sync run as independently deployable microservices with hexagonal boundaries, every service ships its own unit tests plus contract/integration tests as definition of done, heavy agent stages default to low-cost Gemini models, the known reparse/pulling bugs are fixed, and LaTeX rendering takes the lowest-latency path available in each environment.

## Success Criteria

- `firebase deploy` from a clean checkout brings up Hosting (PWA), Firestore (rules + indexes), and all Functions/services against a configured project; `python3 scripts/check.py` passes before and after.
- A new Gmail job alert flows to a staged, scored job with no full-mailbox rescan and no duplicate processing.
- `prepare-job-application` parses candidate sources at most once per source-manifest fingerprint; a second run with unchanged sources is a validated cache hit with zero LLM calls.
- A render request returns a PDF via the fastest available path (direct compile, no queue wait) locally and on Cloud Run.
- Each microservice has: unit tests colocated (`test_*.py`), at least one contract/integration test running against the Firestore emulator, and a documented monthly-cost line item.
- No live-service change ships without an explicit `--live` invocation and a passing emulator suite.

## Context And Current Facts

- Deploy surface already exists: `functions/main.py` defines 4 Firebase Functions (Firestore trigger `on_application_written`, HTTPS `notion_webhook`, schedulers `reconcile_notion_sync` hourly and `drain_notion_sync_queue` every minute); `deploy/cloudbuild.yaml` builds 3 workers (playwright, notion, latex); `deploy/compose.live.yaml` wires live workers; `deploy/firestore/` holds rules + indexes; `deploy/pwa/` is the Hosting app; `firebase.json` configures Functions/Firestore/Hosting/emulators.
- Lowest-latency render locally is already built on this branch (`d75d9e9 feat: direct containerized render path without Firestore`): `POST /compile` in `job_application_agents/render_service/server.py` calls `compile_request` synchronously with admission control; `test_direct.py` covers it. The Cloud Run worker still uses the queue-lease path (`enqueue` → 1s polling → lease/heartbeat).
- Parse-once machinery already exists: `map-candidate-evidence` resolves a source manifest, reuses only a cache entry whose fingerprint matches, and validates via `validate_candidate_evidence.py` + receipt. The reported reparse bug is therefore a caller/contract problem (controller or workers re-invoking parsing instead of passing hashed artifacts), not a missing cache.
- Cost defaults already exist: `job_application_agents/orchestration/worker_command.py` forces `effort=low` for Gemini models without an explicit effort suffix. Per-stage model routing (`skills/*/agents/*.yaml`, e.g. `prepare-job-application/agents/openai.yaml`) is the lever for making Gemini Flash the default everywhere heavy.
- Ingestion already has cheap filters before expensive work: `integrations/pipeline/` (date/title/experience prefilters), `integrations/email/processed_ledger.py` (dedupe ledger), `integrations/email/provider_filter.py`. The reported Gmail pulling problem is the scan strategy (repeated polling/rescanning), not missing filters.
- Gaps verified this session: `JAA_FIREBASE_PROJECT_ID` is unset (`.env`, `config.jsonc` are placeholders); live Firestore is unreachable from the sandbox (DNS blocked), though host ADC credentials for `tinder-jobs-4bf1b` exist; the Firestore emulator works (write/read/delete + `FirestoreUserSyncRepository` round-trip verified). Cost smell: `drain_notion_sync_queue` runs every minute and `reconcile_notion_sync` hourly — always-on polling burns Functions invocations.
- Test framework is stdlib `unittest` with `python3 scripts/check.py` as the gate; emulator-backed tests are skipped unless `FIRESTORE_EMULATOR_HOST` is set (`sync/test_sync.py`).

## Constraints And Non-goals

- Cheapest-first: prefer scale-to-zero (Functions gen2 / Cloud Run `min-instances: 0`), free-tier-shaped quotas, and fewer always-on daemons over latency or throughput. Any always-on resource needs a written cost justification.
- No new cloud vendor: Firebase/GCP only (Firestore, Functions, Cloud Run, Scheduler, Hosting, Auth, Secret Manager, Artifact Registry).
- Hexagonal: each service exposes domain ports (repository/use-case interfaces) with adapters for Firestore, Notion, Gmail, and LLM providers; no direct SDK imports in domain code.
- Non-goals: auto-apply submission stays gated (`JAA_ENABLE_SUBMISSION` + `--allow-submit` + confirmation, per `deploy/architecture.md`); no multi-region; no removal of the local-only/Notion-only modes; no new LLM vendor evaluation beyond making Gemini the default.

## Key Decisions

1. **Scale-to-zero everywhere, direct-compile on Cloud Run for latency.** Cloud Run `latex-worker` gains the already-proven `POST /compile` over HTTPS (warm `min-instances: 0`; first hit pays cold start, subsequent hits are direct with no Firestore polling). Rejected: always-warm worker (fixed monthly cost for a bursty workload) and keeping cloud renders on the 1s-poll queue path (adds seconds per render for no durability benefit — the queue remains as fallback).
2. **Gemini Flash (low effort) as default for all heavy agent stages; stronger models only via explicit per-stage override.** The `worker_command.py` low-effort default is extended into a central model policy (one config map stage → model/effort, audited in CI). Rejected: per-skill ad-hoc model strings (current drift source) and using a single flagship model everywhere (cost).
3. **Parse-once enforced by contract, not by convention.** `candidate-evidence.json` + receipt fingerprint becomes a required `StageTask` input for bundle-writing/humanization/review; stages that re-invoke extraction fail validation. Rejected: trusting workers to "just reuse the cache" (the current bug).
4. **Gmail push, not poll.** Replace repeated mailbox scans with Gmail `watch` + Pub/Sub push to an HTTPS function, keeping `ProcessedEmailLedger` as the idempotency backstop. Rejected: shorter poll intervals (scales cost linearly) and full rescan on each run (the current pain).
5. **Microservices = current deploy units, not a rewrite.** ingest, evidence, pipeline-controller, render, sync map onto existing packages/workers with hexagonal seams added; the 1-minute Notion drain scheduler is replaced by an event-driven claim (Firestore trigger already exists: `on_application_written`) plus a lenient sweep (e.g. every 30–60 min) as safety net. Rejected: big-bang rearchitecture and keeping 1-minute polling (highest idle-cost item).
6. **Artifact Registry over `gcr.io`.** `cloudbuild.yaml` still targets `gcr.io/$PROJECT_ID`; move to Artifact Registry (cheaper storage, `gcr.io` is legacy). Minor but cost-aligned.

## Recommended Approach

Phase the work so each phase is independently shippable to the emulator and only the final phase touches live. Within each phase, add the hexagonal port/adapter seam for the touched service first, then the behavior change, then the tests — no phase rewrites a service from scratch. Land the two bug fixes (parse-once contract, Gmail push) before any live deploy so production never inherits the expensive behavior. Keep `scripts/check.py` green throughout; every phase ends with emulator integration tests passing.

## Work Plan

1. **Project + cost baseline.** Set `JAA_FIREBASE_PROJECT_ID` for a dedicated project (not a personal/quota project), enable Blaze with budget alerts at $0/10/50, move image pushes to Artifact Registry, document the per-service cost table (expected $0 at idle). DoD: `firebase projects:list` + budget alert proof + updated `cloudbuild.yaml`; no code changes.
2. **Hexagonal seams + model policy.** Introduce `ports` (repository/LLM/queue interfaces) in `sync`, `render_service`, `auto_apply`, `integrations`, `plugins/notion`; move SDK imports into `adapters/`; add one central stage→model map defaulting heavy stages to Gemini Flash low-effort with CI check that no skill bypasses it. DoD: unit tests for policy + ports; `check.py` green; zero behavior change.
3. **Parse-once fix.** Make evidence fingerprint + receipt mandatory `StageTask` inputs in `prepare-job-application`/`manage-job-applications` controller; `validate_candidate_evidence.py` receipt check gates bundle-writing; add a regression test proving unchanged sources → cache hit with no extraction call. DoD: two consecutive runs, second run performs zero parses (asserted in test + controller ledger).
4. **Gmail push ingestion.** Add Gmail `watch`/renew + Pub/Sub push endpoint; orchestrator consumes push events, prefilters run before any scrape/LLM, `ProcessedEmailLedger` dedupes; keep one daily full-scan sweep as backstop. DoD: emulator test (duplicate delivery → single staging), prefilter test (irrelevant mail never reaches scraper), unit tests for watch renewal.
5. **Direct render on Cloud Run.** Expose `POST /compile` on the Cloud Run `latex-worker` (reuse `server.py`), client tries direct HTTPS first with queue fallback; keep local direct path as-is. DoD: `test_direct.py` + new cloud-fallback contract test; latency check (direct p50 < queue p50 on identical fixture).
6. **Event-driven sync, kill the 1-minute poll.** Route Notion work through the existing Firestore trigger; relax `drain_notion_sync_queue` to a 30–60 min safety sweep; keep hourly reconcile. DoD: emulator test (write → trigger → Notion job claimed, no scheduler involved); Functions invocation count comparison.
7. **Live deploy + smoke.** `firebase deploy` (Hosting, rules, indexes, Functions), Cloud Run workers via updated Cloud Build, PWA auth check, one `--live` end-to-end smoke (alert → staged → prepared → rendered → Notion). DoD: smoke receipt + rollback notes (previous Cloud Run revision + `firebase hosting:rollback` path).

## Validation Plan

- Every phase: `python3 scripts/check.py` (full unit suite) plus the phase's new emulator integration tests with `FIRESTORE_EMULATOR_HOST=127.0.0.1:8080` (scrub sandbox `*_PROXY` vars — known gRPC breakage, verified this session).
- Phase 3 highest-risk check: instrument extraction-call count; assert exactly 0 on cache-hit rerun (this is the test that would have caught the reported bug).
- Phase 5 highest-risk check: identical fixture via direct vs queue path — PDFs equivalent, direct measurably faster; overload returns retryable `429`/`503`, never a second concurrent compile.
- Phase 7: single `--live` smoke only after all emulator gates pass; record Functions/Run invocation counts for 24h to confirm idle ≈ $0.
- Manual: PWA login → review-only view of a prepared application; confirm no client path creates approval/submission jobs.

## Risks / Rollback

- Risk: Gmail `watch` expiry (7 days) silently stops ingestion — mitigated by renewal scheduler + daily sweep backstop; rollback to polling interval config.
- Risk: Cloud Run cold start hurts first-render UX — mitigated by client-side queue fallback and documenting expected cold latency; rollback is the queue path, which stays intact.
- Risk: hexagonal refactoring breaks skill scripts that import deep paths — mitigated by keeping old import paths as shims within each phase, removing them only in a final cleanup with `check.py` green.
- Risk: live Firestore costs from a runaway worker — mitigated by lease/claim bounds already in the queue design + budget alerts from phase 1; rollback via previous Cloud Run revision and scheduler disable.
- Rollback per phase: each phase ships behind existing paths (queue render, poll sweep, legacy evidence inputs remain supported until phase 7), so any phase can be reverted to prior behavior without a full redeploy.

## Open Questions

None blocking. Runtime decisions for approval: (1) confirm the target Firebase project ID (current host credentials point at `tinder-jobs-4bf1b` — okay to reuse or prefer a fresh project?); (2) keep Notion as the tracking backend in v1 of live, or go `firestore_only`?
