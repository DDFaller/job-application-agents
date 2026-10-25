# Job-driven tailoring

Treat the normalized opening as the selection lens and the candidate's role-profile sources as the source of candidate facts. Use the opening to adjust emphasis and alignment, never to fabricate experience or distort stable CV context.

## Role-profile sources workflow (Standard)

In standard batches, candidate information is organized under `~/Documents/job-search/sources/<role-profile>/` with standard markdown files:
- `identity.md` — name, headline, location, and verified contact/social URLs.
- `experience.md` — work history, employer/client relationships, responsibilities, and achievements.
- `education.md` — institutions, official degrees, specializations, and dates.
- `skills.md` — technical, data, platform, and observability capabilities.
- `projects.md` — standalone prototypes, hackathons, and technical projects.
- `languages.md` — spoken languages and verified proficiency levels.
- `pre-formatted.tex` — authoritative 1-page XeLaTeX CV reference demonstrating optimal phrasing, structure, formatting, and page-budget allocation.

1. **Role Profile Selection**: New batches use the evidence-bound `profile-selection` stage and its approved positioning library, not profile-name keyword matching. The library references canonical source folders without duplicating facts. `match_role_profile()` remains only a legacy helper.
2. **Reference Alignment**: The author consults `pre-formatted.tex` for the profile to model section ordering, entry formats, and bullet phrasing.
3. **Targeted Tailoring**: Select and prioritize the most relevant experience and skills for the opening, while preserving truthful baseline context (education, languages, core contact).
4. **Validation**: The authored bundle is validated with `validate_bundle.py`. When candidate evidence is omitted, strict `E###` citation gates are bypassed while structural and document gates remain enforced.

## Legacy approved profile selection (Schema-3 Reference)

When running legacy batches with `candidate-evidence.json` and a compiled role-profile catalog:
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

## Cover-letter narrative order

Always organize the letter body in this order, after the salutation:

1. **Introduce the candidate.** Open in the first person with the candidate's professional positioning, a concise relevant background, and the role sought. Do not open with the company's needs or a technical achievement inventory.
2. **Explain the attraction to the company.** Identify one or two concrete aspects of the company, team, product, or work described in the supplied sources, and explain their appeal. Avoid generic praise, invented personal passions, unsupported company claims, or pretending to have followed the company for years.
3. **Demonstrate the mutual fit.** Connect specific company or role needs to a small number of supported candidate examples and the contribution those examples enable. Make the relationship explicit rather than listing matching technologies or repeating the CV.

Close with a brief invitation to discuss the role. Keep the letter within one readable page, preserve truthful language levels and other necessary qualifications, and retain internal citations for both candidate and company claims. The three moves should read as connected prose, without visible section labels. Humanization and review must preserve and check this order.

## Evidence selection

Use this order because it is both faster and more reliable than comparing every fact equally with every requirement:

1. Derive job priorities only from cited job fields, emphasizing responsibilities and requirements over generic company language.
2. After approved-profile selection, run a baseline-coverage pass before semantic matching:
   - Preserve the candidate identity, contact, and headline fields as required by the bundle contract.
   - If language facts exist, keep a concise language line by default. Always keep them when the posting names a language, involves customers/public/stakeholders, is international, or makes communication a priority. Do not infer proficiency; if levels are absent, list only the supported language names.
   - If education facts exist, preserve every unambiguous education record by default. Compress wording and details to fit the page, but do not remove an education stage merely because it is not directly related to the opening. Copy each institution, official credential, field, and date from its typed record.
   - If supported technical-skill facts exist, always include a compact technical-skills section. Tailor its ordering and grouping to the opening, but do not remove the section. In the France profile, render technical skills as `one_line` sidebar entries.
   - If supported soft-skill facts exist, always include them as a compact, evidence-backed sidebar section in the France profile (and a compact section in the international profile). Derive the label conservatively from documented communication, collaboration, problem-solving, learning, ownership, or process-discipline evidence; cite the underlying facts. Do not manufacture personality claims from job requirements.
   - Preserve certifications when current, legally/operationally relevant, explicitly required, or useful evidence of readiness. Preserve chronology-bearing experience facts needed to avoid a misleading work history, even when their details are concise.
   - Represent baseline facts compactly (`one_line` for technical skills, soft skills, and languages; `education` for every education record; concise entries for certifications) so preservation does not consume the space needed for relevant experience.
3. Run the job-relevance pass. Select candidate facts that establish a cited priority, support a truthful transferable capability, provide a required baseline context item, or substantiate an honest gap analysis. Rank direct evidence above transferable evidence, and transferable evidence above keyword adjacency.
4. Put every other candidate fact in `deprioritized_candidate_evidence_ids`. Selected and deprioritized IDs must be disjoint and together cover every candidate fact. A fact is not “selected” unless it is cited in authored bundle content; this keeps the artifact validator and the document synchronized.
5. Build `fit_arguments` that cite both sides. A coincidental keyword is not enough; describe the supported relationship.
6. Cite all candidate claims with selected evidence. Do not turn an adjacent fact into direct experience, and do not use a job requirement to upgrade an unsupported language level, degree, certification, or seniority claim.
7. Draft for a one-page résumé. Spend the page budget in this order: required identity/context, relevant experience, all education records, mandatory technical skills, relevant languages/certifications, supported soft skills, then optional personal projects. Compress repeated wording and move secondary details into compact lines before removing baseline context. Personal projects may be omitted when space is insufficient; never omit education or technical skills to make room for them. Never use irrelevant facts as filler.

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
| Education | Keep every unambiguous education record in compact form | Compress wording or details when space is tight, but do not remove an education stage solely because it is not job-specific |
| Certification | Keep compactly when current or meaningful | The posting requires it, the role is regulated, or it is evidence of operational readiness |
| Identity/contact | Always preserve through the candidate contract | Never; do not tailor these away |
| Experience | Keep role/title/employer/date context; select details by relevance | Always, because omission can distort chronology or seniority |
| Technical skills | Always keep a compact supported section | Reorder and group toward the posting; the France profile places it in the left sidebar |
| Soft skills | Always keep a compact section when supported by candidate evidence | The France profile places it in the left sidebar; omit unsupported generic traits |
| Personal projects | Optional; add only after required content fits | Include relevant projects when the rendered PDF still fits one page |

These are retention heuristics, not permission to invent content. When page space is genuinely insufficient, retain the strongest baseline item and record the omitted optional facts as deprioritized; never remove all evidence for a category solely because it did not match a keyword.

## Non-computing and minor jobs

Start from the actual duties. Prefer supported evidence of reliability, customer or stakeholder communication, teamwork, organization, languages, documentation, learning, responsibility, and process discipline when those qualities match the opening. Keep true employer names, titles, and dates. Omit irrelevant projects and technology inventories. Technical work may demonstrate a transferable quality, but do not present technical sophistication as the reason for fit unless the posting values it.

Example: for a warehouse role that stresses accurate order handling and teamwork, a supported history of careful operational processes and collaboration can be selected; an unrelated framework list should be deprioritized. For customer service, supported communication and language facts may lead; backend architecture should not.

When classification is unclear, use a conservative focus, avoid speculative tailoring, and surface the uncertainty in the selection rationale.

For schema-2 profile selections, `decision: review` describes assessment, not rejection. The controller records an explicit preparation choice separately. Preserve all gaps from `fit-report.json`; do not reapply legacy eligibility gates or fabricate evidence to close gaps.
