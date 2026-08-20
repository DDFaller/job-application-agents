# Application workflow contract

Use `~/Documents/job-search` as the root and create applications at:

`applications/<company-slug>/<role-slug>/<job-id-or-url-hash>/`

Process exactly one opening. In parallel, use one clean-context Luna agent for the job, a distinct candidate-evidence agent on a cache miss, and local XeLaTeX preflight. In managed mode, resolve `sources/current.json`; reuse a validated cache entry when the complete source fingerprint matches, otherwise map the canonical Markdown once while holding the cache-build lock. Never write generated evidence into the source folder. After the job output and candidate evidence validate, run the complete `$tailor-application-bundle` workflow in reuse mode. Tailoring uses a clean-context Terra agent to classify and write the application. A separate clean-context Luna agent remains the semantic authority. After structural validation, run review and XeLaTeX staging concurrently. Promote only the exact accepted bundle. Deterministic scripts verify structure, hashes, evidence references, review integrity, and PDF page/text bounds; agents own semantic judgment. Only the parent may access Notion. New synchronization requires a schema-3 manifest with fresh review status; legacy schema-1/2 versions remain eligible only for retry. Create all PDF and LaTeX upload targets before concurrent uploads; keep page mutation and verification sequential. Send stage transitions to the coordinator and provide a heartbeat at least every 45 seconds while active.

The final response must identify the version directory, generated artifacts, evidence gaps, Notion status, and Notion page URL. Application submission is always out of scope.
