---
name: prepare-job-application
description: Orchestrate the complete single-job application workflow by extracting a public opening, combining it with master-curriculum evidence, tailoring a job-family-appropriate application bundle, independently reviewing it, and tracking it through the connected Notion MCP. Use for computing, non-computing, mixed, or minor-job applications from a URL or pasted description.
---

# Prepare Job Application

Coordinate `$extract-job-opening`, `$tailor-application-bundle`, and `$notion-track-application` in that order.

When invoked by `$manage-job-applications`, accept its timing-ledger path and
run ID and append all stage events to that ledger. At minimum record the two
parallel extraction branches, candidate/job validation and repairs, tailoring
and review attempts, staged rendering/promotion, and Notion synchronization. Pass
the same context to nested skills. A blocked gate must close its active event,
open a `kind: wait` event, and finalize the run as `needs_input` until resumed.
All timestamps must be created through `workflow_timing.py`; never fabricate
or backfill event timestamps from worker prose.

## Live status contract

- Before spawning work, report `[company/role or queue label] status: starting` with the planned parallel branches.
- Report every stage start, completion, retry, blocker, and recovery. If no transition occurs for 45 seconds, emit a heartbeat with completed stages, active stages/agents, next stage, blocker, and elapsed time. Never wait longer than 45 seconds while workers are active without checking for updates.
- When invoked as a worker, send each transition and heartbeat to the calling coordinator; the coordinator alone turns them into user-facing commentary. When invoked directly, publish them yourself.
- Use `workflow_timing.py status --file <ledger>` as the factual snapshot. Worker prose may explain a state but must not replace the ledger.
- End with exactly one status: `prepared`, `needs input`, or `failed`, plus artifacts, Notion result, and timing.

## End-to-end workflow

1. Read `references/workflow.md` and resolve the application root.
2. Start the job-opening extraction agent, a distinct candidate-evidence mapping agent on a cache miss, and local XeLaTeX preflight concurrently. Submit all independent work before waiting. In managed mode, use the resolved canonical Markdown directory and manifest supplied by `$manage-job-applications`. Reuse a validated hash-keyed evidence cache entry; only run the mapping agent while holding a cache-build lock on a miss. Do not treat a state-root readiness report as required input. If multi-agent tools or capacity are unavailable, report degraded serial mode immediately and serialize only the unavailable branches.
3. Join and validate the job artifact and the derived candidate-evidence index. Preserve the canonical Markdown directory and source hashes for the next stage. Stop if either branch is partial/blocked or required identity/contact evidence is missing.
   If candidate mapping is unavailable, close the active event, record a
   `kind: wait` event, and return `needs_input`; do not pass provisional output
   to tailoring.
4. Run the complete `$tailor-application-bundle` workflow in reuse mode with the derived per-run evidence index and canonical Markdown context. Require its job-family classification, job-priority/evidence partition, compatible document focus, structural validation, and independent semantic review. Do not replace it with an abbreviated writer-only call.
5. Start temporary XeLaTeX rendering concurrently with the distinct independent semantic-review agent. Promote the staged artifacts only after the exact bundle receives a validated `accept` verdict. No visual inspection is required.
6. Upsert the Notion record in `TO_APPLY` only after local success.
7. Return the local version directory and Notion page URL. Do not submit the application.

If Notion fails, keep the local bundle and retry synchronization from its manifest; do not regenerate documents. If extraction fails, request pasted content rather than bypassing authentication.
