---
name: onboard-job-search
description: Onboard or refine a candidate's job-search profile from supplied documents or a guided interview, including target roles, locations, languages, salary preferences, deal-breakers, search terms, portals, and CV language. Use when the user wants to set up or reconfigure their job search. Never publish unapproved facts.
---

# Onboard Job Search

Use `$maintain-master-curriculum` as the factual source workflow. This skill
owns the conversational setup and search preferences, not a second candidate
database.

1. Resolve the configured data root and inspect existing source/profile
   manifests before asking questions.
2. Offer three paths: ingest supplied documents, import one CV, or conduct a
   guided interview. Re-running setup must be additive and idempotent.
3. Collect only missing preferences: target functions and title variants,
   industries, geographic tiers, work model, professional languages and
   proficiency, compensation baseline, deal-breakers, preferred portals, and
   CV language.
4. Send factual material through `$maintain-master-curriculum` with its exact
   preview and approval gates. Store preferences in a separate approved
   search-preferences artifact bound to the current source fingerprint.
5. Suggest adjacent role families as options, never as silently enabled
   targets. Return readiness, unresolved contradictions, and configured
   search terms.

Do not infer language proficiency, authorization, salary, preferences, or
career goals. Do not overwrite an approved source or profile without preview.
