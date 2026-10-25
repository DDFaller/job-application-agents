---
name: prepare-job-application
description: "Define and validate the flat single-job application DAG used by the durable batch controller. Use to prepare a reviewable draft from a public opening; never spawn agents, maintain the master curriculum, submit, or mark APPLIED."
---

# Prepare Job Application

This is an orchestration specification, not a worker stage. When the durable
controller is available, do not launch a `$prepare-job-application` session.
The controller expands it into one clean session for each semantic stage and
passes data only through validated artifacts.

Read `/home/falluba/job-application-agents/skills/prepare-job-application/references/workflow.md`, then require one public opening URL or pasted
posting, an explicit canonical data root outside the repository (`~/Documents/job-search`),
discovered role-profile sources under `~/Documents/job-search/sources/<role-profile>/`, and a unique run ID with a controller-owned timing ledger.

The streamlined stage order is:
1. `job-extraction` (extracts job posting to `source.md` and `job.json`)
2. `profile-selection` ($select-application-profile; score approved profiles and expose gaps for user review)
3. `bundle-writing` (grounds drafting directly in selected role profile sources)
4. `copy-humanization` (polishes tone while preserving facts)
5. `independent-review` (audits bundle quality and evidence)
6. `render-promotion` (compiles XeLaTeX resume and motivation letter, generates PDFs)
The coordinator may then perform a deduplicated Notion update through its connector. Dependencies are serial within one job; different jobs may progress concurrently.

Every worker receives one `StageTask` and returns one `StageResult`. It must not
spawn or delegate, edit batch state or timing, access Notion, update the master
curriculum, or use conversational continuation as state. On failure, retry
only that stage with accepted upstream artifacts and a new attempt path.

In legacy batches only, if no approved profile fits, the bundle stage may emit a validated profile
proposal and non-retryable `profile_approval_required` blocker. End as
`needs_input`; a separate explicit `$maintain-master-curriculum` workflow is
required to review and publish it.

A job is locally `prepared` only after the exact reviewed bundle is rendered,
passes deterministic PDF/text/page gates, and is atomically promoted. Notion
failure does not invalidate local preparation. Never submit, contact the
employer, invoke auto-apply, or mark `APPLIED`.

New batches require an approved positioning library before launch. Schema-2 selection exposes supported fit, evidence coverage, gaps and unknowns, then pauses at `awaiting_fit_review`. Only an explicit user skip becomes `skipped`. For jobs the user has already selected, `--prepare-selected` continues truthful preparation while preserving the fit report. Submission remains a separate authorized workflow. Stored batch stages preserve legacy order on resume. Positioned CVs must pass the one-page, minimum-10pt PDF gate.
