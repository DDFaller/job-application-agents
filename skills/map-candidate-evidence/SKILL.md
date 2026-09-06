---
name: map-candidate-evidence
description: "Map the canonical Markdown curriculum into one validated candidate-evidence artifact and receipt as an isolated stage, or return a validated cache hit. Never alter canonical sources, approved profiles, or spawn agents."
---

# Map Candidate Evidence

> [!NOTE]
> **Legacy / Backward-Compatibility Stage**:
> In the standard 5-stage orchestration pipeline, application drafting grounds directly in
> `sources/<role-profile>/` markdown files and `pre-formatted.tex`. This stage is retained for
> backwards compatibility with legacy schema-3 batches that explicitly require `candidate-evidence.json`.

Execute only the `candidate-evidence` `StageTask`. Do not delegate. Resolve the
canonical source manifest supplied by preflight and verify every source hash.
Use `/home/falluba/job-application-agents/skills/tailor-application-bundle/references/candidate-evidence-template.json`
and the cache utility in `/home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/`.

Reuse only a cache entry whose fingerprint matches the complete source
manifest and whose receipt validates. On a miss, acquire the fingerprint build
lock and write a fresh schema-3 evidence index under `output_dir`. Extract
identity, contact values, languages, conservative facts, typed experience, and
typed education. Preserve legal employer/client/contracting and official
credential distinctions. Each fact must cite an absolute source and SHA-256;
never infer absent information.

Run `/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/validate_candidate_evidence.py`, create/verify its receipt, and accept only
exit 0. Lock contention or transient file races are retryable; missing or
contradictory canonical evidence is non-retryable and must not trigger
`$maintain-master-curriculum`. Return hashed evidence and receipt references in
the exact `StageResult`. Do not edit canonical sources, profiles, timing,
Notion, or batch state.
