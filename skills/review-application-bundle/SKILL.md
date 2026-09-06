---
name: review-application-bundle
description: "Independently review one exact humanized application bundle against validated job, candidate role-profile sources, and bundle inputs. Never revise the bundle, spawn agents, render, track, or submit."
---

# Review Application Bundle

Execute only the `independent-review` `StageTask`. Do not delegate and do not
edit the bundle. Verify declared input hashes, then read
`/home/falluba/job-application-agents/skills/tailor-application-bundle/references/job-driven-tailoring.md` and
`/home/falluba/job-application-agents/skills/tailor-application-bundle/references/tailoring-review-template.json`.

Review relevance, factual grounding against candidate role-profile sources
(`sources/<role-profile>/`), seniority, employer/client labels, official education
credentials, acronyms, spelling, complete bullets, motivation-letter quality, and ATS reading order.
When candidate evidence is omitted, factual grounding is verified directly against
the role-profile markdown files and `pre-formatted.tex`.
Treat the constrained Humanizer receipt as provenance, not proof of quality.

Write `tailoring-review.json` with verdict `accept` or `revise`, exact input
hashes, and actionable findings. Validate it with
`/home/falluba/job-application-agents/.venv/bin/python /home/falluba/job-application-agents/skills/tailor-application-bundle/scripts/validate_tailoring_review.py --review <tailoring-review.json>`. For `accept`, return a successful result with
the review hash. For `revise`, return a retryable `bundle_revision_required`
blocker with `restart_stage: bundle-writing` and include the validated review
artifact; the controller rewinds the DAG while retaining accepted upstream
evidence. Do not render, promote, access Notion, or change application status.
