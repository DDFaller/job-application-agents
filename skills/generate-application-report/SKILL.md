---
name: generate-application-report
description: Generate a self-contained offline HTML dashboard from local or Firestore application records, including status funnel, interview rate, sectors, channels, scores, deadlines, stale actions, and links to bundles. Use when the user asks for application analytics or a job-search dashboard.
---

# Generate Application Report

1. Resolve the data root and load current application metadata from the local
   source or an explicitly requested Firestore export. Do not make the report
   a system of record.
2. Normalize legacy statuses and missing fields without dropping records.
   Exclude unsubmitted drafts from submitted-application funnel rates.
3. Run `scripts/generate_application_report.py`; it uses the shared helper,
   escapes all HTML values, and writes one dependency-free HTML file.
4. Include report inputs, generation timestamp, status/sector/channel
   breakdowns, interview progression, score distribution where available,
   and next-action/deadline warnings.
5. Return the report path and input coverage warnings. Regeneration is safe
   and read-only with respect to application state.
