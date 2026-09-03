# Job Integrations Subsystem

The `integrations/` package reads public job-alert emails through Gmail IMAP,
extracts public posting URLs, scrapes and normalizes postings, scores them
against the candidate evidence, and stages qualifying jobs. It never submits
applications, uses credentials on posting sites, or bypasses access controls.

## Gmail API OAuth

The preferred transport is the read-only Gmail API. In Google Cloud Console,
enable the Gmail API, configure the OAuth consent screen with this account as a
test user, create a **Desktop** OAuth client, and download its JSON file. Then:

```bash
export GMAIL_AUTH_MODE=gmail_api
export GMAIL_CLIENT_SECRETS_PATH="$HOME/.config/job-application-agents/gmail-client-secret.json"
python3 scripts/ingest_jobs.py authorize-gmail
python3 scripts/ingest_jobs.py test-connection
```

The first command opens the system browser, saves a refreshable token under
`~/.config/job-application-agents/gmail-token.json`, and requests only
read-only Gmail access. API mode never marks messages read. If API access is
unavailable and `GMAIL_APP_PASSWORD` is configured, ingestion automatically
falls back to the existing IMAP transport. Set `GMAIL_AUTH_MODE=app_password`
to use IMAP directly.

## Provider-first ingestion

The ingestion order is:

```text
Gmail candidates
  -> processed-email ledger (permanent skip by default)
  -> provider aliases in sender/subject/plain body/HTML body
  -> parser -> public scraper -> extractor -> scorer -> staging
```

Provider settings are manually edited in
`integrations/auto_ingest_settings.py`:

```python
PROVIDERS = [LINKEDIN, INDEED]
matches_dict = {
    LINKEDIN: ["linkedin", "linkedinjobs", "linkedin job alerts"],
    INDEED: ["indeed", "indeed jobs", "job alert"],
}
```

`PROVIDERS` selects active providers. Add aliases to the corresponding list;
the validator rejects unknown providers, duplicate aliases, malformed values,
and enabled providers without aliases. Matching is case-insensitive and
punctuation/whitespace-normalized. One email may match multiple providers;
those matches are retained for diagnostics, while the existing parser registry
selects the parser.

Gmail uses mailbox-wide candidate search by default, with `UNSEEN`, `ALL`, and
date-window controls. `--sender` remains an explicit optional narrowing
optimization; it is not the provider correctness filter. An empty `UNSEEN`
search is not silently replaced by a search for recent messages.

## Processed-email ledger

The durable ledger is stored at:

```text
<data-root>/integrations/processed_emails.json
```

The data root can be set with `INTEGRATIONS_DATA_ROOT`, `JAA_DATA_ROOT`, or
`data_root` in the integrations JSON config. Each record stores identity,
content SHA-256, filter matches, parse/staging status, job keys, timestamp, and
an error, but never stores email bodies. Normalized `Message-ID` is the primary
permanent identity; missing Message-ID falls back to folder + IMAP UID. The
content hash is diagnostic only and does not suppress separate messages with
identical templates. Writes are atomic temporary-file replacements.

Checked-but-no-match, matched-and-staged, and failed messages are all skipped
on later runs. Use an explicit recheck command to revisit them:

```bash
python3 scripts/ingest_jobs.py ingest --force-recheck
python3 scripts/ingest_jobs.py ingest --recheck-message-id '<id@example.com>'
python3 scripts/ingest_jobs.py ingest --recheck-uid 123
python3 scripts/ingest_jobs.py ingest --retry-failed
```

Dry-run mode does not stage jobs or update the ledger. Messages are marked read,
when enabled in Gmail configuration, only after their ledger record is durable.

## CLI

```bash
# Validate settings without Gmail access.
python3 scripts/ingest_jobs.py validate-settings

# Normal ingestion; checked messages are skipped permanently by default.
python3 scripts/ingest_jobs.py ingest --providers LINKEDIN,INDEED

# See fetched/skipped/filtered/matched/parsed/staged/failed counters.
python3 scripts/ingest_jobs.py ingest --show-filter-summary

# Show counts and recent metadata without bodies or credentials.
python3 scripts/ingest_jobs.py show-processed

# Existing diagnostics and local parsing remain available.
python3 scripts/ingest_jobs.py test-connection
python3 scripts/ingest_jobs.py parse-email sample_alert.html --sender jobalerts-noreply@linkedin.com
python3 scripts/ingest_jobs.py scrape https://www.linkedin.com/jobs/view/4422257733
```

Gmail job-alert ingestion and application-status email synchronization use
separate workflows and separate ledgers. A job-alert ledger decision never
changes application status records.

## Python API

```python
from integrations import JobIngestionPipeline

pipeline = JobIngestionPipeline()
result = pipeline.run_ingestion(
    limit=15,
    min_match_score=60,
    dry_run=False,
)
print(result.total_emails_fetched, result.total_emails_skipped_already_checked)
print(result.total_jobs_staged)
```

The existing LinkedIn/Indeed parsers, public scrapers, schema-v2 evidence
artifacts, scorer, and destinations remain compatible with this flow.
