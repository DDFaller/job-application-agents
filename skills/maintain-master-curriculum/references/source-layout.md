# Canonical source layout

Keep current, user-approved candidate evidence in the role-profile source directories under:

`<data-root>/sources/<role-profile>/` (e.g. `sources/backend-engineer/`, `sources/ai-platform-engineer/`)

Each role profile directory contains:
- `identity.md` — name, headline, location, contact methods, professional and portfolio links
- `experience.md` — employers, roles, dates, responsibilities, technologies, and outcomes
- `education.md` — degrees, institutions, subjects, and dates
- `skills.md` — independently supportable technical, platform, and interpersonal skills
- `projects.md` — project purpose, ownership, technologies, links, and outcomes
- `languages.md` — language and explicit proficiency
- `pre-formatted.tex` — authoritative 1-page XeLaTeX reference CV demonstrating optimal phrasing and structure
- `international_utilities.tex` — companion LaTeX macros for standalone compilation
- `profile-photo.jpg`, `profile-photo.jpeg`, or `profile-photo.png` — optional approved CV portrait

## Fact format

Facts are written in clear, natural Markdown bullets. Bullet assertions should be factual, concise, and truthful:

```markdown
# Experience
## Example GmbH
- Worked at Example GmbH as a Backend Developer from 2024-01 to 2026-06.
- Built Spring Boot APIs for the inventory domain with PostgreSQL and Kafka.
```

Legacy `[MC-ID-001]`, `[MC-EXP-001]` prefixes are supported for backwards compatibility, but are no longer required. State dates, proficiency, technologies, responsibilities, and outcomes truthfully without exaggeration.

## Update rules

- Treat an explicitly approved user statement as a canonical fact without adding a lower-confidence label.
- Reconcile contradictions by asking the user; do not keep mutually incompatible current facts.
- Do not turn GitLab CI usage into general Git knowledge, exposure into proficiency, team outcomes into personal outcomes, or project work into employment.
- For employment or independent work, state legal employer, contracting party,
  client, engagement type, and official title as separate facts when known. Do
  not use `at <client>` as evidence of employment.
- For education, state institution, official degree or certificate, field,
  track, completion status, credential awarded, and dates separately when
  known. Do not translate a Brazilian lato sensu specialization to a master's
  degree or use a framework equivalence such as `BAC+5` as the credential.
- Do not create quantified impact from qualitative wording.
- Do not store subjective impressions, speculation, or explicitly unmeasured outcomes as canonical application facts.
- Use full URLs for links and label the destination.
- Prefer `YYYY-MM` dates when known; preserve coarser dates rather than guessing missing months.
- Put no placeholder, `TODO`, example person, or instructional comment into approved sources.

## Compatibility boundary

The live `/home/falluba/job-application-agents/skills/tailor-application-bundle/references/candidate-evidence-template.json` and `/home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/validate_candidate_evidence.py` define technical readiness. This layout optimizes extraction but does not replace that validator. A technically valid evidence set can still have quality gaps.
