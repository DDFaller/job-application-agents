---
name: notion-track-application
description: Create, deduplicate, update, and move job application records in the user's connected Notion workspace using the Notion MCP. Use when Codex needs to initialize the Job Applications database, attach current application PDFs, record bundle versions, or update application statuses and dates.
---

# Track Applications in Notion

Use only the connected Notion MCP. Do not request or store a separate Notion API token.

When called from `$prepare-job-application`, accept the shared timing-ledger
path and run ID. Record workspace fetch, database/deduplication lookup, upload
target creation and PDF uploads, page mutation, verification, and any retry as
separate events. A missing Notion connection is a `kind: wait`/blocked event;
leave local artifacts unchanged and preserve the ledger.

`Generated At` is the authoritative timestamp for when the current application
bundle was generated. `Applied At` is the separate submission timestamp; never
derive one from the other. Board audits of bundle completeness or recency and
unanswered-application age calculations must inspect `Generated At`; `Applied
At` remains submission metadata.

Delegate board reviews and stale-card sweeps to `$requeue-unanswered-applications`.
Its normal review mode may change only qualifying `APPLIED` statuses to
`REAPPLY`; an explicitly requested preview, audit, or dry run remains read-only.

## Workflow

1. Call Notion `fetch` with `self` before writes. If it fails, direct the user to `codex mcp login notion` and leave local artifacts unchanged.
2. Follow `references/notion-schema.md` to find or create the `Job Applications` database and its Pipeline board.
3. Fetch the database before every create or update. Use its exact data-source ID and property names.
4. Deduplicate with a parameterized data-source query: canonical `Job URL`, then `Source Job ID` plus company and role.
5. Create or update the page only after the local bundle and manifest exist. For new schema-2 manifests, require `semantic_review.verdict: accept`, an accepted semantic-review quality gate, and matching review/bundle hashes. Existing schema-1 immutable bundles remain eligible only for synchronization retry.
6. Create upload targets for the current resume and motivation-letter PDFs first. If `.tex` source files exist in the versioned directory (from `--render-engine latex`), also create upload targets for `resume.tex` and `letter.tex`. Send all multipart POSTs concurrently, then use all returned attachment Markdown values in the page. Keep the page mutation and post-mutation verification sequential.
7. Preserve unrelated page content. Replace only the stable `Current Documents` section when regenerating.
8. Apply the status/date rules in the reference and fetch the page after mutation to verify it.

## Backfill existing bundles

When a user asks to apply a new document heuristic to an existing status column, query that exact live Notion status first. Audit each card's current local bundle without changing it. Regenerate only noncompliant bundles through `$tailor-application-bundle`; never edit an immutable version. After each replacement has an accepted embedded semantic review and passes deterministic rendering checks, update `Current Version`, `Generated At`, `Local Bundle Path`, `Match Summary`, and only the `Current Documents` section. Preserve status, dates, notes unrelated to the regeneration, and every compliant card unchanged.

Never submit a job application. Never create duplicate database rows to recover from a partial failure.
