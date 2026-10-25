## Goal

Deploy this repository as a website on Firebase so the owner plus a few trusted people can run the full job-application pipeline from the browser: submit job URLs, upload documents, watch runs, and review and approve drafts. No CLI or local toolchain required for day-to-day use.

## Success Criteria

- A trusted user can sign in on the public URL, submit a job opening URL, and get back rendered CV and letter PDFs without touching a terminal.
- Draft review and approval happen in the browser with the same safety rails as today: nobody can mark a record `APPLIED` or enqueue a submission from client-side code.
- Each user's applications, documents, and integration tokens are isolated per Firebase Auth UID.
- Idle cloud spend stays near $0 (scale-to-zero, Blaze plan) per `deploy/costs.md`; LLM usage remains the only meaningful variable cost.
- `python3 scripts/check.py` passes, and the Firestore emulator flow keeps working for local development.

## Context And Current Facts

- The repo is a local-first CLI/agent system: Python packages in `job_application_agents/`, pipeline stages executed by Codex/Agent Deck workers spawned from this machine (`scripts/launch.py`, `scripts/run_application_batch.py`), local XeLaTeX rendering, and private data under `~/Documents/job-search`.
- A web foundation already exists: `firebase.json` points Firebase Hosting at `deploy/pwa/` (an authenticated, read-only review PWA backed by Firestore realtime listeners), Firestore rules and indexes live in `deploy/firestore/`, and Cloud Functions entry points live in `functions/main.py` (application-write sync, Gmail push ingest, Notion webhook).
- Today's security boundaries (`deploy/architecture.md`, `deploy/firestore/firestore.rules`): queue collections (`renderJobs`, `notionJobs`, `submissionJobs`) deny all client access; users may read and write only their own `users/{uid}/**` subtree; clients cannot promote anything to `APPLIED`; the PWA has no approval or submission path.
- Interactive approval currently lives in `job_application_agents/auto_apply/local_review_server.py`: a token-authenticated server designed for a trusted local network, not the open internet.
- Workers run containerized (`deploy/docker/`: latex, notion, playwright, emulator) with a live-cloud topology already documented, plus deploy helpers (`scripts/deploy_live.sh`, `scripts/deploy_cloud.sh`, `scripts/deploy_cloud_run.py`).
- Offline reporting exists via `scripts/generate_application_report.py`; it is a dashboard, not a live web app, and does not replace the PWA work below.

## Constraints And Non-goals

- Audience is fixed: owner plus a few named trusted users. No public sign-ups, no self-service registration, no multi-tenant SaaS billing in this plan.
- The pipeline's agent stages stay server-side. The browser never receives integration tokens (Gmail, Notion, model keys) and never spawns workers.
- Submission safety is non-negotiable: the `JAA_ENABLE_SUBMISSION` plus `--allow-submit` plus interactive-confirmation gates, and the server-only `submissionJobs` rule, survive this migration unchanged.
- `.env`, Firebase credentials, tokens, candidate data, and generated records are never committed (per `AGENTS.md`).
- Non-goals: native mobile apps, a public job board, automatic submission without supervision, migrating off Firebase, replacing Codex/Agent Deck as the stage harness on the local path.

## Key Decisions

1. **Host on Firebase (per user choice, already wired).** Hosting serves `deploy/pwa/`; Cloud Functions provide the write API; Cloud Run hosts the workers; Firestore remains the state and queue backbone. Rejected: a self-managed VPS, which would reintroduce server patching and uptime duty for no capability gain.
2. **Browser writes go through Callable Functions, never direct queue writes.** The PWA keeps its read-only listeners and gains HTTPS-callable endpoints (approve, edit, submit-job, upload-reference) that run the existing handler logic server-side with the caller's UID. Rejected: opening Firestore rules for client queue writes (destroys the submission-safety boundary) and exposing `local_review_server.py` to the internet (token-only auth, no user identity, LAN design).
3. **Runs execute on Cloud Run workers leasing Firestore queues (Topology B in `deploy/architecture.md`).** The browser only enqueues a run request and watches `users/{uid}/applications` update in realtime. Rejected: executing stages in the browser, which would require shipping the Codex CLI, secrets, and LaTeX to clients.
4. **Stage harness must move from CLI-spawn to API calls on the cloud path.** Local execution keeps spawning Codex/Agent Deck; Cloud Run workers call model APIs directly using the existing per-stage effort profiles (`extractor`, `mapper`, `writer`, `humanizer`, `reviewer` in `run_application_batch.py --profiles`). This is the largest code change in the plan and is isolated behind the harness interface so local behavior is untouched.
5. **Per-user isolation by Auth UID end to end.** Firestore already scopes `users/{uid}/**`; extend the same UID scoping to uploaded documents, run-request routing, worker data roots (one namespace per UID, replacing the single `~/Documents/job-search` assumption), and per-user integration credentials stored server-side only (Secret Manager or encrypted per-user docs decided in Phase 0; never in the PWA bundle).
6. **Auth: Firebase Auth with an explicit UID allowlist for v1.** Current rules let any signed-in user self-provision their own subtree, which is too open even for a small group; add an allowlist gate (custom claims or an `allowlistedUsers` doc checked in rules and in every Callable Function) before opening the URL to anyone.

