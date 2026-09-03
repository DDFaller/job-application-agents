# Job Application Agents

Prepare evidence-backed CVs and motivation letters with Codex. The plugin uses several specialized agents in parallel, renders editable LaTeX sources and PDFs, and can track successful bundles in Notion. It never submits applications.

## Recommended installation

This is the easiest installation path for a new user on Linux or macOS. You need:

- Git and Python 3;
- the Codex CLI, already signed in;
- Docker with Docker Compose;
- the local LaTeX toolchain: `latexmk`, XeLaTeX, `kpsewhich`, and Poppler.

On Fedora, install the local toolchain before setup with:

```bash
sudo dnf install latexmk texlive-xetex poppler-utils
```

On Debian or Ubuntu, use:

```bash
sudo apt-get install latexmk texlive-xetex poppler-utils
```

Copy and run these commands in a terminal:

```bash
git clone https://github.com/DDFaller/job-application-agents.git
cd job-application-agents
python3 scripts/setup.py
```

Setup then:

- detects missing local LaTeX tools and offers to install them with the detected package manager;
- creates the private working directory `~/Documents/job-search`;
- installs the Python render-service client into `.venv`;
- verifies the local LaTeX toolchain used by VS Code LaTeX Workshop and local rendering;
- offers to start the local Firestore emulator and isolated XeLaTeX worker;
- installs and enables the plugin through your personal Codex marketplace;
- grants only the bundled Python scripts the command permissions they need;
- offers to connect the optional Notion integration.

Notion opens a browser login and is only needed for application tracking. You can answer `n` and connect it later with:

```bash
codex mcp login notion
```

## Configuration examples

The repository includes [config.example.jsonc](config.example.jsonc) for storage
and [render.example.jsonc](render.example.jsonc) for rendering. They are
commented references, not runtime files: create comment-free JSON files at
`~/.config/job-application-agents/config.json` and
`~/.config/job-application-agents/render.json` when you need overrides.

Environment variables such as `JAA_DATA_ROOT`, `JAA_FIREBASE_PROJECT_ID`,
`JAA_RENDER_MODE`, `NOTION_DATABASE_ID`, and the existing Gmail variables continue to take
precedence over file settings. The only currently available render engine is
`xelatex`; rendering is local-first by default, while `JAA_RENDER_MODE=cloud`
selects the Firestore worker and `auto` falls back to it when local tools are
unavailable. Selecting the reserved `cvrender` value fails until its adapter
is installed.

Verify the installation:

```bash
python3 scripts/setup.py --check
python3 scripts/check.py
```

Both commands should exit successfully; their summaries should report the required tools as `READY`, the configuration as `OK`, and the tests as passing. The worker image contains its own isolated XeLaTeX and Poppler runtime, while the local toolchain powers local-first rendering and VS Code editing.

`setup.py --check` also reports the local LaTeX tools required for the editable
VS Code workflow. If you intentionally use only the cloud renderer, pass
`--skip-local-latex` to setup and its check, and set `JAA_RENDER_MODE=cloud`.

Start or inspect the rendering services independently with:

```bash
.venv/bin/python scripts/render_service.py up
.venv/bin/python scripts/render_service.py status
```

These commands use an isolated Firebase demo project and never contact live Firebase. To connect an existing project, create Application Default Credentials and deploy the required queue indexes once:

```bash
gcloud auth application-default login
export JAA_FIREBASE_PROJECT_ID="your-firebase-project-id"
.venv/bin/python scripts/render_service.py configure --live
.venv/bin/python scripts/render_service.py up --live
```

Live mode mounts the ADC file read-only into the worker. Do not commit credentials. Compiled artifacts remain under `~/Documents/job-search/.render-service/artifacts`, so Firebase Storage and its Blaze-plan requirement are not needed.

Start Codex against the same live project with `python3 scripts/launch.py --live`. Without `--live`, the launcher always selects the isolated local emulator. The launcher passes only the selected repository and private data root; it does not forward integration tokens to child agents.

Restart Codex or start a new Codex session so it loads the plugin. From the cloned repository, the recommended launcher gives Codex access to the application data directory and enables up to six concurrent workers. A complete cache-miss application reserves five of those workers (including the constrained Humanizer pass) and the default concurrency guard runs one complete application at a time. Integration credentials are kept out of worker environments.

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

## Firebase User Layer & Cloud Sync

The platform provides user-isolated Firestore synchronization under `users/{userId}/` for all curricula, role profiles, and application bundles.

### Automatic Firestore ↔ Notion application sync

