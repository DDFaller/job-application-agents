# Readiness rubric

## Hard blockers

Report a hard blocker when application tailoring cannot safely start:

- Canonical source directory is missing, empty, structurally invalid, or contains forbidden files.
- Candidate name, at least one contact method, or usable evidence facts are absent.
- A populated candidate identity field lacks exact quote-backed evidence.
- Candidate evidence contains invalid paths, changed hashes, non-verbatim quotations, unknown references, or schema errors.
- The live candidate-evidence validator returns `1` or cannot be run.
- Current sources contain unresolved contradictions that could change identity, employment, education, or claimed qualifications.

## Quality gaps

Report these as non-blocking when the evidence remains technically usable:

- Headline, location, professional links, or portfolio links are absent.
- Employment or education dates are incomplete.
- Responsibilities do not identify personal contribution or technologies.
- Projects lack purpose, ownership, implementation detail, outcomes, or usable links.
- Skills cannot be connected to experience, education, or projects.
- Language proficiency is absent or ambiguous.
- Certifications omit issuer, date, identifier, or verification link.
- Claims are too broad, compound, vague, or unsupported by measurable detail the user may be able to provide.
- Chronology has unexplained overlaps or gaps worth confirming.

For every gap, ask one focused question whose answer could produce a canonical fact. Do not treat an absent job-specific qualification as a blocker; the bundle writer must disclose it in match analysis.

## Coverage values

Use `covered`, `partial`, `missing`, or `not_applicable` for: `identity`, `contact`, `profile`, `experience`, `projects`, `education`, `skills`, `languages`, and `certifications`. Identity and contact cannot be `not_applicable`.
