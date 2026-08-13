---
name: prepare-job-application
description: Orchestrate the complete single-job application workflow by extracting a public opening, combining it with master-curriculum evidence, tailoring a job-family-appropriate application bundle, independently reviewing it, and tracking it through the connected Notion MCP. Use for computing, non-computing, mixed, or minor-job applications from a URL or pasted description.
---

# Prepare Job Application

Coordinate `$extract-job-opening`, `$tailor-application-bundle`, and `$notion-track-application` in that order.

## End-to-end workflow

1. Read `references/workflow.md` and resolve the application root.
2. Start two clean-context Luna agents concurrently: one extracts the opening and one extracts candidate evidence from local documents.
3. Join and validate both artifacts. Stop if either is partial/blocked or required identity/contact evidence is missing.
4. Run the complete `$tailor-application-bundle` workflow. Require its job-family classification, job-priority/evidence partition, compatible document focus, structural validation, and independent semantic review. Do not replace it with an abbreviated writer-only call.
5. Render and inspect the immutable artifacts only after the tailoring review verdict is `accept`.
6. Upsert the Notion record in `TO_APPLY` only after local success.
7. Return the local version directory and Notion page URL. Do not submit the application.

If Notion fails, keep the local bundle and retry synchronization from its manifest; do not regenerate documents. If extraction fails, request pasted content rather than bypassing authentication.
