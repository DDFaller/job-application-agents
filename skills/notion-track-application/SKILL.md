---
name: notion-track-application
description: Create, deduplicate, update, and move job application records in the user's connected Notion workspace using the Notion MCP. Use when Codex needs to initialize the Job Applications database, attach current application PDFs, record bundle versions, or update application statuses and dates.
---

# Track Applications in Notion

Use only the connected Notion MCP. Do not request or store a separate Notion API token.

## Workflow

1. Call Notion `fetch` with `self` before writes. If it fails, direct the user to `codex mcp login notion` and leave local artifacts unchanged.
2. Follow `references/notion-schema.md` to find or create the `Job Applications` database and its Pipeline board.
3. Fetch the database before every create or update. Use its exact data-source ID and property names.
4. Deduplicate with a parameterized data-source query: canonical `Job URL`, then `Source Job ID` plus company and role.
5. Create or update the page only after the local bundle and manifest exist.
6. Upload the current resume and motivation-letter PDFs with `create_file_upload`, one multipart POST per returned URL, then use the returned attachment Markdown in the page.
7. Preserve unrelated page content. Replace only the stable `Current Documents` section when regenerating.
8. Apply the status/date rules in the reference and fetch the page after mutation to verify it.

## Backfill existing bundles

When a user asks to apply a new document heuristic to an existing status column, query that exact live Notion status first. Audit each card's current local bundle without changing it. Regenerate only noncompliant bundles through `$tailor-application-bundle`; never edit an immutable version. After each replacement passes review and visual inspection, update `Current Version`, `Generated At`, `Local Bundle Path`, `Match Summary`, and only the `Current Documents` section. Preserve status, dates, notes unrelated to the regeneration, and every compliant card unchanged.

Never submit a job application. Never create duplicate database rows to recover from a partial failure.
