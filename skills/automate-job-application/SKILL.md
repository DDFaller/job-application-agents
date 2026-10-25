---
name: automate-job-application
description: Inspect ATS forms, map verified candidate facts, fill applications through Playwright or invisible_playwright, preserve login sessions and exclusions, and record verified submission receipts.
---

# Automate Job Application

Use the local browser workflow for employer portals and ATS forms. Ground answers
in candidate evidence and the current user's instructions. Current submission
authorization supersedes an older manual-only preference; do not ask for it again.
Preparation, preview and a final click are different from confirmed submission.

## Input and candidate evidence

- When the user supplies email job links, preserve a private queue of canonical
  job URLs and deduplicate against receipts and uncertain prior attempts. For
  LinkedIn use `https://www.linkedin.com/jobs/view/<id>/`; discard email tracking,
  signature and OTP query parameters before tools, logs or records receive them.
- Read the candidate's approved sources and relevant application history. Never
  invent work authorization, language proficiency, availability, pay currency,
  coursework, project usage or years of experience to satisfy a form.
- For jobs the user explicitly asks to apply to, prepare with `--prepare-selected`.
  Report the evidence-based fit score and unresolved gaps without treating a weak
  score as withdrawal of that instruction. Verify required form answers separately;
  unknown fit does not authorize inventing an answer or making a false attestation.
- When the user requests junior CVs despite weak experience, use the batch
  controller's `--junior-tailoring-instruction <private-file>` preparation option
  and the [selection contract](../select-application-profile/references/contracts.md).
  Keep gaps truthful and select relevant transferable evidence. Actual study
  experience can appear in skills with its context; a missing skill is not study
  experience. Document preparation does not certify submission eligibility.
- Use the accepted, independently reviewed application bundle. Show clickable
  Markdown links to the exact CV and letter before upload. Honor requested
  filenames; never select an arbitrary PDF. Use `--resume` and `--letter` for
  reviewed copies whose filenames differ from the bundle's defaults.
- Avoid unsolicited commentary about application automation in employer-facing
  copy. Answer direct questions or attestations truthfully. Leave unsupported
  required answers pending; do not mark them positive by default.

## Browser setup and persistent login

The local inspection and application CLIs share
`job_application_agents.auto_apply.browser.application_browser`. It yields a
context for either engine. Ordinary Playwright remains the installation default;
use `--browser invisible` when the user requests invisible_playwright.

```bash
.venv/bin/python -m pip install -e '.[browser-invisible]'
.venv/bin/python -m invisible_playwright fetch
```

