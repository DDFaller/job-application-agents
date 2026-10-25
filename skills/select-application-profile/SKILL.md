---
name: select-application-profile
description: Assess job fit against an approved positioning library, exposing evidence, gaps and unknowns for a user decision before writing documents.
---

Execute only the `profile-selection` StageTask. Do not delegate, write candidate sources, render, access Notion or submit.
Follow the [stage input scope](../manage-job-applications/references/stage-input-scope.md): read declared inputs only; do not search historical applications or results for examples.
Read `references/contracts.md`. Resolve `job.json` and `positioning-library.json` from declared, hashed task inputs. Read the library's canonical sources. Use actual duties rather than the advertised title or profile-name keyword overlap.

For new tasks write `profile-selection.json` with `schema_version: 2` in the exact task output directory. Cite source facts and job fields for all assessments, enumerate each requirement once, and compare every profile. Use only supported experience and clearly bounded transferable skills; do not invent personal interests or use generic enthusiasm as evidence. Unknown information, unmet requirements, seniority gaps and weak duty coverage remain visible assessments; they never cause an automatic `skip`. Return `decision: "review"` with the best supported profile (or the explicitly requested profile). Code derives the ranking and fit score; do not invent numerical scores or application permission. For an explicitly legacy task, preserve schema 1 and its documented semantics.

When the coordinator supplies `junior-tailoring-instruction.txt` authorizing CV
preparation despite gaps, apply the `junior_tailoring_override` contract below
for actual entry/junior scope. Select the most relevant evidence-backed profile
for document preparation even when experience is weak. Keep every gap assessed
as unknown/unmet; this is not proof of employer eligibility or a new skill claim.

Derive the selected profile and validate with `python3 scripts/validate_profile_selection.py --selection <file> --data-root <task.data_root> --derive`. The reason must still explain the factual strengths, gaps and uncertainty. Return a successful StageResult with the hashed selection artifact only after validation passes. Missing, stale or contradictory source/library input is a non-retryable configuration blocker. Mechanical schema errors may be repaired once; do not disguise an error as a weak match.

Legacy schema-1 working-practice exceptions retain their existing validation rules. Schema 2 does not need an exception to expose a job for review. Keep every original employer requirement and its truthful assessment; the coordinator records user choices separately. No selection or fit score authorizes submission or supplies new candidate facts.
