# Agent Deck Batch Init

Run these pre-commands before launching a job-application batch so workers
start with binaries, auth, directories, and permissions established and never
wait on an interactive prompt. All commands assume `REPO` is this checkout
and `DATA_ROOT` is the private working directory (default
`~/Documents/job-search`).

```bash
REPO=$HOME/job-application-agents
DATA_ROOT=${JAA_DATA_ROOT:-$HOME/Documents/job-search}
```

## 0. Common (every harness)

```bash
# Runtime + repo sanity
test -x $REPO/.venv/bin/python || python3 $REPO/scripts/setup.py

# Agent Deck control plane is reachable
agent-deck list --json | head -5

# Private data root, role-profile sources, and render prerequisites.
# Mirrors BatchPreflight: DATA_ROOT and DATA_ROOT/sources must exist.
test -d "$DATA_ROOT" && test -d "$DATA_ROOT/sources" \
  && echo "data-root OK: $DATA_ROOT"
ls "$DATA_ROOT/sources"   # expect a dir per role profile, e.g. backend-engineer
python3 $REPO/skills/tailor-application-bundle/scripts/render_bundle.py --preflight \
  && echo "render OK"

# Jobs file is a valid URL list
python3 -c "import json; print(len(json.load(open('$DATA_ROOT/jobs.json'))), 'jobs')"

# Coordinator credentials stay in THIS shell only. The launcher strips
# NOTION_*, GMAIL_*, GOOGLE_APPLICATION_CREDENTIALS, FIREBASE_TOKEN,
# BROWSER_COOKIE, and PLAYWRIGHT_STORAGE_STATE from every worker environment,
# so export them here (or in .env), never in task files or prompts.
```

## 1. agy (default `--harness agy`)

```bash
command -v agy && agy --version   # verified: 1.1.27
```

- Auth: `agy --help` exposes no login subcommand. Configure its provider
  credentials in the coordinator environment before launch.
- Permissions: workers get `--add-dir <data-root>` only. Unattended runs need
  `--unattended` (adds `--dangerously-skip-permissions`).
- Effort: never combine `--effort` with Claude models — the launcher rejects it.

## 2. codex (`--harness codex`)

```bash
codex --version               # verified: codex-cli 0.153.1
codex login status            # expect: Logged in using ChatGPT (or your method)
```

- One-time login: `codex login` (re-run the status probe after).
- Permissions: workers run `codex exec -C <repo> --add-dir <data-root>` in
  `workspace-write` sandbox (network on for `job-extraction` only).
  Unattended runs need `--unattended` (adds
  `--dangerously-bypass-approvals-and-sandbox`).

## 3. opencode (`--harness opencode`)

```bash
command -v opencode || export OPENCODE_BIN=$HOME/.opencode/bin/opencode
opencode --version            # verified: 1.18.29
opencode auth list            # lists providers/credentials; needs a writable HOME
```

- Models must use `provider/model` format (e.g. `openai/gpt-5.6`); anything
  else is rejected at validation.
- Permissions: workers run `opencode run --dir <repo> --pure` with JSON event
  output. Unattended runs need `--unattended` (adds `--auto`).
- Interactive batches use `opencode run --interactive` for PTY supervision.

## 4. muse (`--harness muse`)

```bash
command -v muse && muse --version   # verified: Muse Code 1.0.3
```

- One-time auth (no headless status probe exists): `muse login` (browser
  approval), or export `META_API_KEY` in the coordinator shell — the env key
  takes priority over the account login. Re-run only if workers report auth
  blockers.
- Permissions: workers run `muse exec --workspace <data-root>` (single
  policy-gated root, data-only scoping like agy) with `--model` and
  `--reasoning-effort` for stage effort. Unattended runs need `--unattended`
  (adds `--approval-mode never`).
- Interactive batches use the bare `muse` session form for supervision.

## 5. Launch

```bash
# Smoke: one controller tick in this shell, no host session
.venv/bin/python scripts/run_application_batch.py \
  --jobs "$DATA_ROOT/jobs.json" --role-profile backend-engineer \
  --harness muse --model muse-spark --unattended --once

# Full run: spawn the Agent Deck host; per-stage subworkers launch as their
# own sessions under --group (default: job-applications)
.venv/bin/python scripts/run_application_batch.py \
  --jobs "$DATA_ROOT/jobs.json" --role-profile backend-engineer \
  --harness muse --model muse-spark --unattended --launch-host
# -> {"event": "host-launched", "batch": ..., "state": ..., "host": ...}

# Follow up / resume from anywhere
agent-deck list --json | python3 -c "import json,sys; [print(s['id'], s['title']) for s in json.load(sys.stdin)]"
.venv/bin/python scripts/run_application_batch.py --state <state-from-host-launched>
```

Stage order per job is fixed: `job-extraction` → `bundle-writing` →
`copy-humanization` → `independent-review` → `render-promotion`, then
coordinator-only Notion sync. Only one stage runs per job at a time; tune
parallelism with `--max-active-jobs` (default 3).
