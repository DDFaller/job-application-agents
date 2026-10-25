---
name: manage-job-applications
description: "Coordinate durable batches with one Agent Deck session per semantic stage, strict artifact contracts, stage-only retries, and controller-owned tracking. Never submit applications, expose credentials, mutate candidate evidence, or mark records APPLIED."
---

# Manage Job Applications

Act as the control plane. Do not perform semantic application work and do not
ask a worker to coordinate or spawn other agents. Use
`job_application_agents.orchestration.BatchController`; Agent Deck is the
default executor and the direct-process executor is an interchangeable local
fallback.

## Non-negotiable boundaries

- Resolve the private data root with `resolve_data_root`: explicit CLI value,
  `JAA_DATA_ROOT`, or default `~/Documents/job-search`.
- Run one global preflight before launching a model: discover and validate role-profile
  sources under `~/Documents/job-search/sources/<role-profile>/` (including `pre-formatted.tex`),
  verify local render prerequisites, and optionally support legacy source manifests.
- Keep Notion, Gmail, Firebase, browser, and provider credentials in the
  coordinator process. Never put secrets in prompts, task artifacts, Agent
  Deck commands, logs, or ledgers.
- Workers may write only inside their attempt output directory and exact
  `result_path`. Only the controller writes batch state and timing ledgers.
- Never submit, contact an employer, invoke auto-apply, or mark `APPLIED`.

## Worker input boundaries

Apply the [stage input scope](references/stage-input-scope.md) to every preparation
worker. Supply needed private dependencies as exact hashed inputs; a missing
dependency belongs back with the coordinator, not in a worker search of old
applications. Keep deduplication and historical discovery in the coordinator.

Distinguish instruction compliance from runtime enforcement. `--add-dir`, a
terminal sandbox and credential-environment filtering do not prove native file
tools cannot read unrelated private records. For a task requiring enforced read
isolation, first verify allowed reads and denied out-of-scope reads using
synthetic files through both native file tools and shell execution. If that
boundary is unavailable or a probe succeeds outside scope, stop before exposing
real candidate data and report the unsupported control. Command approval alone
does not mediate every native file read; do not claim otherwise.

On observed scope drift, preserve a redacted trace and classify the cause before
retrying in a fresh session. An actual out-of-scope read stops the worker. Respect
the user's repair limit; do not keep injecting corrections into a contaminated
context or change the judging criteria to accept it.

## Flat stage graph

For each job, run these dependent stages. Each gets a fresh Agent Deck session,
a versioned `StageTask`, one named skill, validated input artifacts, and one
exact `StageResult` path:

1. `job-extraction` with `$extract-job-opening`.
2. `profile-selection` with `$select-application-profile`: use schema 2, compare the approved library against the extracted duties and constraints, and expose the controller-calculated fit score, range, evidence coverage and gaps. Weak/unknown fit becomes user review, never automatic skip.
3. `bundle-writing` with `$tailor-application-bundle`, grounded directly in the
   selected role profile's source markdown files and using `pre-formatted.tex` as the
   layout, structure, and phrasing reference.
4. `copy-humanization` with `$humanize-application-copy`.
5. `independent-review` with `$review-application-bundle`.
6. `render-promotion` with `$render-application-bundle` after acceptance.
7. Coordinator-only deduplicated `$notion-track-application` synchronization,
   if its connected integration is available and tracking was requested.

Legacy schema-3 batches may optionally include the batch-shared `candidate-evidence`
stage (`$map-candidate-evidence`), but standard batches streamline directly from
job-extraction to bundle-writing.

`$prepare-job-application` describes this DAG; it is not another parent worker.
`$maintain-master-curriculum` is outside the application DAG and is never
invoked merely because application inputs are missing or stale.

## Fit decisions

New batches pause at `awaiting_fit_review`. Show the user each job's supported
score out of 100, evidence coverage, important gaps and constraints. Inspect with
`python3 scripts/review_job_fit.py --state <batch> --data-root <root>` and record
the user's choice with `--job <key> --decision prepare|skip --selection-sha256
<reviewed-hash>`, then resume the batch. Missing evidence is not proven inability.
When the user has already explicitly selected jobs for preparation/application,
pass `--prepare-selected` at batch creation; show the same fit findings and
continue preparing without asking again. This flag covers document preparation;
submission is a separate authorized workflow. Do not set an automatic threshold
unless supplied by the user. `--automatic-fit-threshold` reports eligibility only
and never grants permission to submit. Preserve the fit report through review.

## Scheduling and retries

- Limit concurrency by active jobs, not estimated nested-agent slots. Only one
  stage runs for a job at a time; independent jobs may run concurrently.
- Poll result contracts and Agent Deck state at least every 45 seconds. Report
  transitions, retries, blockers, and concise heartbeats.
- Success requires matching schema and task identity, validated artifact paths
  under the data root, and matching SHA-256 hashes. Chat prose and session
  `idle` are not completion.
- Automatic retries require a typed blocker with `retryable: true` and attempts
  remaining. Missing artifacts or an absent `StageResult` do not establish
  retryability: stop and report the failure until its cause is classified.
  For an authorized retry, restart only the failed stage in a fresh session and
  attempt directory; keep accepted upstream artifacts.
- A non-retryable blocker becomes `needs_input`; exhausted retryable failures
  become `failed`; stopped jobs become `cancelled`. Finalized ledgers are
  immutable, so later resumed work gets a fresh run and ledger.

## Provider command rules

Build commands through `orchestration.worker_command`, never ad-hoc shell
strings. Agy uses `--print` and always receives `--add-dir <data-root>`.
 Do not pass `--effort` to Agy Claude models. Codex uses `codex exec`, explicit `-C`, and `--add-dir`. Auto-approval is opt-in and confined to scoped directories.

OpenCode runs through the Agent Deck worker wrapper with `opencode run`, an
explicit `provider/model`, `--dir <repository-root>`, `--pure`, and JSON event
output. Interactive batches add OpenCode's interactive run mode so an operator
can supervise the child agent through the Agent Deck PTY. Stage effort maps to
OpenCode's `--variant`; auto-approval remains opt-in. The binary is resolved
from `OPENCODE_BIN`, PATH, or `~/.opencode/bin/opencode`.

Muse runs headless through `muse exec` with `--workspace <data-root>` (a
single policy-gated root; data-only scoping mirroring agy), `--model`, and
`--reasoning-effort` for stage effort. Interactive batches use the bare
`muse` session form for supervision. Auto-approval is opt-in via
`--approval-mode never` and stays confined to the data root.

## Completion

After local preparation, the controller may use its authenticated Notion
connector to update `TO_APPLY` while preserving status and unrelated content.
If tracking fails, retry tracking from the accepted manifest; do not regenerate
documents. Return one row per job with terminal status, stage, attempts,
artifact directory or typed blocker, and timing summary.

New batches require an approved, source-current positioning library. Use automatic
selection by default; never force a backend profile across unrelated openings.
An explicit profile must still be assessed and its gaps reported. New schema-2
runs skip only when the user chooses to skip; schema-1 legacy decisions retain
their original meaning. Do not render, prefill or sync skipped jobs. Persist the stage
sequence when creating a batch and preserve the original sequence on resume.
Legacy custom sequences must be supplied explicitly when resuming schema-1 state.
