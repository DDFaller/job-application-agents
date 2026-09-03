---
name: sync-job-pipeline-view
description: Publish a one-way Notion view of ranked public jobs and tracked applications from local or Firestore state. Use when the user wants a glanceable pipeline view in Notion. Never make Notion the source of truth or sync changes back automatically.
---

# Sync Job Pipeline View

1. Require authenticated Notion MCP and gracefully stop if unavailable.
2. Read ranked jobs and tracked applications from the current local/Firestore
   manifests. Sync jobs above score 60 by default plus every tracked
   application; support `--all` and `--min-score N`.
3. Deduplicate by canonical URL, source ID, and company/role. Create or update
   only the defined presentation properties and write-once briefing content.
4. Never rank, tailor, submit, or alter local records. A `--rebuild` request
   is required before replacing an existing briefing page.
5. Return created, updated, skipped, and failed rows with page URLs.

This complements `$notion-track-application`, which owns application document
attachments and lifecycle synchronization.
