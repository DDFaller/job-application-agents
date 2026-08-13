# Resume rendering profiles

Use `--profile auto|international|france`; `auto` is the default.

- `international` preserves the official RenderCV Sb2nov theme, US Letter paper, no photo, and a two-page maximum.
- `france` uses the official Classic theme, A4 paper, left-aligned header, and a one-page maximum. A photo is optional.
- `auto` selects `france` only when the normalized job location clearly identifies France or a recognized French city; otherwise it selects `international`. Pass an explicit profile when geography is ambiguous.

## Photo provenance

Never generate, infer, scrape, retouch, or choose a candidate photo. A photo is allowed only when the candidate explicitly supplies an approved local JPEG or PNG through `--photo <path>`, or places exactly one file named `profile-photo.jpg`, `profile-photo.jpeg`, or `profile-photo.png` in `~/Documents/job-search/sources/`. That exact filename convention constitutes approval for application rendering.

The renderer validates the extension and file signature, limits the source to 10 MB, copies it into the new immutable application version, records its filename in the manifest, and hashes it with the other artifacts. If no approved photo exists, the France profile renders without one. Multiple conventionally named source photos are an error and require explicit selection.

Examples:

```bash
scripts/render_bundle.py --bundle-json bundle.json --application-root applications/acme/role/id --profile auto
scripts/render_bundle.py --bundle-json bundle.json --application-root applications/acme/role/id --profile france --photo ~/Documents/job-search/sources/profile-photo.jpg
```
