# Session functional changes: lightweight application workflow

Date: 2026-09-11

## Scope and implementation location

This document records the completed lightweight reprocessing workflow introduced in this session. It addresses strong matches being skipped because requirements were unknown and documents failing to reach delivery.

The implementation lives in the configured **external private data root**, in a dedicated batch directory and candidate-knowledge store. These batch helpers reuse existing repository capabilities; they do not replace the repository's general orchestration controller or installed skills. No repository source modules or skills were edited for this batch implementation. This Markdown file documents the changes; unrelated changes already present in the working tree are outside its scope.

Private candidate facts, company-level application records, credentials, and generated documents remain outside the repository. Component filenames below are relative to the private batch directory unless otherwise stated.

## Workflow before and after

Previously, unknown requirements, unverified eligibility details, and publication-date uncertainty could prevent a selected opening from reaching CV creation. Multiple separate stages also increased coordination and retry overhead.

The batch now follows:

```text
Explicit job selection
  → Prepare: verify evidence, select positioning, tailor and humanize copy
  → Render: deterministic LaTeX compilation and page previews
  → Combined independent review: factual scope, relevance and visual layout
  → Publish: documents, Notion status and report
```

Unknown requirements become recorded gaps or bounded claims. They do not automatically block drafting. Document readiness and application eligibility are tracked separately, so a complete document package can be delivered with a human-review reason.

## Affected components

| Component | Change | Effect |
| --- | --- | --- |
| `policy.json`, `AUTHOR.md`, `jobs.json` | Explicit selection, exclusions, confidence threshold, author instructions and execution limits | The coordinator processes the authorized batch without repeating the previous skip decisions. |
| `runtime.py`, `RUNTIME.md` | Selection, confidence assessment, experience aggregation, rendering, review validation and state transitions | A small batch runtime replaces the previous stage gates for this execution. |
| Candidate-knowledge policy and confidence cache | Persistent assessments tied to evidence and policy versions | Later work can reuse supported assessments without promoting inferences to canonical facts. |
| `setup/candidate-update/publish_source_profile_amendment.py` | Reviewed publication of approved source/profile amendments | Corrected facts and broader role eligibility become available to tailoring. |
| `deliver.py` | Package reviewed PDFs and editable LaTeX sources | Company folders contain identifiable, reviewable deliverables. |
| `sync_lightweight.py` | Update existing Notion cards and current documents | Documents and review status reach the board without duplicate applications. |
| `report.py` | Generate JSON progress, Markdown and offline HTML reports | Every selected opening has an outcome and an explanation of remaining gaps. |
| `test_runtime.py`, `test_delivery.py`, publisher tests | Focused behavioral checks | Validate confidence, state, review and delivery behavior. |

## Requirement confidence and reusable evidence

The default `requirement_confidence_threshold` is **70**. Assessments apply to an exact requirement and claim scope, with evidence, rationale, source hashes and permitted wording.

| Evidence | Score | Inclusion constraint |
| --- | ---: | --- |
| Explicit user confirmation | 100 | Stay within the confirmed scope. |
| Direct candidate evidence | 90 | Stay within the demonstrated scope. |
| At least two distinct candidate-specific clues | 70 | Familiarity or working exposure only. |
| Company-level evidence alone | 40 | Insufficient for automatic inclusion at the default threshold. |
| Unsupported or denied | 0 | Do not include; denial takes precedence. |

These scores measure support for a bounded claim, not hiring probability or mastery. Common industry use of Agile or CI/CD alone does not establish candidate experience. Narrow evidence cannot justify a stronger claim such as production ownership.

The cache uses requirement, scope, source hashes and policy version. Relevant candidate inputs and overrides must be included in the hashes. Changed evidence invalidates an old assessment; changing the threshold re-evaluates inclusion. Inferences remain separate from canonical curriculum facts. Independent review checks the author's evidence classification and final wording.

Job-post soft skills may be included as user-authorized self-descriptions. This does not authorize invented examples or achievements.

