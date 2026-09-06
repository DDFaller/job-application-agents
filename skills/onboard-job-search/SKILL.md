---
name: onboard-job-search
description: Onboard or refine a candidate's job-search profile from supplied documents or a guided interview, including target roles, locations, languages, salary preferences, deal-breakers, search terms, portals, and CV language. Use when the user wants to set up or reconfigure their job search. Never publish unapproved facts.
---

# Onboard Job Search

Use `$maintain-master-curriculum` as the factual source workflow. This skill
owns the conversational setup and search preferences, not a second candidate
database.

1. Resolve the configured data root (`~/Documents/job-search`) and inspect existing
   role-profile source directories under `<data-root>/sources/<role-profile>/`.
2. Offer three paths: ingest supplied documents, import an existing CV, or conduct a
   guided interview. Re-running setup must be additive and idempotent.
3. Collect only missing preferences: target functions and title variants,
   industries, geographic tiers, work model, professional languages and
   proficiency, compensation baseline, deal-breakers, preferred portals, and
   CV language.
4. Scaffold or update the candidate's role-profile source files:
   - `identity.md`, `experience.md`, `education.md`, `skills.md`, `projects.md`, `languages.md`
   - Generate an initial 1-page `pre-formatted.tex` reference CV and companion `international_utilities.tex`.
   - Store search preferences in `search-preferences.json`.
5. Suggest adjacent role profiles as options, never as silently enabled
   targets. Return readiness, unresolved contradictions, and configured
   search terms.

Do not infer language proficiency, authorization, salary, preferences, or
career goals. Do not overwrite an approved source or profile without preview.