The optional integration pins invisible-playwright 0.39.0 / invisible-core
50.47.0, inspected against [upstream](https://github.com/feder-cr/invisible_playwright/tree/9a1501af7ad0c368a80950b28a8df783c01b4434).
The adapter supports ordinary locators, uploads and persistent sessions; it does
not expose proxy rotation, fingerprint tuning, CAPTCHA preparation or solvers.
Do not switch engines or identities to retry an excluded/challenged website.
The package is not a guarantee against detection. Its Linux headless mode needs
Xvfb; use `--headed` on a desktop without Xvfb. Chromium CDP, HAR and tracing are
not interchangeable with this Firefox backend.

Keep `--browser-profile <private-data-root>/auto-apply/browser-profiles/<name>`
outside the repository. Use separate directories for Chromium and Firefox;
existing Chrome logins do not automatically transfer. Reuse the same directory
for subsequent inspection and application. Never copy cookies into prompts or
inspect passwords. To let the user sign in normally:

```bash
.venv/bin/python scripts/inspect_form.py <login-or-job-url> \
  --browser invisible --headed --wait-for-login \
  --browser-profile <private-data-root>/auto-apply/browser-profiles/invisible
```

The user signs in in the visible browser, then the terminal continues. This is
an authentication step, not additional permission to submit. Do not navigate
away while the user is entering credentials.

## Inspect, fill, verify

Use `FormDOMPreprocessor.extract_from_page()` or the inspection CLI to extract
compact form fields instead of passing raw HTML to a model. Verify required
fields, exact document inputs, custom questions and final submit control.

Resolve ordinary cookie overlays using their visible consent controls (prefer
necessary cookies only). Use a visible button with the exact accessible name;
the first text match may be a hidden duplicate. After an application-opening
click, inspect newly opened pages as well as the original page. Ericsson's
Eightfold listing, for example, opens its SuccessFactors application in a new
page. These UI conditions are not evidence of bot detection. Check the employer
and role again after redirects, because public listing and internal ATS IDs may
differ.

An empty top-level form extraction can mean the form is inside an iframe. Inspect
the visible frames and their public URLs, check their hosts against exclusions,
and inspect the actual form before declaring it missing. Ignore empty
`about:blank` frames. Cegedim's application opens a consent iframe; its visible
consent label is clickable even when the styled checkbox input fails hit testing.
Click the associated label normally, then verify `is_checked()`. Do not force
clicks or set consent through DOM mutation. Cookie text and accessible names can
differ; match the observed visible button text when an exact role name fails.
After a modal closes, verify visibility or absence directly: a timeout waiting
for a removed selector is not a website rejection.

SmartRecruiters can render fields inside open shadow roots that the compact DOM
extractor does not include. Inspect the visible controls with Playwright locators
before declaring required fields absent. A custom component and its inner input
can share an ID; use the observed accessible textbox name or `input#<id>` to
resolve the editable element unambiguously. Select a visible location suggestion
and verify the phone country code rather than relying on the browser's defaults.

Keep authentication and missing facts distinct from browser failures. JOIN can
require sign-in before the form. Personio may require language levels with no
"none" option, and SuccessFactors may require office attendance, postal code
and a conflict-of-interest declaration. Never choose a positive language level,
invent a postal code, or default a conflict declaration to "No". Preserve the
prepared bundle and request the missing answer or ordinary browser sign-in.

```bash
.venv/bin/python scripts/inspect_form.py <job-url> --browser invisible --headed
.venv/bin/python scripts/auto_apply.py --app-dir <application-root> \
  --profile <private-candidate-profile.json> --browser invisible \
  --mode dry-run --headed --resume <exact-reviewed-cv.pdf>
```

Dry-run and supervised mode without `--allow-submit` fill a preview and stop.
Unknown/custom answers need evidence and review; drivers do not claim every
field is filled. The autofill path must never call a solver capable of final
submission. For an already user-authorized submission after reviewing the exact
filled form, the CLI also requires its deployment gate and terminal confirmation:

```bash
JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION \
.venv/bin/python scripts/auto_apply.py --app-dir <application-root> \
  --profile <private-candidate-profile.json> --browser invisible \
  --mode supervised --allow-submit --resume <exact-reviewed-cv.pdf>
```

Direct Playwright work uses the same `application_browser`, `PortalGuard` and
`form_input(page)` helpers. The shared `PacedFormInput` uses 50 ms per typed
character and 1,000 ms between different fields, including uploads, selects,
checkboxes and choice clicks. `slow_mo` does not replace character timing.

## Website exclusions

Load `<data-root>/auto-apply/excluded-sites.json` before navigation. `PortalGuard`
blocks requests to excluded hosts, checks the final page before every paced
input, and persists observed verification challenges. Check application-link
hosts before following them and final redirect URLs before interaction. A
malformed ledger stops the run. Keep exact-host exclusions by default; apply
provider-wide exclusions only when the user requests them.

A visible CAPTCHA or explicit automation rejection stops that website. Record
only a hostname and short public observation, without candidate answers or
query tokens. Do not remove challenges or retry through another host/API.
Distinguish challenges from static privacy footers, login pages, expired jobs,
validation errors and unexplained 403/5xx responses. State the observed reason;
the detector's internal cause is usually unknown. Repair ordinary selectors,
labels and upload behavior only on accessible forms.

Verify uploaded documents in the portal's attachment list. Personio can clear
the native file input after uploading and list the filename with a remove
control; an empty `input.files` alone does not mean the upload failed. Check the
exact displayed filename and visible upload errors before submitting.

Teamtailor can regenerate radio-input IDs when an application form reloads.
Resolve the current question and accessible answer label before selecting it;
do not reuse a numeric ID from an earlier page instance. Leave optional future
recruitment consent unchecked unless the candidate has authorized it.

## Receipts and recovery

The local service writes submission intent before clicking and retains it if the
browser fails. It requires a new visible application acknowledgement before
marking `APPLIED`; driver `success=True`, HTTP 200, URL changes or disappearing
buttons alone do not count. Otherwise record `SUBMISSION_UNCONFIRMED` and do not
retry until employer history or email resolves it. Check receipts before reruns.

A final-click exception can arrive after input was dispatched. Ashby has returned
"mouseup landed on span" while leaving the completed form visible. Continue a
bounded read-only observation for a fresh acknowledgement, and preserve the
intent and screenshot if none appears. Do not classify this as bot detection or
click again merely because the browser reported an error. Keep the browser event
loop running during that observation so pending page requests can finish.
Ashby's observed success text includes "Your application was successfully
submitted." The local acknowledgement matcher recognizes this wording. If a
new visible receipt is clear but a matcher misses it, preserve the exact text and
screenshot, reconcile the receipt, and fix the matcher with regression coverage
instead of submitting again.
Lity's visible receipt says "nous avons bien reçu votre candidature"; it is also
recognized. Preserve its confirmation before closing the application modal.
Personio employers can use "We received your application" without "have".
Recognize that wording only when it is newly visible after the submission;
reconcile an initially missed receipt from its saved text and screenshot without
clicking submit again.

For Cegedim, uploading attachments is separate from selecting the CV: use
"Définir comme CV" on the reviewed résumé, leaving the letter as an additional
document. Its final step can require an exact availability date even after the
identity step is complete. Ask for that date when unknown; an address or a
relocation confirmation does not establish availability.

Store exact document paths and hashes, time, backend and private confirmation
screenshot in the application version directory. Count only confirmed submissions
against the requested batch size. Keep screenshots, profiles and receipts under
the private data root; do not print contacts, passwords, tokens or filled answers
in general logs. Report prepared, blocked, unconfirmed and confirmed separately.

Resolve the actual application record before filling. A render result may point
to worker-owned copies under `.orchestration`, so a PDF's parent is not always
the canonical application version. Verify the promoted documents against the
accepted hashes and keep receipts and status updates under `applications/`;
preserve the controller's finalized state and hashed stage artifacts.

These browser options apply to the local CLIs. The separate cloud worker and
phone-review launchers are not silently migrated to this engine.