Application documents are canonical in Firestore. Firestore-triggered Firebase
Functions enqueue projection jobs to the existing Notion worker. The Notion
connection can also send signed `page.properties_updated` webhooks to the
`notion_webhook` function; only `Status`, `Applied At`, `Next Action At`, and
`Notes` are accepted back into Firestore. An hourly scheduled function repairs
missed events and missing/stale cards.

Configure the deployment with:

```bash
firebase functions:secrets:set NOTION_TOKEN
firebase deploy --only functions
```

If `NOTION_TOKEN` is not configured yet, bootstrap the webhook first:

```bash
firebase deploy --only functions:notion_webhook
```

Then, in the Notion connection settings, create and verify a webhook
subscription pointing to the deployed `notion_webhook` HTTPS URL. The first
verification request is stored server-side automatically, so no separate
verification secret is needed. Configure `NOTION_TOKEN` and deploy the
remaining functions afterward. Subscribe to
`page.created`, `page.properties_updated`, `page.content_updated`, and
`page.deleted`. The deployed `drain_notion_sync_queue` scheduler drains
`notionJobs` every minute. A local worker (`scripts/start_workers.sh`) or the
deployed worker service may also be used; Firestore leases prevent duplicate
processing.

### Sync CLI Commands

```bash
# Check sync status and drift between local workspace and Firestore
python3 scripts/sync.py status

# Push all local curricula, profiles, and applications to Firestore
python3 scripts/sync.py push --all

# Push specific components
python3 scripts/sync.py push --curriculum
python3 scripts/sync.py push --profiles
python3 scripts/sync.py push --applications

# Pull remote cloud data down to your local workspace
python3 scripts/sync.py pull --all

# Connect to live Firebase
python3 scripts/sync.py push --all --live
```

User identity is resolved automatically from `JAA_USER_ID`, local `.config.json`, ADC account credentials, or `--user-id <UID>`.

## Editable LaTeX documents

XeLaTeX runs locally by default using the same bounded compiler contract as
the compile-only Docker worker. Set `JAA_RENDER_MODE=cloud` to use Firestore.
The core freezes the TeX sources and assets, verifies application-specific
reading order, and retains ownership of version promotion. Every current
application version contains:

- `resume.tex`, `letter.tex`, and `preamble.tex` for editing;
- `resume.pdf` and `motivation-letter.pdf`;
- job, candidate-evidence, and approved role-profile snapshots, review receipts, and a manifest.

You may edit the `.tex` files directly in the version referenced by `current.json`. Rebuild them with:

```bash
.venv/bin/python skills/tailor-application-bundle/scripts/render_bundle.py \
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

Repository validation and unit tests:

```bash
python3 scripts/check.py
```

Run the full automated test suite (Firebase unit tests -> LaTeX worker unit tests -> XeLaTeX emulator integration test):

```bash
.venv/bin/python scripts/render_service.py test
```

Or run each stage step-by-step:

```bash
# 1. Unit tests only
.venv/bin/python scripts/render_service.py test --unit-only

# 2. Start services
.venv/bin/python scripts/render_service.py up
export JAA_FIREBASE_PROJECT_ID=demo-job-application-agents
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8080

# 3. Emulator Firestore repository tests
.venv/bin/python -m unittest job_application_agents.render_service.test_firestore -v

# 4. Real XeLaTeX integration test
.venv/bin/python scripts/check_render_service.py
```

GitHub Actions runs these checks on every push and pull request. The separate `Firebase Live Smoke Test` workflow is manual, protected, and authenticates with GitHub OIDC instead of a stored service-account key.

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
- `onboard-job-search` initializes candidate facts and search preferences.
- `rank-job-shortlist` batch-scores and prioritizes staged openings.
- `track-application-outcome` records lifecycle events and drafts follow-ups.
- `sync-application-email` proposes source-cited status changes from email.
- `prepare-interview` builds preparation from the exact submitted bundle.
- `expand-candidate-profile` proposes additive evidence from linked sources.
- `plan-upskilling` turns repeated job gaps into a learning plan.
- `generate-application-report` creates an offline HTML dashboard.
- `sync-job-pipeline-view` publishes an optional one-way Notion view.
- `add-job-portal` generates and validates a public market-specific portal adapter.

See [the complete workflow](docs/job-application-workflow.md) for validation, retries, artifacts, and Notion handoff.

## Privacy and safety

Candidate sources and generated applications stay under `~/Documents/job-search` by default and must not be committed. The plugin never invents candidate facts, bypasses portal access controls, or contacts an employer. Application preparation is hands-off and cannot submit. Browser form filling defaults to dry-run; a separately enabled submission deployment additionally requires interactive user confirmation, and `APPLIED` is recorded only after a verified submission receipt.

## License

MIT
