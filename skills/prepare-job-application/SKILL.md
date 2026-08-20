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

## End-to-end workflow

1. Read `references/workflow.md` and resolve the application root.
2. Start the job-opening extraction branch, candidate-evidence cache lookup, and local rendering preflight concurrently. In managed mode, use the resolved canonical Markdown directory and manifest supplied by `$manage-job-applications`. Reuse a validated hash-keyed evidence cache entry; only run the mapping agent while holding a cache-build lock on a miss. Do not treat a state-root readiness report as required input.
3. Join and validate the job artifact and the derived candidate-evidence index. Preserve the canonical Markdown directory, manifest, and exact source quotations for the next stage. Stop if either branch is partial/blocked or required identity/contact evidence is missing.
   If candidate mapping is unavailable, close the active event, record a
   `kind: wait` event, and return `needs_input`; do not pass provisional output
   to tailoring.
4. Run the complete `$tailor-application-bundle` workflow in reuse mode with the derived per-run evidence index and canonical Markdown context. Require its job-family classification, job-priority/evidence partition, compatible document focus, structural validation, and independent semantic review. Do not replace it with an abbreviated writer-only call.
5. Start temporary rendering concurrently with independent semantic review. Promote the staged artifacts to an immutable version only after the exact bundle receives a validated `accept` verdict. No visual inspection is required.
6. Upsert the Notion record in `TO_APPLY` only after local success.
7. Return the local version directory and Notion page URL. Do not submit the application.

If Notion fails, keep the local bundle and retry synchronization from its manifest; do not regenerate documents. If extraction fails, request pasted content rather than bypassing authentication.