## Recommended Approach

Grow the existing Firebase foundation in thin, separately shippable slices: first put the current read-only PWA on the public URL with locked-down auth, then add browser-initiated review actions, then job submission and uploads, then cloud execution of the pipeline, then multi-user hardening. Each slice ends with the site live and usable; nothing requires a flag-day cutover, and the local CLI path keeps working throughout. The riskiest slice (cloud stage execution, decision 4) lands after real users already get value from review and submission.

## Work Plan

- **Phase 0 — Baseline and secrets model (prerequisite).** Verify `scripts/check.py` and the emulator stack green; pick Google vs email Auth provider; decide Secret Manager vs encrypted per-user Firestore docs for Gmail/Notion/model credentials; record the UID allowlist and the `europe-west1` region choice from `deploy/costs.md`. Owner: platform.
- **Phase 1 — Ship the read-only site.** Deploy Hosting (`deploy/pwa/`), Auth, and current rules/indexes to the live project; add the UID allowlist gate; confirm sign-in, realtime draft display, and PDF links work from a phone on mobile data. Owner: PWA + platform surfaces.
- **Phase 2 — Review actions in the browser.** Add Callable Functions for approve, request-changes, and field edits that reuse `review_session.py` / `draft_service.py` semantics server-side; keep the `APPLIED` promotion ban and the server-only submission rules byte-for-byte; show action history on the draft card. Owner: functions + PWA surfaces.
- **Phase 3 — Submit jobs and upload documents from the browser.** Add a submit-job endpoint (URL in, extraction enqueued, deduplicated like `ingest_jobs.py`) and resumable uploads (Storage bucket with per-UID prefixes, size and file-type limits, versioned overwrites); wire progress into the existing Firestore listeners. Owner: functions + PWA + Storage rules.
- **Phase 4 — Cloud pipeline execution.** Containerize one stage worker on Cloud Run (scale-to-zero) leasing run requests; implement the API-call harness behind the existing harness interface with the current per-stage effort profiles; port LaTeX rendering to the existing latex-worker image; stream stage transitions and heartbeats to the application doc. Owner: orchestration + render-service + deploy surfaces.
- **Phase 5 — Trusted-group hardening.** Per-user Gmail/Notion credential onboarding, per-UID worker namespaces and quotas, audit logging of approvals, $0/$10/$50 billing alerts, and a supervised-submission flow that preserves the existing triple gate. Owner: platform + sync/integrations surfaces.
- **Phase 6 — Ops and rollout.** Promote `deploy_live.sh`/`deploy_cloud_run.py` into a documented release checklist (Hosting + rules + indexes + functions + workers, in that order), record rollback per slice, and keep the emulator path as the pre-deploy gate. Owner: platform.

## Validation Plan

- Each phase: `python3 scripts/check.py` passes; Firestore emulator run of the touched flow passes; deploy to the live project and verify from a signed-in phone browser on mobile data (the PWA's real client).
- Phase 1: sign-in required banner shows for anonymous users; allowlisted UID sees own drafts only; second test UID sees nothing of the first user's data.
- Phase 2: approve and edit round-trip to Firestore; direct client writes to `renderJobs`, `notionJobs`, `submissionJobs`, and any write setting `status == "APPLIED"` are rejected by rules (negative tests against the emulator).
- Phase 3: duplicate job URL submitted twice yields one application; oversized and wrong-type uploads rejected; upload of user A unreadable with user B credentials.
- Phase 4: end-to-end run from URL submit to rendered PDFs entirely in cloud; kill-and-resume of a worker mid-run recovers via lease expiry without duplicate renders.
- Phase 5: revoking a user's allowlist entry blocks their reads and calls within minutes; billing alerts fire on the test threshold.
- Highest-risk validation: Phase 4's harness swap producing indistinguishable bundle quality versus the local CLI path on the same fixture jobs; run both and diff the evidence citations, not just the prose.

## Risks / Rollback

- **Credential leak via browser.** Mitigation: tokens never leave the server; PWA bundle audited for secret references before each release. Rollback: revoke rotated secret, redeploy previous Hosting version (every release is versioned).
- **Accidental submissions from the web.** Mitigation: submission path keeps the triple gate and has no Callable Function in this plan. Rollback: rules redeploy is a single command and denies by default.
- **Runaway LLM or Cloud Run cost.** Mitigation: per-UID quotas, scale-to-zero everywhere, billing alerts from `deploy/costs.md`. Rollback: set worker `maxInstances: 0` to freeze execution without touching data.
- **Harness swap degrades bundle quality.** Mitigation: fixture-based diffing in Phase 4 before any user traffic uses the cloud path. Rollback: route run requests back to the local worker; the queue design allows both consumers.
- **Multi-user data bleed.** Mitigation: UID-scoped rules plus negative tests per phase. Rollback: remove the allowlist entry; data stays partitioned by UID.

## Open Questions

None. Audience (trusted few), scope (full pipeline in browser), and hosting (Firebase) were confirmed before drafting; remaining choices (Auth provider, secrets store) are Phase 0 decisions with safe defaults (Google provider, Secret Manager) and do not block the plan.
