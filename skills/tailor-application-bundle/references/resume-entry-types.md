# Resume entry types

Every `resume_sections[].items[]` object contains `type`, `evidence_ids`, and the exact fields listed below. Use the most specific type supported by the evidence. Dates are display strings in the posting language; use `null` when absent.

- `experience`: `company`, `position`, `location`, `dates`, `summary`, `highlights`
- `education`: `institution`, `area`, `degree`, `location`, `dates`, `summary`, `highlights`
- `normal`: `name`, `location`, `dates`, `summary`, `highlights` (projects, certifications, awards with detail)
- `one_line`: `label`, `details` (skills, languages, concise facts)
- `publication`: `title`, `authors`, `journal`, `dates`, `doi`, `url`, `summary`
- `bullet`: `text`
- `numbered`: `text`
- `reversed_numbered`: `text`
- `text`: `text`

Every object in `highlights` is `{ "text": ..., "evidence_ids": [...] }`. All authored claims, including one-line details and standalone text, must be supported by the entry's `evidence_ids`; highlights additionally carry their own evidence IDs. Do not add empty sections. When supported evidence exists, technical skills are mandatory, and evidence-backed soft skills are mandatory; unsupported generic personality claims remain prohibited. Prefer one-line entries for technical skills, soft skills, and languages. Preserve every unambiguous education record, using compact `education` entries when necessary, and preserve its typed dates whenever present. Target one page and never exceed one page under either rendering profile. Under the France profile, one-line technical skills, soft skills, and languages are placed in the left sidebar; education, experience, and optional project details remain in the main column.

For `experience`, copy `company` from the matching typed record's
`legal_employer` or `contracting_party`; never use its `client`. Label a client
project inside the summary/highlights only when the typed record supplies it.
For `education`, copy `institution`, `degree`, and `area` exactly from
`institution`, `official_degree`, and `field`. Do not synthesize or translate a
credential into a different qualification.

For the France visual profile, the renderer formats experience companies,
education institutions, and project names in bold. Experience positions and
education degrees/fields are also bold; dates, locations, and technology lines
remain secondary styling.

When a typed education record contains dates, its `education` entry must retain
a non-empty date string. A complete bundle must render every typed education
record exactly once; compact wording is allowed, but dropping a record is not.
