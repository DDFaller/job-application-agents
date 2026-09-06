# Ownership & Review Routing

Status: **advisory** until required code-owner review is enabled in branch
protection. Enforcement lives in `.github/CODEOWNERS`; this file explains
the domains and when to pull in a second owner.

All team handles (`@DDFaller/<team>`) are placeholders. Replace them with
real teams or users once the roster is known.

## Domains

| Domain | Steward | Paths | Review triggers |
| --- | --- | --- | --- |
| Application Core | `@DDFaller/app-core` | `job_application_agents/auto_apply/`, `job_search/`, `orchestration/`, `sources.py`, `config.py` (+ colocated `test_*.py`), `main.py`, `config.jsonc`, `scripts/auto_apply.py`, `scripts/phone_review.py` | Matching/scoring changes, draft models, verifier signals, review UI |
| Render Pipeline | `@DDFaller/render-pipeline` | `job_application_agents/render_service/`, `scripts/render_service.py`, `scripts/check_render_service.py` | Compiler, artifacts, worker leases, migrations, render CLI |
| Data, Sync & Ingestion | `@DDFaller/data-sync` | `job_application_agents/sync/`, `plugins/`, `integrations/`, `functions/`, ingestion/Notion ops scripts | Sync protocol, Firestore schema use, scrapers, Notion board ops, handlers |
| Platform, Deploy & Release | `@DDFaller/platform` | `deploy/`, `firebase.json`, deploy/worker shell scripts | Images, compose, rules/indexes, Cloud Build, PWA, releases |
| Agent Workflows & Docs | `@DDFaller/agent-workflows` | `skills/`, `docs/`, `README.md`, report script | Skill frontmatter/conventions, workflow semantics, docs |
| Repo Tooling & Hygiene | `@DDFaller/tooling` | `pyproject.toml`, `requirements*.txt`, `scripts/check.py`, `scripts/setup.py`, `.github/`, `AGENTS.md`, unlisted `scripts/` | Packaging, setup, CI, repo process |

## Shared contracts (dual sign-off)

Changes to these require **both** listed stewards, regardless of who
initiates the change:

- `job_application_agents/plugins/base.py` — data-sync + app-core
- `integrations/base.py`, `integrations/models.py` — data-sync + app-core
- `job_application_agents/render_service/migrations/` — render-pipeline + platform
- `deploy/firestore/` (rules, indexes) — platform + data-sync

## Routing rules

- New `scripts/` belong to the domain they operate on, not to tooling by
  default; update `.github/CODEOWNERS` when adding one.
- New skills belong to agent-workflows for structure, with content review
  from the domain the skill automates.
- Generated, external, or personal paths are out of scope and intentionally
  unowned: `build/`, `output/`, `data/`, `__pycache__/`, `*.egg-info/`,
  `.agents/`.

## Activating enforcement

1. Replace placeholder handles with real teams/users in `.github/CODEOWNERS`.
2. Enable "Require review from Code Owners" in branch protection for `main`.
3. Flip the status line at the top of this file from advisory to enforced.
