---
name: tailor-application-bundle
description: "Write one evidence-backed application bundle from validated job, candidate-evidence, and approved role-profile artifacts. This is one isolated semantic stage: never spawn agents, humanize, review, render, track, or submit."
---

# Tailor Application Bundle

Execute only the `bundle-writing` `StageTask`. Do not delegate.
Inputs are resolved from `StageTask.inputs`. The primary source of candidate information is the role-profile source directory under `~/Documents/job-search/sources/<role-profile>/` containing `education.md`, `experience.md`, `identity.md`, `languages.md`, `projects.md`, and `skills.md`. Legacy hashed inputs (`candidate-evidence.json`, source manifest, role-profile catalog) are also supported for backwards compatibility.

Resolve every input exclusively from the artifact records in `StageTask.inputs`.
An input path is authoritative when it is absolute, exists, and matches its
declared hash (if declared). Batch-shared artifacts may intentionally live
under another job key's orchestration directory. Never reject, relocate, copy,
or replace a valid input merely because its path is not beneath the current job
key. Do not derive alternate job-local paths or search caches when the task
already supplies the required artifact.

Read `/home/falluba/job-application-agents/skills/tailor-application-bundle/references/bundle-template.json`, `/home/falluba/job-application-agents/skills/tailor-application-bundle/references/resume-entry-types.md`, and
`/home/falluba/job-application-agents/skills/tailor-application-bundle/references/job-driven-tailoring.md`. Draft content grounded directly in the role profile's sources (`education.md`, `experience.md`, `identity.md`, `languages.md`, `projects.md`, `skills.md`). Use the role profile's `pre-formatted.tex` CV as an authoritative layout, structure, and phrasing reference. Restrict positioning to truthful facts present in the source files. Keep
legal employer, contracting party, client, title, chronology, degree, and
credential distinctions exact.

Draft a concise one-page-oriented résumé and motivation letter in the posting
language, with English fallback. Preserve candidate identity/contact fields and
job URLs exactly. Include supported technical and soft skills, retain all
credibility warnings, and cite every authored claim. Never invent metrics,
seniority, tools, dates, relationships, credentials, language levels, or domain
experience.

If no approved profile passes the documented gates, write and validate a
`profile-proposal.json`, then return a non-retryable
`profile_approval_required` blocker. Do not invoke curriculum maintenance or
use a generic fallback.

Run `/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/validate_bundle.py --bundle <bundle.json>`. One in-stage repair
pass is allowed for structural errors. This validator does not grant semantic
acceptance. Write a successful `StageResult` with the validated bundle hash, or
a typed failed/blocked result. Do not humanize copy, review semantics, run
XeLaTeX, promote versions, access Notion, or edit timing/batch state.
