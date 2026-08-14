# Job-driven tailoring

Treat the normalized opening as the selection lens and candidate evidence as the only source of candidate facts.

## Classification

- `computing`: software, data, IT, infrastructure, security, or another primarily technical role.
- `non_computing`: retail, hospitality, logistics, administration, service, manual, or another role whose core work is not computing.
- `mixed`: computing is useful but not the role's sole or primary function.
- `unclear`: the extracted duties do not support a confident classification.

Use `technical` or `balanced` focus for computing jobs, `transferable` or `balanced` for non-computing jobs, `balanced` or `transferable` for mixed jobs, and `conservative` for unclear jobs.

## Evidence selection

1. Derive job priorities only from cited job fields, emphasizing responsibilities and requirements over generic company language.
2. Select candidate facts only when they help establish a priority, a necessary resume identity item, or an honest gap analysis.
3. Put every other candidate fact in `deprioritized_candidate_evidence_ids`. Selected and deprioritized IDs must be disjoint and together cover every candidate fact.
4. Build `fit_arguments` that cite both sides. A coincidental keyword is not enough; describe the supported relationship.
5. Cite all candidate claims with selected evidence. Do not turn an adjacent fact into direct experience.
6. Draft for a balanced one-page résumé. If visual inspection finds the first accepted render conspicuously underfilled, reconsider deprioritized evidence once in this order: relevant work experience, relevant education, then other relevant facts. Move every newly used fact into the selected partition. Stop when the page is balanced or no further relevant evidence exists; never use irrelevant facts as filler.

## Non-computing and minor jobs

Start from the actual duties. Prefer supported evidence of reliability, customer or stakeholder communication, teamwork, organization, languages, documentation, learning, responsibility, and process discipline when those qualities match the opening. Keep true employer names, titles, and dates. Omit irrelevant projects and technology inventories. Technical work may demonstrate a transferable quality, but do not present technical sophistication as the reason for fit unless the posting values it.

Example: for a warehouse role that stresses accurate order handling and teamwork, a supported history of careful operational processes and collaboration can be selected; an unrelated framework list should be deprioritized. For customer service, supported communication and language facts may lead; backend architecture should not.

When classification is unclear, use a conservative focus, avoid speculative tailoring, and surface the uncertainty in the selection rationale.
