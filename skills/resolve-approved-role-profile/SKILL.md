---
name: resolve-approved-role-profile
description: Read-only resolution and validation of the canonical approved role-profile catalog for application workflows. Use when an application needs a profile catalog; never use this skill to edit, review, propose, publish, or approve curriculum or profiles.
---

# Resolve Approved Role Profile

> [!NOTE]
> **Legacy / Backward-Compatibility Skill**:
> In the modern role-profile architecture, candidate role profiles are directly organized as
> folders under `<data-root>/sources/<role-profile>/` and resolved at runtime via
> `job_application_agents.sources.list_role_profiles()` and `match_role_profile()`.
> This resolver is retained for legacy catalogs compiled from `master-curriculum/profiles`.

This is the application-time read-only contract for role profiles. It is
separate from `$maintain-master-curriculum`, which owns all curriculum and
profile writes, proposals, reviews, approvals, and publication.

## Required invocation

Require an explicit absolute data root. Run:

```bash
/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/resolve-approved-role-profile/scripts/resolve_approved_role_profile.py \
  --data-root <data-root>
```

The resolver uses only:

- `<data-root>/sources/current.json` and its canonical Markdown files;
- `<data-root>/master-curriculum/profiles/current.json`;
- immutable artifacts under `<data-root>/master-curriculum/profiles/versions/`.

It must never fall back to `./job-search`, inspect generated applications as
candidate evidence, or write any file.

## Acceptance contract

Accept only exit code `0`. The result contains the validated source manifest,
approved immutable catalog path, catalog hash, profile IDs, and source
fingerprint. The resolver verifies:

- the canonical source manifest and live Markdown hashes;
- the profile pointer and immutable version hash;
- the accepted review and its reviewed catalog snapshot;
- approved catalog schema and evidence references;
- exact binding to the requested canonical source manifest.

Exit code `2` is a blocked or stale profile state and must be returned to the
owning application as `needs_input`. Do not invoke maintenance or repair from
this skill. A user explicitly requesting a curriculum/profile change must be
routed to `$maintain-master-curriculum` as a separate operation.
