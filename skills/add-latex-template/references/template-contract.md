# Declarative XeLaTeX template contract

An installed template is a directory named by its lower-case slug under
`tailor-application-bundle/assets/latex/templates/`.

## Required files

`template.json` contains exactly:

```json
{
  "schema_version": 1,
  "id": "template-slug",
  "display_name": "Human name",
  "description": "Short design description",
  "engine": "xelatex",
  "main": "resume.tex.tmpl",
  "required_packages": ["fontspec.sty"],
  "required_fonts": ["TeX Gyre Heros"],
  "fragments": {
    "section": ".jaa/section.tex.tmpl",
    "highlight": ".jaa/highlight.tex.tmpl",
    "experience": ".jaa/experience.tex.tmpl",
    "education": ".jaa/education.tex.tmpl",
    "normal": ".jaa/normal.tex.tmpl",
    "one_line": ".jaa/one-line.tex.tmpl",
    "publication": ".jaa/publication.tex.tmpl",
    "bullet": ".jaa/bullet.tex.tmpl",
    "numbered": ".jaa/numbered.tex.tmpl",
    "reversed_numbered": ".jaa/reversed-numbered.tex.tmpl",
    "text": ".jaa/text.tex.tmpl"
  }
}
```

All paths are relative, remain inside the template directory, and name regular
files. Supporting `.cls`, `.sty`, fonts, images, and TeX partials may sit
alongside these files. Do not include generated PDFs or auxiliary build files.

## Tokens

Use `[[JAA:FIELD]]` for an escaped value. Use
`[[JAA:IF FIELD]]...[[JAA:END FIELD]]` for optional content; nested conditional
blocks are not supported. Template-authored TeX remains raw, while every value
inserted through a token is LaTeX-escaped.

The main template must use `NAME`, `HEADLINE`, `LOCATION`, `CONTACT`, `PROFILE`,
and `SECTIONS`. The section fragment uses `TITLE` and `ITEMS`; the highlight
fragment uses `TEXT`.

Entry fragment fields are:

- `experience`: `COMPANY`, `POSITION`, `LOCATION`, `DATES`, `SUMMARY`, `HIGHLIGHTS`
- `education`: `INSTITUTION`, `AREA`, `DEGREE`, `LOCATION`, `DATES`, `SUMMARY`, `HIGHLIGHTS`
- `normal`: `NAME`, `LOCATION`, `DATES`, `SUMMARY`, `HIGHLIGHTS`
- `one_line`: `LABEL`, `DETAILS`
- `publication`: `TITLE`, `AUTHORS`, `JOURNAL`, `DATES`, `DOI`, `URL`, `SUMMARY`
- `bullet`, `numbered`, `reversed_numbered`, and `text`: `TEXT`

Every fragment must retain every field token for its entry type. Optional
values may be hidden with conditionals, but adapters must not discard data the
bundle supplies. The validator exercises all fields and requires the synthetic
identity, section titles, item anchors, and highlights to remain extractable in
bundle order.

## Safety and compatibility

- Use one column and preserve semantic source order.
- Compile without shell escape; do not use shell execution, Lua execution,
  external pipes, absolute includes, parent traversal, or arbitrary file I/O.
- Keep the résumé to one page and text extractable with `pdftotext`.
- List every non-local LaTeX package in `required_packages` by `.sty` filename.
- List every non-local font family in `required_fonts`; locally bundled fonts
  stay inside the project and need not be listed.
- Report missing packages and fonts, but never install or download them.
- Keep sample candidate data out of installed files.
- Let the template define its own paper size; geographic render profiles apply
  only to the built-in template.
