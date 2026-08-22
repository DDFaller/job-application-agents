# Job-driven tailoring

Treat the normalized opening as the selection lens and candidate evidence as the only source of candidate facts. Use the opening to change emphasis, not to erase stable CV context. Select an approved role profile first, then preserve compact baseline context and rank remaining job-specific evidence.

## Approved profile selection

Use the role-profile catalog as a positioning boundary, never as candidate
evidence. For every approved profile, map its stable `MC-*` facts through the
candidate facts' `source_fact_ids`. Score every relevant mapped claim from `0`
through `3` on relevance, evidence strength, specificity, recency, risk, and
redundancy, with cited job evidence and a rationale. Compute:

`relevance * evidence_strength * specificity * recency - risk - redundancy`

A profile is eligible only when mapped evidence covers at least one anchor, two
distinct supporting facts, and cited job priorities without violating its
seniority ceiling or prohibited claims. Sum non-negative claim scores. Select
the highest score; break ties by total evidence strength, total relevance,
lower risk, then stable profile ID.

Headline, summary, fit arguments, highlights, matched analysis, letter claims,
and selection rationale may use only facts in the selected profile's
`allowed_positioning_fact_ids`. Generate headline and summary last. A translated
headline must preserve the canonical profile meaning and seniority.

When no profile is eligible, stop and propose a new evidence-backed profile.
Explain why no approved profile fits and which facts support the proposal. Do
not fall back to a generic résumé.

## Classification

- `computing`: software, data, IT, infrastructure, security, or another primarily technical role.
- `non_computing`: retail, hospitality, logistics, administration, service, manual, or another role whose core work is not computing.
- `mixed`: computing is useful but not the role's sole or primary function.
- `unclear`: the extracted duties do not support a confident classification.

Use `technical` or `balanced` focus for computing jobs, `transferable` or `balanced` for non-computing jobs, `balanced` or `transferable` for mixed jobs, and `conservative` for unclear jobs.

## Evidence selection

Use this order because it is both faster and more reliable than comparing every fact equally with every requirement:

1. Derive job priorities only from cited job fields, emphasizing responsibilities and requirements over generic company language.
2. After approved-profile selection, run a baseline-coverage pass before semantic matching:
   - Preserve the candidate identity, contact, and headline fields as required by the bundle contract.
   - If language facts exist, keep a concise language line by default. Always keep them when the posting names a language, involves customers/public/stakeholders, is international, or makes communication a priority. Do not infer proficiency; if levels are absent, list only the supported language names.
   - If education facts exist, keep the most recent or highest completed education entry by default. Keep additional education when it is required, directly relevant, recent, or needed to explain the candidate's profile. Do not drop all education merely because the role is non-computing.
   - Preserve certifications when current, legally/operationally relevant, explicitly required, or useful evidence of readiness. Preserve chronology-bearing experience facts needed to avoid a misleading work history, even when their details are concise.
   - Represent baseline facts compactly (`one_line` for languages/skills, `education` for education, concise entries for certifications) so preservation does not consume the space needed for relevant experience.
3. Run the job-relevance pass. Select candidate facts that establish a cited priority, support a truthful transferable capability, provide a required baseline context item, or substantiate an honest gap analysis. Rank direct evidence above transferable evidence, and transferable evidence above keyword adjacency.
4. Put every other candidate fact in `deprioritized_candidate_evidence_ids`. Selected and deprioritized IDs must be disjoint and together cover every candidate fact. A fact is not “selected” unless it is cited in authored bundle content; this keeps the artifact validator and the document synchronized.
5. Build `fit_arguments` that cite both sides. A coincidental keyword is not enough; describe the supported relationship.
6. Cite all candidate claims with selected evidence. Do not turn an adjacent fact into direct experience, and do not use a job requirement to upgrade an unsupported language level, degree, certification, or seniority claim.
7. Draft for a one-page résumé. Spend the page budget in this order: required identity/context, relevant experience, relevant education, relevant languages/certifications, then other relevant facts. Compress repeated wording and move secondary details into compact lines before removing baseline context; only then deprioritize the least relevant optional fact. Never use irrelevant facts as filler.

Use typed records as the only source of employer and education display fields.
An employee/intern entry uses `legal_employer`; contractor/freelancer work uses
`contracting_party`. A `client` may appear only with an explicit client-project
label. Copy `institution`, `official_degree`, and `field` from education
records. Omit ambiguous records and surface their candidate-evidence warnings
as gaps.

### Fast preservation heuristics

Apply these as deterministic gates before making nuanced relevance judgments:

| Candidate category | Default treatment | Escalate to job-specific matching when |
| --- | --- | --- |
| Language | Keep a compact line when present | The posting names a language, values public/customer communication, or has an international context |
| Education | Keep the highest/recent completed item | A degree/field is required, directly relevant, recent, or multiple entries clarify chronology |
| Certification | Keep compactly when current or meaningful | The posting requires it, the role is regulated, or it is evidence of operational readiness |
| Identity/contact | Always preserve through the candidate contract | Never; do not tailor these away |
| Experience | Keep role/title/employer/date context; select details by relevance | Always, because omission can distort chronology or seniority |
| Skills/projects | Select only supported priorities or transferable capabilities | The posting makes the technology, method, or project domain useful |

These are retention heuristics, not permission to invent content. When page space is genuinely insufficient, retain the strongest baseline item and record the omitted optional facts as deprioritized; never remove all evidence for a category solely because it did not match a keyword.

## Non-computing and minor jobs

Start from the actual duties. Prefer supported evidence of reliability, customer or stakeholder communication, teamwork, organization, languages, documentation, learning, responsibility, and process discipline when those qualities match the opening. Keep true employer names, titles, and dates. Omit irrelevant projects and technology inventories. Technical work may demonstrate a transferable quality, but do not present technical sophistication as the reason for fit unless the posting values it.

Example: for a warehouse role that stresses accurate order handling and teamwork, a supported history of careful operational processes and collaboration can be selected; an unrelated framework list should be deprioritized. For customer service, supported communication and language facts may lead; backend architecture should not.

When classification is unclear, use a conservative focus, avoid speculative tailoring, and surface the uncertainty in the selection rationale.
