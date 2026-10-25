---
name: review-application-bundle
description: "Independently review one exact humanized application bundle against validated job, candidate role-profile sources, and bundle inputs. Never revise the bundle, spawn agents, render, track, or submit."
---

# Review Application Bundle

Follow the [stage input scope](../manage-job-applications/references/stage-input-scope.md): read declared inputs only; do not search historical applications or results for examples.

A validated `junior_tailoring_override` permits preparing a junior application
despite weak experience. Verify its controller-supplied direct-user authority
and exact quote. Do not reject solely because the user accepted a preparation
gap; still reject invented skills, study usage, years, languages or credentials.
Keep unmet requirements explicit in internal match analysis. Acceptance of the
documents does not certify that all employer submission requirements are met.

Execute only the `independent-review` `StageTask`. Do not delegate and do not
edit the bundle. Verify declared input hashes, then read
`/home/falluba/job-application-agents/skills/tailor-application-bundle/references/job-driven-tailoring.md` and
`/home/falluba/job-application-agents/skills/tailor-application-bundle/references/tailoring-review-template.json`.

Review relevance, factual grounding against candidate role-profile sources
(`sources/<role-profile>/`), seniority, employer/client labels, official education
credentials, acronyms, spelling, complete bullets, motivation-letter quality, and ATS reading order.
When candidate evidence is omitted, factual grounding is verified directly against
the role-profile markdown files and `pre-formatted.tex`.
Treat the constrained Humanizer receipt as provenance, not proof of quality.

Check that the cover-letter body introduces the candidate first, explains a
specific source-grounded attraction to the company second, and then connects
supported candidate examples to the company's needs and prospective contribution.
Require revision when this order is missing, the company paragraph is generic
or unsupported, or the fit paragraph only lists technologies without explaining
their relevance. A brief closing follows these three narrative moves.

Write `tailoring-review.json` with verdict `accept` or `revise`, exact input
hashes, and actionable findings. Validate it with
`/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/validate_tailoring_review.py --review <tailoring-review.json>`. For `accept`, return a successful result with
the review hash. For `revise`, return a retryable `bundle_revision_required`
blocker with `restart_stage: bundle-writing` and include the validated review
artifact; the controller rewinds the DAG while retaining accepted upstream
evidence. Do not render, promote, access Notion, or change application status.

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

When selection contains `user_authorized_exceptions`, validate it against the exact
hashed job and private direct-user instruction using the selection contract in
`../select-application-profile/references/contracts.md`. Verify actual user provenance,
verbatim quote, and explicit authorization for this job and Agile/Scrum-only gap;
a matching hash alone does not establish consent. An otherwise valid selection may
retain `unknown`/`unmet` for that user-accepted gap. Do not reject solely for that
accepted gap or demand it become `met`. Preserve original employer requirements,
all other qualification gates and evidence limits. The exception is not candidate
evidence: reject unsupported Agile experience or any other false CV/letter claim.
