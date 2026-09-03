# Resume rendering profiles

Use `--profile auto|international|france`; `auto` is the default.

- `international` uses the preserved compact downloaded international design on US Letter paper. It is one column, has no photo, and renders sections in bundle order.
- `france` uses the preserved downloaded `main.tex`/`cv.cls` A4 design with colored left and right columns and a circular candidate photo. The left sidebar is reserved for identity, technical skills, soft skills, and languages as compact `one_line` sections; profile, experience, all education records, optional projects, and other detailed sections render in the main column.
- `auto` selects `france` only when the normalized job location clearly identifies France or a recognized French city; otherwise it selects `international`. Pass an explicit profile when geography is ambiguous.

Every profile has a hard one-page maximum enforced with `pdfinfo`. Generated PDFs must contain extractable text and pass their profile-specific reading-order contract: sequential bundle order internationally, and left-column identity/sidebar content followed by the right-column headline/profile/main content for France. The France check uses raw PDF content order so visual row alignment cannot scramble the two semantic columns. Page-fill visual inspection is intentionally out of scope. Do not stretch prose, add irrelevant history, or invent facts to fill the page.

### France visual hierarchy and spacing

For the France profile, preserve this visual reference when constructing new
CVs:

- Bold the company/employer, institution, and project name.
- Bold the experience position and education degree/field; keep location and
  dates italic or regular so they remain secondary.
- Keep contact methods on separate readable lines, with small vertical gaps
  between email, phone, and social-link groups.
- Keep technical skills, supported soft skills, and languages in the left
  sidebar as compact one-line category entries. Use controlled `2pt` spacing
  between entries rather than blank source lines.
- In the main column, use `\medskip` after major section headings and between
  major experience entries; use `\smallskip` between education entries.
- Use short bullet lists with approximately `1--2pt` between bullets and no
  filler spacing. Place optional personal projects after education so they are
  the first content removed when the one-page render is too tall.

XeLaTeX is the only renderer. Each current version includes editable `resume.tex`, `letter.tex`, and `preamble.tex`, the selected template's supporting files, and a frozen template-source snapshot.

## Imported templates

Use `--template <slug>` only when the user explicitly selects a template installed by `$add-latex-template`. Omitting it selects the automatic geographic built-ins. An imported template controls its own paper size and layout, cannot be combined with an explicit geographic profile or photo, and must pass the same one-page, extractable-text, and declared reading-order gates.

Every render records the selected template fingerprint, copies the exact master project under `template-source/`, and includes its runtime assets in the version. Editing a shared installed master changes future renders only; rebuilding an existing application uses its frozen snapshot and runtime files.

## Photo provenance

The France profile requires a candidate-approved local JPEG or PNG. Resolution order is:

1. an explicit `--photo <path>`;
2. exactly one file named `profile-photo.jpg`, `profile-photo.jpeg`, or `profile-photo.png` in `~/Documents/job-search/sources/`.

The filename convention constitutes approval for application rendering. The renderer never generates, scrapes, retouches, or chooses a photo. It validates the file signature and 10 MB limit, copies it into the staged application under `profile-photo.<ext>`, records it in the manifest, and hashes it with the other artifacts. Missing or multiple canonical photos are errors for the France profile. International and imported templates reject `--photo`.

Examples:

```bash
scripts/render_bundle.py --stage --bundle-json bundle.json --application-root applications/acme/role/id --profile auto
scripts/render_bundle.py --stage --bundle-json bundle.json --application-root applications/acme/role/id --profile france --photo ~/Documents/job-search/sources/profile-photo.jpg
scripts/render_bundle.py --stage --bundle-json bundle.json --application-root applications/acme/role/id --template compact-modern
scripts/render_bundle.py --promote applications/acme/role/id/.staging/bundle-abc123 --review-json tailoring-review.json --application-root applications/acme/role/id
```
