---
name: prepare-job-application
description: Orchestrate one job application by extracting a public opening, combining neutral master-curriculum evidence with an approved role-profile catalog, tailoring and independently reviewing an editable LaTeX bundle, and tracking it in Notion. Use for computing, non-computing, mixed, or minor-job applications. Pause with an explained profile proposal when no approved profile fits.
---

# Prepare Job Application

Coordinate `$extract-job-opening`, `$tailor-application-bundle`, and `$notion-track-application` in that order.

When invoked by `$manage-job-applications`, accept its timing-ledger path and
run ID and append all stage events to that ledger. At minimum record job and
candidate extraction, profile resolution, all validation and repair, tailoring
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
2. Start job extraction, candidate-evidence mapping/cache lookup, approved-profile resolution, and local XeLaTeX preflight concurrently. Submit all independent work before waiting. In managed mode, use the exact source and profile manifests supplied by `$manage-job-applications`. Reuse a validated evidence cache entry; only run the mapping agent while holding the cache-build lock on a miss. If multi-agent capacity is unavailable, report degraded serial mode.
3. Join and validate the job, schema-3 candidate evidence, and approved role-profile catalog. Require typed work/education records and an exact match between candidate sources and the catalog's source binding. Stop if any input is partial, stale, blocked, or missing identity/contact evidence.
   If candidate mapping is unavailable, close the active event, record a
   `kind: wait` event, and return `needs_input`; do not pass provisional output
   to tailoring.
4. Run the complete `$tailor-application-bundle` workflow in reuse mode with candidate evidence and the approved catalog. Require profile ranking, claim scores, evidence partition, structural validation, and independent review. If it returns a validated profile proposal, record `needs_input`, return its reason and path, and stop before rendering or Notion.
5. Start temporary XeLaTeX rendering concurrently with the distinct independent semantic-review agent. Use `--profile auto`: clearly French locations receive the preserved A4 sidebar template and all others receive the compact international template. The France profile requires the approved canonical candidate photo. Promote the staged artifacts only after the exact bundle receives a validated `accept` verdict. No visual inspection is required.
6. Upsert the Notion record in `TO_APPLY` only after local success. The Notion synchronization must include the current resume and motivation-letter PDFs and the editable LaTeX sources (`resume.tex`, `letter.tex`, and `preamble.tex`); when individual `.tex` uploads are unsupported, attach a versioned ZIP containing those exact raw files.
7. Return the local version directory and Notion page URL. Do not submit the application.

If Notion fails, keep the local bundle and retry synchronization from its manifest; do not regenerate documents. If extraction fails, request pasted content rather than bypassing authentication.
