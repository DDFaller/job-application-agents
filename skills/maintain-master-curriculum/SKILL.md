---
name: maintain-master-curriculum
description: "Explicitly maintain and audit canonical candidate evidence or approved role profiles through staged, reviewed, user-approved versions. Never invoke during ordinary application preparation, spawn agents, infer facts, or publish without approval."
---

# Maintain Master Curriculum

This workflow is separate from job application preparation. Missing application
inputs, a job mismatch, or a profile proposal never authorizes curriculum
writes. Invoke only for an explicit user request to add/correct candidate facts,
review a proposed profile, publish an approved change, or audit readiness.

Resolve the data root only through explicit input, `JAA_DATA_ROOT`, or default
`~/Documents/job-search`. Canonical candidate facts live in
`<data-root>/sources/<role-profile>/` with standard markdown files (`identity.md`,
`experience.md`, `education.md`, `skills.md`, `projects.md`, `languages.md`) and
an authoritative 1-page XeLaTeX reference CV (`pre-formatted.tex`).
Read `/home/falluba/job-application-agents/skills/maintain-master-curriculum/references/source-layout.md`
and `/home/falluba/job-application-agents/skills/maintain-master-curriculum/references/role-profiles.md`.

## Flat maintenance stages

The owning controller may launch separate fresh Agent Deck sessions using this
skill and a `StageTask` whose stage is one of the following. A worker executes
only its named stage, writes only its attempt directory and `StageResult`, and
never delegates.

- `source-draft`: conservatively stage Markdown changes from only supplied
  documents or direct user statements, preserving snapshots and SHA-256.
- `source-review`: independently produce `additions-review.json` from the exact
  staged diff using `/home/falluba/job-application-agents/skills/maintain-master-curriculum/references/additions-review.md`; detect contradictions,
  unsupported metrics, inferred proficiency, exaggeration, duplicate facts,
  and silent removals.
- `profile-draft`: stage evidence-backed profiles bound to the exact source
  manifest. Require an anchor, two distinct supports, seniority ceiling,
  demonstrated technologies, allowed facts, prohibited claims, and risks.
- `profile-review`: independently review grounding, sufficiency, seniority,
  coherence, and risks with `/home/falluba/job-application-agents/skills/maintain-master-curriculum/references/profile-review-template.json`.
- `readiness-audit`: derive and validate an audit artifact without modifying
  canonical facts or profiles.

Author and reviewer stages must be different sessions. Scripts validate schema,
hashes, and stale inputs but never invent semantic acceptance. One mechanical
repair attempt is allowed inside a stage; substantive revision returns to a
fresh author attempt.

## Approval and publication

After validators pass, show the user the exact current-to-staged diff, claim-
level review, and unresolved questions. Do not publish or imply approval.
Only the coordinator may act on explicit approval by running:

```bash
/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/maintain-master-curriculum/scripts/commit_master_update.py --staged-dir <dir> --review <review> \
  --source-dir <data-root>/sources --state-root <data-root>/master-curriculum \
  --approval APPROVED
```

or, for profiles:

```bash
/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/maintain-master-curriculum/scripts/commit_profile_update.py --staged-catalog <catalog> \
  --review <review> --state-root <data-root>/master-curriculum \
  --approval APPROVED
```

Use `--sync-firestore` only when the user explicitly requested live sync and
the controller has credentials. Commit scripts rerun validators, create
immutable `vNNN`/`pNNN` history, and update pointers atomically. Never edit an
immutable version.

Every source-manifest change invalidates the current profile catalog until a
compatible catalog is separately reviewed and approved. A
`profile-proposal.json` from tailoring is only an input to `profile-draft`; it
never resumes an application automatically.

## Safety invariants

- Candidate sources contain neutral facts, not job requirements or generated
  résumé language. Never import applications, mocks, or inferred claims.
- Ambiguous employer/client relationships and credentials are quality gaps,
  never profile anchors.
- Keep snapshots, audits, generated evidence indexes, profiles, and application
  documents outside the canonical source directory.
- Never access Notion, submit an application, contact an employer, or change an
  application status from this skill.

## Positioning library publication

For the modern positioning library, use the separate contract in
`skills/select-application-profile/references/contracts.md`. Stage the exact
library and Markdown/LaTeX/PDF baseline previews, then obtain an independent
claim-level review binding all preview hashes. The same explicit-approval rule
above applies. Validate without activating:

```bash
python3 scripts/publish_positioning_library.py --library <library> --review <review> --data-root <private-root>
```

Only after approval of these exact artifacts, add `--approval APPROVED` to create
an immutable positioning release and atomically activate its separate pointer.
Legacy catalog publication remains unchanged. Direct user statements may be
separate hashed evidence inputs; never infer eligibility from spoken language.
