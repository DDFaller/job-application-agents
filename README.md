# Job Application Agents

Prepare evidence-backed CVs and motivation letters with Codex. The plugin uses several specialized agents in parallel, renders editable LaTeX sources and PDFs, and can track successful bundles in Notion. It never submits applications.

## Quick start

You need Python 3 and the Codex CLI. Clone this repository, open a terminal in it, and run:

```bash
python3 scripts/setup.py
```

Setup explains every change before making it. It can offer the appropriate XeLaTeX and Poppler package command, creates `~/Documents/job-search`, installs the local plugin, writes narrow command rules, and offers to connect Notion.

Restart Codex after setup, then launch it with the application data directory in scope:

```bash
python3 scripts/launch.py
```

Ask naturally:

```text
Prepare this job application: https://example.com/public-job
```

The coordinator reports every major stage and sends a heartbeat at least every 45 seconds while work is active.

## First candidate setup

Before the first application, ask Codex:

```text
Initialize my master curriculum from the résumé and facts I provide.
```

Codex previews the exact evidence library update and waits for approval. Do not copy the example files from this repository into your personal source directory as real facts.

## Editable LaTeX documents

XeLaTeX is the default renderer. Every current application version contains:

- `resume.tex`, `letter.tex`, and `preamble.tex` for editing;
- `resume.pdf` and `motivation-letter.pdf`;
- job and candidate-evidence snapshots, review receipts, and a manifest.

You may edit the `.tex` files directly in the version referenced by `current.json`. Rebuild them with:

```bash
python3 skills/tailor-application-bundle/scripts/render_bundle.py \
  --rebuild-version ~/Documents/job-search/applications/company/role/job/v001
```

The rebuild archives a recoverable revision, recompiles both PDFs, checks page count and extractable text, and refreshes hashes. Layout-only changes keep the semantic review valid. Text changes mark it stale and must receive a fresh evidence review before Notion synchronization. Ask Codex to “review my manual LaTeX edits and refresh the current application”; it assigns a separate reviewer and records acceptance against the exact PDF text hashes. Older, non-current versions must not be edited.

RenderCV remains an optional compatibility fallback. Install it with `python3 scripts/setup.py --with-rendercv` and select it explicitly with `--render-engine rendercv`.

## Diagnose and test

Read-only setup diagnosis:

```bash
python3 scripts/setup.py --check
```

Repository validation:

```bash
python3 scripts/check.py
```

If Notion is disconnected, run `codex mcp login notion`. If Codex does not show the updated plugin, rerun setup and start a new Codex session.

## Included workflows

- `manage-job-applications` coordinates queues and live progress.
- `prepare-job-application` runs one complete multi-agent application.
- `extract-job-opening` extracts one public posting.
- `maintain-master-curriculum` maintains approved candidate evidence.
- `tailor-application-bundle` writes, reviews, renders, and rebuilds documents.
- `notion-track-application` deduplicates and tracks bundles.
- `requeue-unanswered-applications` moves qualifying stale `APPLIED` cards to `REAPPLY`.

See [the complete workflow](docs/job-application-workflow.md) for validation, retries, artifacts, and Notion handoff.

## Privacy and safety

Candidate sources and generated applications stay under `~/Documents/job-search` by default and must not be committed. The plugin never invents candidate facts, submits an application, contacts an employer, or marks an application `APPLIED` without a separate explicit request.

## License

MIT
