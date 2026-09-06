---
name: humanize-application-copy
description: Humanize evidence-backed motivation letters and CV profile summaries while preserving every claim, citation, structured field, and selected role profile. Use after bundle drafting and before independent application review; never rewrite factual CV entries or invent candidate information.
---

# Humanize Application Copy

Execute only the supplied `copy-humanization` `StageTask`. Do not delegate,
write timing or batch state, or perform later review/render stages. Write the
exact required `StageResult` when the constrained merge validates.

Use the pinned `$humanizer` skill in embedded mode for the two prose surfaces
that are intentionally written for each application:

- `candidate.summary.text`, the profile shown above the CV sections;
- `motivation_letter.paragraphs[*].text`.

Do not rewrite headlines, CV bullets, work history, education, skills, dates,
URLs, contact details, evidence IDs, job references, or profile-selection data.

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
