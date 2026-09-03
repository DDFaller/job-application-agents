---
name: automate-job-application
description: Inspect target ATS career portals, extract token-optimized form structures, map candidate facts using low-cost models (Gemini 3.6 Flash), autofill application forms via Playwright in supervised mode, and track submission receipts.
model: flash
---

# Automate Job Application Skill

Fill web-based ATS forms (Lever, Ashby, Greenhouse, Workable, and custom
employer portals) in supervised mode while preserving evidence truthfulness,
token efficiency, and a human approval boundary. Dry-run is the default and
supervised mode stops before submission unless the user explicitly opts into
both the CLI flag and the environment gate. This skill never exposes
unattended submission.

---

## 1. Core Model & Token Efficiency Principles

1. **Efficient form analysis**:
   - Use the configured low-cost model when available, but do not assume a
     provider or model name in the workflow contract.

2. **Token Optimization Preprocessor**:
   - Never feed raw, unprocessed HTML pages (>50k tokens) to LLMs.
   - Always run the DOM preprocessor via `scripts/inspect_form.py <url>` or `FormDOMPreprocessor.extract_from_page()`.
   - The preprocessor strips scripts, styles, SVGs, base64 images, and navigation noise, compressing form data by **85% to 98%** (<500 tokens).

3. **Supervised-First Policy**:
   - Always prefer running with **`--mode dry-run`** for first-time form filling.
   - Launches a visible Chrome window, populates 100% of the form, attaches the tailored `resume.pdf` (and `motivation-letter.pdf`), and pauses for user visual verification.
   - In supervised mode, pauses for human verification and does not submit by default.

4. **Authoritative Document Transparency (Mandatory)**:
   - When executing or presenting an application run, the agent must ALWAYS display clickable markdown links (`file:///...`) to the exact `resume.pdf` and `motivation-letter.pdf` (or `motivation-letter.md`) that are being uploaded.


---

## 2. Standard Workflow

```
Target Job URL
      │
      ▼
1. Pre-fetch & Token Pruning:
   Run `scripts/inspect_form.py <url>` ──► Generates compressed form tree (~450 tokens)
      │
      ▼
2. Fact Grounding & Mapping:
   Read candidate identity (`sources/identity.md`) + tailored package (`resume.pdf`)
   Map each form field to authoritative candidate facts (Never hallucinate)
      │
      ▼
3. Supervised Browser Execution:
   Run `python3 scripts/auto_apply.py --app-dir <app-dir> --mode dry-run`
   • Autofills Name, Email, Phone, LinkedIn, GitHub, Portfolio
   • Attaches tailored resume.pdf
   • Checks Legal Work Authorization & Hybrid commitments
   • Captures a reviewable preview without submission
      │
      ▼
4. Receipt & Status Lifecycle:
   Upon submission confirmation:
   • Saves `vNNN/receipt.json` and `vNNN/submission-confirmation.png`
   • Updates `current.json` status to `APPLIED` only after a verified receipt
   • Syncs Notion card and Firestore status to `APPLIED` with `applied_at`
     only after the user-approved submission is confirmed
```

---

## 3. CLI Commands Reference

```bash
# 1. Pre-fetch and inspect compressed form fields:
python3 scripts/inspect_form.py https://jobs.ashbyhq.com/company/role-id

# 2. Supervised autofill for review (no submission by default):
python3 scripts/auto_apply.py \
  --app-dir job-search/applications/<company>/<role>/<id> \
  --mode supervised

# 3. Separate, explicit submission opt-in (only after the user requests it):
JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION \
python3 scripts/auto_apply.py \
  --app-dir job-search/applications/<company>/<role>/<id> \
  --mode supervised --allow-submit

# 4. Dry-run snapshot (Generates preview.png without submitting):
python3 scripts/auto_apply.py \
  --app-dir job-search/applications/<company>/<role>/<id> \
  --mode dry-run
```

---

## 4. Safety & Compliance Rules
   - **Never submit without an explicit user approval**. Submission requires
     the user-requested CLI opt-in, the exact environment gate, and the
     interactive review confirmation. There is no unattended/headless
     submission mode.
   - Do not mask browser automation or bypass portal access controls. Hand
     authentication walls, CAPTCHAs, and blocked pages back to the user.
- **Never fabricate answers** to custom questions; ground all answers in `sources/` curriculum evidence.
- **Always preserve confirmation receipts** in the application version directory.
- Do not place candidate identity, session cookies, Notion tokens, or portal
  credentials in prompts, logs, screenshots, or generated artifacts.
