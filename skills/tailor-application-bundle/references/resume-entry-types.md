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

Every object in `highlights` is `{ "text": ..., "evidence_ids": [...] }`. All authored claims, including one-line details and standalone text, must be supported by the entry's `evidence_ids`; highlights additionally carry their own evidence IDs. Do not add empty sections. Prefer one-line entries for skills and languages. Keep the complete resume within two US Letter pages under the fixed RenderCV Sb2nov theme.
