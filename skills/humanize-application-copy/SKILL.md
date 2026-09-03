---
name: humanize-application-copy
description: Humanize evidence-backed motivation letters and CV profile summaries while preserving every claim, citation, structured field, and selected role profile. Use after bundle drafting and before independent application review; never rewrite factual CV entries or invent candidate information.
---

# Humanize Application Copy

Use the pinned `$humanizer` skill in embedded mode for the two prose surfaces
that are intentionally written for each application:

- `candidate.summary.text`, the profile shown above the CV sections;
- `motivation_letter.paragraphs[*].text`.

Do not rewrite headlines, CV bullets, work history, education, skills, dates,
URLs, contact details, evidence IDs, job references, or profile-selection data.

## Workflow

1. Require an absolute validated bundle, job, candidate-evidence, and approved
   role-profile input. Accept an optional user writing sample only when it is
   explicitly provided.
2. Ask a clean-context writing agent to use `$humanizer` in embedded mode. Give
   it only the approved inputs, the two target prose fields, and the output
   contract. It must preserve claims, names, numbers, dates, citations, and
   evidence references, and must return final text only for each field.
3. Write a rewrite receipt containing the original text, final text, exact
   field paths, input bundle hash, Humanizer version, and Humanizer skill hash.
4. Run `scripts/apply_humanized_copy.py` to verify that every `before` value
   still matches the bundle and that no non-target value changed. Write the
   merged bundle to a staging path, never over the source bundle.
5. Re-run the normal bundle validator and the independent tailoring review.
   If the rewrite is unsupported, incomplete, or changes meaning, discard the
   staged result and return `failed` or `needs_input` with the original bundle
   intact.

Humanization is a prose-quality pass, not permission to improve the candidate
record. Application preparation remains prohibited from writing curriculum or
profile state, submitting applications, or changing Notion status.
