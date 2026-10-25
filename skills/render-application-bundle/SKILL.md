---
name: render-application-bundle
description: "Deterministically stage and promote one exact independently accepted application bundle into editable LaTeX and PDFs. Never make semantic edits, spawn agents, access Notion, or submit."
---

# Render Application Bundle

Execute only the `render-promotion` `StageTask`. Do not delegate. Require the
exact bundle and a validated independent review whose verdict is `accept` and
whose bundle hash matches.
Follow the [stage input scope](../manage-job-applications/references/stage-input-scope.md): read declared inputs only; do not search historical applications or results for examples.

Run `/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/render_bundle.py --preflight`, then
stage with `--profile auto`. French locations use the preserved A4 France
template and approved canonical photo; other locations use the compact
international template. Verify page count, extractable text, reading order,
frozen TeX/assets, and returned hashes. Every résumé must be at most one page.

Promote only the exact accepted staging directory. Promotion atomically creates
the next version and updates `current.json`; never edit a historical version.
Return hashed references to the version manifest, résumé PDF, letter PDF, and
editable TeX sources in `StageResult`. Deterministic tool or transient render
failures are retryable; a semantic mismatch is non-retryable and belongs back
at bundle writing/review. Do not access Notion, submit, or mark `APPLIED`.

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
