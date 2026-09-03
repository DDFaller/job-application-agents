# Playwright Auto-Apply Engine & Human-in-the-Loop Architecture

The **Auto-Apply Engine** (`job_application_agents/auto_apply`) automates the filling, PDF attachment, mobile/web review, and multi-signal submission verification for employer job applications.

---

## 1. Decoupled Human-in-the-Loop Lifecycle

```mermaid
sequenceDiagram
    participant Agent as AI Agent / CLI
    participant DOM as Playwright Chromium
    participant Pre as FormDOMPreprocessor
    participant Draft as DraftService
    participant User as User (Mobile PWA / Web UI)
    participant Verifier as SubmissionVerifier
    participant Cloud as Firestore & Notion

    Agent->>DOM: Open Target Job Opening
    DOM->>Pre: Extract Active Interactive Controls
    Pre-->>Draft: Token-Compressed Tree (📉 97.7% reduction)
    Draft->>DOM: Autofill Known Identity Facts & Upload resume.pdf
    Draft-->>User: Emit ApplicationDraft (Rev 1, sha256 hash)
    Note over Draft,User: PAUSE: Mobile Push Notification

    opt User Edits Field (e.g. Years experience: 4 ➔ 6)
        User->>Draft: PATCH field edits
        Draft->>DOM: Apply edits to live browser input
        Draft-->>User: Incremented ApplicationDraft (Rev 2, fresh sha256 hash)
    end

    User->>Draft: Approve Submission (Signed ApprovalToken with Hash & Rev)
    Draft->>Draft: Assert ApprovedHash == LiveBrowserHash
    Draft->>DOM: Capture pre-submit.png & Click Submit
    DOM->>Verifier: Inspect URL redirect, success text, confirmation ID
    Verifier-->>Draft: VerificationScore & Verdict (SUBMITTED_CONFIRMED)
    Draft->>DOM: Capture submission-success.png
    Draft->>Cloud: Update Status to APPLIED & attach Proof Package
```

---

## 2. Core Subsystem Modules

| Module | Responsibility |
|---|---|
| [`draft_models.py`](file:///home/falluba/job-application-agents/job_application_agents/auto_apply/draft_models.py) | `ApplicationDraft`, `ApplicationField`, `ApprovalToken`, `VerificationScore`, `FieldSource`, `ApplicationState`. |
| [`preprocessor.py`](file:///home/falluba/job-application-agents/job_application_agents/auto_apply/preprocessor.py) | `FormDOMPreprocessor` compressing raw HTML pages into token-efficient JSON form trees (<500 tokens). |
| [`draft_service.py`](file:///home/falluba/job-application-agents/job_application_agents/auto_apply/draft_service.py) | `DraftService` managing draft extraction, revision increments, cryptographic lock enforcement, and proof archiving. |
| [`verifier.py`](file:///home/falluba/job-application-agents/job_application_agents/auto_apply/verifier.py) | `SubmissionVerifier` running multi-signal verification scoring across redirect URLs, DOM text, and confirmation IDs. |
| [`service.py`](file:///home/falluba/job-application-agents/job_application_agents/auto_apply/service.py) | `AutoApplyService` transparent browser lifecycle coordinator with supervised review and clickable document links. |
| [`scripts/draft_review.py`](file:///home/falluba/job-application-agents/scripts/draft_review.py) | Terminal TUI and local web review dashboard (`http://127.0.0.1:8765`) for 1-click mobile/desktop draft approvals. |

---

## 3. Key Architectural Guardrails

1. **No Blind Submissions**:
   - Submissions require an explicit `ApprovalToken` containing the exact `revision` number and cryptographic `draft_hash` (SHA-256).
   - If live form inputs diverge after approval, submission is halted.

2. **Never Blindly Retry Uncertain Submissions**:
   - If network drops or confirmation DOM cannot be verified, status transitions to `SUBMISSION_UNCERTAIN`.
   - The engine **never retries blindly**, preventing duplicate employer submissions.

3. **Complete Proof Package**:
   - Every submission automatically saves:
     - `pre-submit.png`: Exact state of all form fields before click.
     - `submission-success.png`: Confirmation screen.
     - `proof-package.json`: Form answers, confirmation ID, verification score, timestamps, and resume path.

4. **Respect Portal Boundaries**:
   - Dry-run is the default. Submission additionally requires the exact
     `JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION` deployment gate, an
     explicit CLI opt-in, and interactive confirmation. Authentication walls,
     CAPTCHAs, and access restrictions are handed back to the candidate.
