# Job Application Agents

Prepare evidence-backed CVs and motivation letters with Codex. The plugin uses several specialized agents in parallel, renders editable LaTeX sources and PDFs, and can track successful bundles in Notion. It never submits applications.

## Recommended installation

This is the easiest installation path for a new user on Linux or macOS. You need:

- Git and Python 3;
- the Codex CLI, already signed in;
- permission to install XeLaTeX and Poppler when setup asks.

Copy and run these commands in a terminal:

```bash
git clone https://github.com/DDFaller/job-application-agents.git
cd job-application-agents
python3 scripts/setup.py
```

When setup displays the operating-system package command, answer `y`. Your computer may ask for its administrator password. Setup then:

- creates the private working directory `~/Documents/job-search`;
- installs and enables the plugin through your personal Codex marketplace;
- grants only the bundled Python scripts the command permissions they need;
- offers to connect the optional Notion integration.

Notion opens a browser login and is only needed for application tracking. You can answer `n` and connect it later with:

```bash
codex mcp login notion
```

Verify the installation:

```bash
python3 scripts/setup.py --check
python3 scripts/check.py
```

Both commands should exit successfully; their summaries should report the required tools as `READY`, the configuration as `OK`, and the tests as passing. If setup could not install XeLaTeX automatically, run the package command it printed and repeat these checks.

Restart Codex or start a new Codex session so it loads the plugin. From the cloned repository, the recommended launcher gives Codex access to the application data directory and enables up to six concurrent workers:

```bash
python3 scripts/launch.py
```

For the first use, provide your existing résumé and facts, then ask:

```text
Initialize my master curriculum from the résumé and facts I provide.
```

After approving that evidence library, start an application with:

```text
Prepare this job application: https://example.com/public-job
```

The coordinator uses specialized agents in parallel, reports every major stage, and sends a heartbeat at least every 45 seconds while work is active.

### Updating an existing installation

Pull the newest version and rerun the idempotent setup:

```bash
cd job-application-agents
git pull
python3 scripts/setup.py
```

Then restart Codex. Setup preserves other personal marketplace entries and replaces only this plugin's installed copy and scoped rules.

## Candidate evidence safety

During the first-use curriculum step above, Codex previews the exact factual evidence update and waits for approval. It then discovers or assesses role profiles in a separate catalog, commissions an independent review, and asks for separate approval before publishing them. Do not copy the example files from this repository into your personal source directory as real facts.

## Editable LaTeX documents

XeLaTeX is the default renderer. Every current application version contains:

- `resume.tex`, `letter.tex`, and `preamble.tex` for editing;
- `resume.pdf` and `motivation-letter.pdf`;
- job, candidate-evidence, and approved role-profile snapshots, review receipts, and a manifest.

You may edit the `.tex` files directly in the version referenced by `current.json`. Rebuild them with:

```bash
python3 skills/tailor-application-bundle/scripts/render_bundle.py \
  --rebuild-version ~/Documents/job-search/applications/company/role/job/v001
```

The rebuild archives a recoverable revision, recompiles both PDFs, checks page count and extractable text, and refreshes hashes. Layout-only changes keep the semantic review valid. Text changes mark it stale and must receive a fresh evidence review before Notion synchronization. Ask Codex to “review my manual LaTeX edits and refresh the current application”; it assigns a separate reviewer and records acceptance against the exact PDF text hashes. Older, non-current versions must not be edited.

The renderer automatically uses the preserved US Letter international template for jobs outside France and the preserved A4 two-column French template for jobs in France. The French profile uses the approved `~/Documents/job-search/sources/profile-photo.jpg`; XeLaTeX is the only rendering engine.

To add a reusable local XeLaTeX résumé design, ask Codex to use
`$add-latex-template` with the project path and a new template slug. The skill
removes sample candidate content, adapts every supported résumé entry type,
compiles an ATS compatibility probe, and previews the complete change before
requiring explicit approval. Select an installed design explicitly with
`render_bundle.py --template <slug>`; omitting the option keeps automatic
geographic template selection. Each application stores an exact snapshot, so later edits to the
shared template affect only future applications.

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
- `maintain-master-curriculum` maintains neutral candidate evidence and a separate approved role-profile catalog.
- `add-latex-template` safely adapts and installs reusable local XeLaTeX résumé projects.
- `tailor-application-bundle` writes, reviews, renders, and rebuilds documents.
- `notion-track-application` deduplicates and tracks bundles.
- `requeue-unanswered-applications` moves qualifying stale `APPLIED` cards to `REAPPLY`.

See [the complete workflow](docs/job-application-workflow.md) for validation, retries, artifacts, and Notion handoff.

## Privacy and safety

Candidate sources and generated applications stay under `~/Documents/job-search` by default and must not be committed. The plugin never invents candidate facts, submits an application, contacts an employer, or marks an application `APPLIED` without a separate explicit request.

## License

MIT
