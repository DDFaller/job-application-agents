---
name: render-application-bundle
description: "Deterministically stage and promote one exact independently accepted application bundle into editable LaTeX and PDFs. Never make semantic edits, spawn agents, access Notion, or submit."
---

# Render Application Bundle

Execute only the `render-promotion` `StageTask`. Do not delegate. Require the
exact bundle and a validated independent review whose verdict is `accept` and
whose bundle hash matches.

Run `/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/render_bundle.py --preflight`, then
stage with `--profile auto`. French locations use the preserved A4 France
template and approved canonical photo; other locations use the compact
international template. Verify page count, extractable text, reading order,
frozen TeX/assets, and returned hashes. Every résumé must be at most one page.

Promote only the exact accepted staging directory. Promotion atomically creates
the next version and updates `current.json`; never edit a historical version.
Return hashed references to the version manifest, résumé PDF, letter PDF, and
editable TeX sources in `StageResult`. Deterministic tool or transient render
failures are retryable; a semantic mismatch is non-retryable and belongs back
at bundle writing/review. Do not access Notion, submit, or mark `APPLIED`.
