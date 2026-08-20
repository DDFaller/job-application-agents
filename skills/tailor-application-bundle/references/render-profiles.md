# Resume rendering profiles

Use `--profile auto|international|france`; `auto` is the default.

- `international` uses the maintainable XeLaTeX template, US Letter paper, no photo, and a one-page maximum.
- `france` uses the maintainable XeLaTeX template, A4 paper, and a one-page maximum. A photo is optional.
- `auto` selects `france` only when the normalized job location clearly identifies France or a recognized French city; otherwise it selects `international`. Pass an explicit profile when geography is ambiguous.

Every profile has a hard one-page maximum enforced with `pdfinfo`; generated PDFs must also contain extractable text. Page-fill visual inspection is intentionally out of scope. Do not stretch prose, enlarge spacing, add irrelevant history, or invent facts to fill the page.

XeLaTeX is the default. Each current version includes editable `resume.tex`,
`letter.tex`, and `preamble.tex`. Use `--render-engine rendercv` only for the
legacy compatibility path.

## Photo provenance

Never generate, infer, scrape, retouch, or choose a candidate photo. A photo is allowed only when the candidate explicitly supplies an approved local JPEG or PNG through `--photo <path>`, or places exactly one file named `profile-photo.jpg`, `profile-photo.jpeg`, or `profile-photo.png` in `~/Documents/job-search/sources/`. That exact filename convention constitutes approval for application rendering.

The renderer validates the extension and file signature, limits the source to 10 MB, copies it into the new application version, records its filename in the manifest, and hashes it with the other artifacts. The copied photo is not an editable current-document source. If no approved photo exists, the France profile renders without one. Multiple conventionally named source photos are an error and require explicit selection.

Examples:

```bash
scripts/render_bundle.py --stage --bundle-json bundle.json --application-root applications/acme/role/id --profile auto
scripts/render_bundle.py --stage --bundle-json bundle.json --application-root applications/acme/role/id --profile france --photo ~/Documents/job-search/sources/profile-photo.jpg
scripts/render_bundle.py --promote applications/acme/role/id/.staging/bundle-abc123 --review-json tailoring-review.json --application-root applications/acme/role/id
```