## Profile positioning and experience

- Publish approved qualification and employment corrections through source/profile amendments with independent review.
- Include intermediate roles in profile eligibility instead of restricting selection to junior roles; retain truthful historical job titles.
- Calculate total experience from the union of authorized professional calendar months, including authorized internships. Count overlapping transition months once.
- Do not present aggregate experience as the same duration of experience in every technology.
- Select role-specific experience, skills and projects to support a clear reason for applying.

## Selection, freshness and human review

The policy records an automatic match threshold of 75, with an explicit-selection override for this batch. The explicitly blocked employer remains excluded. Original ranking scores and historical audit records are preserved.

A displayed publication date, `datePosted` or `releasedDate` is sufficient; this batch does not require proof of the original first publication or impose a maximum-age gate. An update-only date does not establish publication freshness.

Missing publication dates produce `HUMAN_REVIEW` with a reason while document creation continues. Material language, eligibility or specific qualification gaps can also require human review. Other unresolved technical requirements are omitted, carefully scoped or reported as nonblocking gaps.

## Document creation and review

The batch uses the French two-column photo XeLaTeX template, with one A4 page per document, body text of at least 10 pt and margins of at least 12 mm. Soft skills appear below competencies; selected projects appear below education. Each company receives a dedicated folder and descriptive document filenames.

One author combines evidence mapping, positioning, tailoring and humanization. Execution allows up to three concurrent authors. Rendering runs XeLaTeX twice with shell escape disabled, retains compiler logs, and produces page counts, PDF hashes and PNG previews.

A reviewer distinct from the author examines factual scope, role relevance and every rendered page. Acceptance is bound to the exact PDF SHA-256 hashes and preview references. Hash validation establishes which files were accepted; actual visual inspection remains the reviewer's responsibility.

One correction cycle is allowed. Corrected files must be rendered and reviewed again. A second revision request routes the result to human review instead of creating an indefinite loop. Delivery validates the current review and packages PDFs with editable LaTeX sources.

## Notion synchronization and delivery

The batch uses the existing direct Notion API capability independently of the MCP startup path that encountered OAuth failures. It updates existing cards, refreshes their current-document attachments and preserves unrelated content.

- Deliver the CV, cover letter and editable source ZIP.
- Set ready documents to `TO_APPLY`, or record `HUMAN_REVIEW` and its reasons.
- Preserve existing applied, interview, assessment and terminal statuses.
- Use synchronization receipts and partial-upload reuse for repeatable retries.
- Retain local documents if authentication or network errors leave synchronization pending; do not regenerate documents just to retry synchronization.

The combined download archive preserves company folders. Reports contain opening and board links, document links, publication dates, status counts and remaining gaps. Completion metadata records deliverable counts and integrity checks.

## Completed validation and outcome

The session completion manifest records:

- `python3 scripts/check.py`: passed during implementation.
- Runtime and delivery tests: 24 passed.
- Source/profile publisher tests: 8 passed.
- XeLaTeX smoke check: passed.
- All 26 PDF pages visually reviewed; every PDF has one page.
- Review/delivery hashes verified and archive CRC checked.

The batch completed 13 tailored CVs, 13 cover letters and 13 editable source bundles. All 13 records were synchronized: 10 ready to apply and 3 requiring human review. The persistent store contains 298 requirement-confidence assessments at a default threshold of 70.

No applications were submitted or prefilled during this execution. Scheduled timers and old background supervisors were not restarted.

## Limits and future reuse

The new behavior is operational for this private batch. Persisted evidence assessments and approved profile amendments can support future work, but other entrypoints do not automatically inherit these batch policies. General adoption would require explicitly integrating the helpers and contracts into the repository controller and relevant skills, with regression checks.

Future runs should resolve current candidate sources and policy, invalidate stale confidence records, preserve explicit exclusions, and keep document generation separate from application eligibility. Candidate-specific overrides must not silently become defaults for other candidates or batches.
