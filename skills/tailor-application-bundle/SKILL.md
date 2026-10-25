---
name: tailor-application-bundle
description: "Write one evidence-backed application bundle from validated job, candidate-evidence, and approved role-profile artifacts. This is one isolated semantic stage: never spawn agents, humanize, review, render, track, or submit."
---

# Tailor Application Bundle

For a validated `junior_tailoring_override` selection, write the junior CV even
when experience coverage is weak. Emphasize evidenced transferable work and
projects. Distinguish professional, project and study experience; add study
skills only when actually documented. Record gaps in match analysis, never
invent experience to satisfy the posting. This override concerns preparation.

Execute only the `bundle-writing` `StageTask`. Do not delegate.
Follow the [stage input scope](../manage-job-applications/references/stage-input-scope.md): read declared inputs only; do not search historical applications or results for examples.
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

Always structure the cover-letter body as candidate introduction → specific,
source-grounded attraction to the company → evidence-backed matches and prospective
contribution, followed by a brief closing. Follow the cover-letter narrative
heuristics in `references/job-driven-tailoring.md`; preserve this order through
humanization and independent review.

For legacy tasks without profile-selection.json, if no approved profile passes
the documented gates, write and validate a
`profile-proposal.json`, then return a non-retryable
`profile_approval_required` blocker. Do not invoke curriculum maintenance or
use a generic fallback.

Run `/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/validate_bundle.py --bundle <bundle.json>`. One in-stage repair
pass is allowed for structural errors. This validator does not grant semantic
acceptance. Write a successful `StageResult` with the validated bundle hash, or
a typed failed/blocked result. Do not humanize copy, review semantics, run
XeLaTeX, promote versions, access Notion, or edit timing/batch state.

## Selected positioning profile (new batches)

When `profile-selection.json` is a declared input, it is mandatory provenance.
Use its exact selected profile from `positioning-library.json`; the canonical
identity headline is a fallback for legacy bundles, not a reason to replace an
approved specialized headline. Bind the bundle with `inputs.profile_selection_json`
and `inputs.profile_selection_sha256`, keep `inputs.role_profile` and
`inputs.role_profile_source_dir` pointing to the selected profile's source folder,
and set `tailoring_strategy.selected_profile_id` to the positioning profile ID.
Do not change this selection during humanization or rendering.

Read and follow the library editorial rules and profile's narrative, skill groups,
prohibited claims and risk notes. Show identity, evidence and role-relevant
contribution in the summary without inventing personal interests. Choose the most
relevant achievements and projects; no universal employer bullet caps or rigid
word count. Keep a one-page CV with at least 10pt body text. Cut redundancy before
shrinking type. Keep employment titles/dates and professional/project distinctions.

Independent review must verify the selection's priority/mandatory assessments
against the actual job and source facts, including that every `learning_allowed`
assessment cites an explicit allowance. Reject unsupported years or ownership,
misleading skills, and generic summaries interchangeable across different job
families. A selection error returns to `profile-selection`; a wording error returns
to `bundle-writing`. Missing input bindings must block review/render acceptance.

For a positioned bundle, use direct source fact IDs and omit legacy candidate-evidence/catalog inputs. The selected positioning library replaces legacy profile ranking; do not recompute a different winner inside the bundle.
