---
name: rank-job-shortlist
description: Batch-rank staged or ingested public job openings against the candidate evidence, deduplicate tracked applications, expose strengths and gaps, and return a triage shortlist for preparation. Use for ranking jobs, prioritizing a queue, or choosing which openings to apply to. Scores are triage only.
---

# Rank Job Shortlist

Rank jobs in parallel without turning triage into a final application decision.

1. Resolve the current candidate source manifest and approved role profiles.
   Load normalized `job.json` files from staging or accept an explicit list.
2. Exclude jobs already tracked by canonical URL, source job ID, or the exact
   company/role identity. Keep exclusions explainable.
3. Use `scripts/rank_jobs.py` for deterministic scoring and stable sorting.
   The output includes `job_key`, score, breakdown, matched/missing skills,
   source path, and `triage_only: true`.
4. Have clean-context agents inspect the posting evidence for deal-breakers,
   deadline urgency, stale/expired status, and honest strengths/gaps. Never
   score from a title alone; inaccessible jobs are blocked or expired.
5. Present the ranked shortlist and hand selected entries to
   `$prepare-job-application`. Final company research and semantic fit review
   always run again during preparation.

Default to five results and a score threshold of 60. `--all`, `--top N`, and
`--min-score N` are run-scoped options. Preview is read-only; writing
`rankings/latest.json` requires an explicit write request.
