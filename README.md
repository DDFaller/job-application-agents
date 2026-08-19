# Job Application Agents

A shareable Codex plugin for evidence-backed job applications. It uses small, specialized skills and clean-context subagents instead of one large prompt.

## Included skills

- `manage-job-applications` routes requests and delegates an application queue.
- `prepare-job-application` coordinates a complete single-job workflow.
- `extract-job-opening` turns one public posting into validated evidence-backed JSON.
- `maintain-master-curriculum` maintains the approved candidate evidence library.
- `tailor-application-bundle` writes, independently reviews, validates, and renders application documents.
- `notion-track-application` deduplicates and tracks applications through Notion MCP.
- `requeue-unanswered-applications` reviews the live board and automatically moves `APPLIED` cards to `REAPPLY` at the 14-day `Generated At` threshold.

See [the complete job-application workflow](docs/job-application-workflow.md)
for the execution order, agent responsibilities, validation scripts, expected
artifacts, retry rules, and Notion handoff.

The plugin never submits applications. Candidate claims must be supported by approved local evidence.

## Requirements

- Codex with plugin, skill, and subagent support.
- An authenticated Notion MCP connection for tracking: `codex mcp login notion`.
- Python 3 for validators and RenderCV plus groff for PDF rendering.

## Install

Install the repository as a Codex plugin using the plugin installation flow available in your Codex client. After installation, authenticate Notion and invoke:

```text
Use $manage-job-applications to prepare these job openings and track the successful bundles in Notion.
```

For local development, point Codex at this plugin directory. Keep candidate sources outside the repository; the skills default to `~/Documents/job-search/`.

## Privacy and safety

Do not commit candidate documents, generated applications, tokens, cookies, or `.env` files. The included `.gitignore` excludes the common local data directories.

## License

MIT
