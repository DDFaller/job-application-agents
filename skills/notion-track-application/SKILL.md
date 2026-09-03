---
name: notion-track-application
description: Create, deduplicate, update, and move job application records in the user's connected Notion workspace using the Notion MCP. Use when Codex needs to initialize the Job Applications database, attach current application PDFs, record bundle versions, or update application statuses and dates.
---

# Track Applications in Notion

Applications can be tracked in Notion via:
1. **Automated Cloud Worker (Recommended)**: Asynchronous queue-based sync via `python3 scripts/sync.py worker-notion --live` or the containerized daemon (`deploy/docker/notion-worker`), which automatically uploads PDFs/LaTeX ZIPs via the 2-step protocol and populates the user's private database.
2. **Interactive Notion MCP**: Direct interactive manipulation in chat using the connected Notion MCP.


`Generated At` is the authoritative timestamp for when the current application
bundle was generated. `Applied At` is the separate submission timestamp; never
derive one from the other. Board audits of bundle completeness or recency and
unanswered-application age calculations must inspect `Generated At`; `Applied
At` remains submission metadata.

Lifecycle updates from `$track-application-outcome` may set interview-stage,
offer, rejection, or withdrawal statuses when explicitly reported or approved
from a source-cited email proposal. `$sync-job-pipeline-view` is a separate
one-way presentation lane and does not own application attachments.

Delegate board reviews and stale-card sweeps to `$requeue-unanswered-applications`.
Its normal review mode may change only qualifying `APPLIED` statuses to
`REAPPLY`; an explicitly requested preview, audit, or dry run remains read-only.

## Workflow

1. Call Notion `fetch` with `self` before writes. If it fails, direct the user to `codex mcp login notion` and leave local artifacts unchanged.
2. Follow `references/notion-schema.md` to find or create the `Job Applications` database and its Pipeline board.
3. Fetch the database before every create or update. Use its exact data-source ID and property names.
4. Deduplicate with a parameterized data-source query: canonical `Job URL`, then `Source Job ID` plus company and role.
5. Create or update the page only after the local bundle and manifest exist. For schema-3 manifests, verify every current artifact hash, require `semantic_review.verdict: accept` and `semantic_review.status: fresh`, and require passed PDF quality gates. A direct LaTeX edit with changed extracted text is blocked until a fresh independent evidence review is recorded. Existing schema-1/2 bundles remain eligible only for synchronization retry under their original rules.
6. Always send the editable LaTeX sources with the PDFs. Create upload targets for the current resume and motivation-letter PDFs plus `resume.tex`, `letter.tex`, and `preamble.tex` (and any renderer utility required by the frozen template). Send the independent uploads concurrently, then use all returned attachment Markdown values in the page. If Notion rejects the `.tex` extension, package the untouched `.tex` files with their exact filenames into a versioned ZIP, upload that ZIP, and include its attachment in `Current Documents`; a PDF-only sync is incomplete. Keep page mutation and post-mutation verification sequential.
7. Preserve unrelated page content. Replace only the stable `Current Documents` section when regenerating, including the current PDFs and the editable-source attachment (individual `.tex` files or the required ZIP fallback).
8. Apply the status/date rules in the reference and fetch the page after mutation to verify it.

## Backfill existing bundles

When a user asks to apply a new document heuristic to an existing status column, query that exact live Notion status first. Audit each card's current local bundle without changing it. Regenerate only noncompliant bundles through `$tailor-application-bundle`. After each replacement has a fresh accepted semantic review and passes deterministic rendering checks, update `Current Version`, `Generated At`, `Local Bundle Path`, `Match Summary`, and only the `Current Documents` section. Preserve status, dates, notes unrelated to the regeneration, and every compliant card unchanged.

Never submit a job application. Never create duplicate database rows to recover from a partial failure.
