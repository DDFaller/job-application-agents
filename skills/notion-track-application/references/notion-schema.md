# Notion tracking contract

## Database

Find an exact-title `Job Applications` database before creating one. Create it privately at workspace level with:

```sql
CREATE TABLE (
  "Application" TITLE,
  "Status" SELECT('TO_APPLY':gray, 'APPLIED':blue, 'INTERVIEW':yellow, 'FINAL_INTERVIEW':orange, 'OFFER':green, 'REJECTED':red, 'WITHDRAWN':brown),
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

## Page content

Keep sections named `Job Summary`, `Requirements`, `Match Analysis`, `Gaps`, and `Current Documents`. Read the Notion enhanced-Markdown resource before constructing content.

## Status rules

- New bundle: `TO_APPLY`.
- First `APPLIED`: set `Applied At` to the supplied date or current date.
- Interview stages: preserve `Applied At`; update `Next Action At` only when supplied.
- `OFFER`, `REJECTED`, or `WITHDRAWN`: clear `Next Action At` unless explicitly supplied.
- Permit corrections to earlier statuses without deleting history.
