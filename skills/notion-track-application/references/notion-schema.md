# Notion tracking contract

## Database

Find an exact-title `Job Applications` database before creating one. Create it privately at workspace level with:

```sql
CREATE TABLE (
  "Application" TITLE,
  "Status" SELECT('TO_APPLY':gray, 'APPLIED':blue, 'REAPPLY':purple, 'INTERVIEW':yellow, 'FINAL_INTERVIEW':orange, 'OFFER':green, 'REJECTED':red, 'WITHDRAWN':brown),
  "Company" RICH_TEXT,
  "Role" RICH_TEXT,
  "Location" RICH_TEXT,
  "Work Model" SELECT('On-site':yellow, 'Hybrid':blue, 'Remote':green, 'Unspecified':gray),
  "Source" SELECT('LinkedIn':blue, 'Personio':green, 'Other ATS':purple, 'Pasted text':gray),
  "Job URL" URL,
  "Source Job ID" RICH_TEXT,
  "Current Version" RICH_TEXT,
  "Generated At" DATE,
  "Applied At" DATE,
  "Next Action At" DATE,
  "Local Bundle Path" RICH_TEXT,
  "Match Summary" RICH_TEXT,
  "Notes" RICH_TEXT
)
```

Create a `Pipeline` board with `GROUP BY "Status"` and an `All Applications` table sorted by `Generated At` descending. Fetch the database to obtain its database and data-source IDs.

`Generated At` records the generation time of the current bundle and is the
sole age source for bundle-recency, generation-completeness, and stale-card
requeue checks. `Applied At` records the actual submission time and must not be
inferred from `Generated At` or used as a requeue fallback.

## Page content

Keep sections named `Job Summary`, `Requirements`, `Match Analysis`, `Gaps`, and `Current Documents`. `Current Documents` contains the current résumé and letter PDFs plus `resume.tex`, `letter.tex`, and `preamble.tex`. Replace that section only after the schema-3 manifest hashes validate and semantic-review status is fresh. Read the Notion enhanced-Markdown resource before constructing content.

## Status rules

- New bundle: `TO_APPLY`.
- First `APPLIED`: set `Applied At` to the supplied date or current date.
- `REAPPLY`: set only from `APPLIED` by `$requeue-unanswered-applications` when the card's whole local-calendar age from `Generated At` is greater than or equal to the follow-up threshold, default `14` days, or by an explicit user request. A normal board review applies this transition automatically; an explicitly requested preview, audit, or dry run is read-only. Preserve `Generated At` and `Applied At`; update `Next Action At` only when supplied. A database created before this option existed lacks it; add only the missing option in place instead of recreating the database.
- Interview stages: preserve `Applied At`; update `Next Action At` only when supplied.
- `OFFER`, `REJECTED`, or `WITHDRAWN`: clear `Next Action At` unless explicitly supplied.
- Permit corrections to earlier statuses without deleting history.
