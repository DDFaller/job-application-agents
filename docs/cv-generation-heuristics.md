# CV generation heuristics

The BAO `software-engineer/v002` PDF was used as a local regression reference.
Its one-page French layout was visually acceptable, but the extracted and
source-backed review found four problems:

- the manually edited TeX contained an empty OLX bullet;
- the FAETEC technical course had no dates;
- education labels had unsupported `BAC+5` and `BAC+4` upgrades;
- the sidebar had technical skills and languages but no evidence-backed soft
  skills.

The generator now follows these rules:

1. Render every typed education record exactly once. If its typed record has
   dates, the rendered entry must keep a non-empty date string.
2. Copy an education institution, degree, and field from the typed record.
   Do not add framework equivalences or translate them into a different
   credential.
3. Keep a compact technical-skills section whenever skill evidence exists.
4. Keep a compact soft-skills section whenever the evidence documents
   communication, collaboration, problem-solving, learning, ownership, or
   process discipline. Use an evidence description such as technical sessions
   or review gates instead of an unsupported personality label.
5. In the France profile, render technical skills, soft skills, and languages
   as one-line sidebar sections; keep education and experience in the main
   column.
6. Omit empty highlight lists instead of emitting empty bullets, and use
   controlled spacing between sidebar entries and major sections.
7. Preserve fully qualified contact URLs without adding a second `https://`.

The improved BAO evaluation draft remained one A4 page, retained all four
education stages, added an evidence-backed communication line, removed the
unsupported credential upgrades, and preserved readable whitespace.
