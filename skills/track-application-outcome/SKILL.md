---
name: track-application-outcome
description: Record application outcomes such as interview stages, assessments, offers, rejection, withdrawal, silence, feedback, and draft follow-ups across the local application archive, Firestore, and Notion. Use when the user reports what happened after applying or asks which applications need follow-up. Never send messages or infer outcomes.
---

# Track Application Outcome

Use the existing application version as the document-of-record and the
Notion schema as the board contract.

1. Identify one application by canonical URL, source ID, company, and role;
   list ambiguities instead of guessing.
2. Accept an explicit user outcome or a source-cited approved email-sync
   proposal. Record an append-only outcome event with timestamp, source,
   stage, feedback, and user notes; preserve submitted document hashes.
3. Validate the requested status transition with the shared lifecycle rules.
   Update local metadata, Firestore, and Notion consistently while preserving
   unrelated fields. Never set `APPLIED` without a verified submission receipt.
4. For `followup`, find open quiet applications using `Generated At` or the
   explicitly configured response timestamp, default threshold 14 days,
   maximum two drafts. Draft only; do not send or mark an application as
   contacted. Use claims from the submitted materials and record the draft as
   pending approval.
5. Return changed records, skipped ambiguities, and the next human action.

Use explicit preview/dry-run for batch changes. Final statuses are not silently
reopened; corrections require an explicit user instruction.
