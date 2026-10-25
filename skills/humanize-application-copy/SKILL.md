---
name: humanize-application-copy
description: Humanize evidence-backed motivation letters and CV profile summaries while preserving every claim, citation, structured field, and selected role profile. Use after bundle drafting and before independent application review; never rewrite factual CV entries or invent candidate information.
---

# Humanize Application Copy

Execute only the supplied `copy-humanization` `StageTask`. Do not delegate,
write timing or batch state, or perform later review/render stages. Write the
exact required `StageResult` when the constrained merge validates.
Follow the [stage input scope](../manage-job-applications/references/stage-input-scope.md): read declared inputs only; do not search historical applications or results for examples.

Use the pinned `$humanizer` skill in embedded mode for the two prose surfaces
that are intentionally written for each application:

- `candidate.summary.text`, the profile shown above the CV sections;
- `motivation_letter.paragraphs[*].text`.

Do not rewrite headlines, CV bullets, work history, education, skills, dates,
URLs, contact details, evidence IDs, job references, or profile-selection data.

Preserve the cover-letter narrative order: introduce the candidate first,
then explain the source-grounded attraction to the company, then demonstrate
the evidence-backed matches and prospective contribution, followed by a brief
closing. Do not move company praise or a technical example ahead of the introduction.

## Workflow

1. Require an absolute validated bundle and job. Candidate-evidence and role-profile
   inputs are used if provided, but are optional when bundles are authored directly
   from role-profile sources. Accept an optional user writing sample only when it is
   explicitly provided.
2. As this isolated stage worker, use `$humanizer` in embedded mode on only the
   two target prose fields. Do not spawn or delegate. Preserve claims, names,
   numbers, dates, citations, and evidence references, and return final text
   only for each field.
3. Write a rewrite receipt containing the original text, final text, exact
   field paths, input bundle hash, Humanizer version, and Humanizer skill hash.
4. Run `/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/humanize-application-copy/scripts/apply_humanized_copy.py` to verify that every `before` value
   still matches the bundle and that no non-target value changed. Write the
   merged bundle to a staging path, never over the source bundle.
5. Re-run `/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/validate_bundle.py --bundle <merged-bundle.json>`. Independent review is a later controller
   stage. If the rewrite is unsupported, incomplete, or changes meaning,
   discard the staged result and return a typed failure with the original
   bundle intact. Write the required `StageResult`; never edit controller state
   or timing.

Humanization is a prose-quality pass, not permission to improve the candidate
record. Application preparation remains prohibited from writing curriculum or
profile state, submitting applications, or changing Notion status.

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
