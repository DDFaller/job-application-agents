# Canonical source layout

Keep only current, user-approved Markdown evidence and the optional approved CV portrait in the canonical source directory. Use these filenames:

- `identity.md` — name, headline, location, contact methods, professional and portfolio links
- `experience.md` — employers, roles, dates, responsibilities, technologies, and outcomes
- `projects.md` — project purpose, ownership, technologies, links, and outcomes
- `education.md` — degrees, institutions, subjects, and dates
- `skills.md` — independently supportable technical and interpersonal skills
- `languages.md` — language and explicit proficiency
- `certifications.md` — credentials, issuer, identifier, and date
- `profile-photo.jpg`, `profile-photo.jpeg`, or `profile-photo.png` — at most one explicitly approved CV portrait; not candidate evidence

`identity.md` is required. Other files are optional until facts exist. Do not put archives, other originals, generated resumes, audit output, or instructions in this directory.

## Fact format

Write every factual assertion as one Markdown bullet beginning with a stable ID:

```markdown
- [MC-ID-001] Name: Ada Example
- [MC-EXP-001] Worked at Example GmbH as a Backend Developer from 2024-01 to 2026-06.
- [MC-EXP-002] Built Spring Boot APIs for the inventory domain.
```

Allowed prefixes are `ID`, `EXP`, `PROJ`, `EDU`, `SKILL`, `LANG`, and `CERT`. Use three or more digits. IDs are unique across the entire library and remain attached to the same fact through wording improvements. Assign a new ID to a genuinely new fact. Do not recycle deleted IDs.

Use headings for organization, not factual claims. Keep one independently quotable claim per bullet. State dates, proficiency, technologies, responsibilities, and outcomes only when explicitly supplied. Preserve meaningful specificity, but split compound claims when their support differs.

## Update rules

- Treat an explicitly approved user statement as a canonical fact without adding a lower-confidence label.
- Reconcile contradictions by asking the user; do not keep mutually incompatible current facts.
- Do not turn GitLab CI usage into general Git knowledge, exposure into proficiency, team outcomes into personal outcomes, or project work into employment.
- Do not create quantified impact from qualitative wording.
- Do not store subjective impressions, speculation, or explicitly unmeasured outcomes as canonical application facts.
- Use full URLs for links and label the destination.
- Prefer `YYYY-MM` dates when known; preserve coarser dates rather than guessing missing months.
- Put no placeholder, `TODO`, example person, or instructional comment into approved sources.

## Compatibility boundary

The live `tailor-application-bundle/references/candidate-evidence-template.json` and `scripts/validate_candidate_evidence.py` define technical readiness. This layout optimizes extraction but does not replace that validator. A technically valid evidence set can still have quality gaps.
