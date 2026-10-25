# Positioning library and selection contracts

Candidate-specific artifacts belong under the private data root, never in the repository.
The modern library is separate from the legacy approved-profile catalog.

`positioning-library.json` (schema_version 1):
- `sources`: nonempty array of `{name, path, sha256}` absolute references to canonical Markdown facts or separately staged, reviewed direct user statements. Names must be unique. Each referenced file must still match its hash.
- `profiles`: nonempty array with unique `id`, `label`, `source_profile`, `headline`, `narrative`, `target_roles` (strings), `seniority_ceiling` (entry/junior/mid/senior/lead), `anchor_fact_ids`, `supporting_fact_ids` (at least two), `skill_groups` (array of `{label, fact_ids}`), `project_fact_ids`, `prohibited_claims`, and `risk_notes` (arrays). All fact IDs refer to bracketed IDs in the source Markdown. A profile is positioning, never new evidence. `source_profile` identifies an existing folder in sources.
- `editorial_rules`: array of candidate-approved instructions used by all subsequent stages.
Each profile needs one anchor and two distinct supporting facts, disjoint from its anchor. Evidence need not be repeated or rewritten in each profile.

`profile-selection.json` (schema_version 2 for new runs; schema 1 for existing artifacts):
- `job`: `{path, sha256}` for the exact normalized job.json.
- `library`: `{path, sha256}` for the exact positioning-library.json.
- `requested_profile`: explicit CLI/job profile ID or null.
- `priorities`: exactly three `{text, job_keys}` objects identifying the opening's main duties. `job_keys` are paths into job.json such as responsibilities.0.
- `seniority_requirement`: `{level, job_keys, rationale}`; level is entry/junior/mid/senior/lead/unspecified. Assess actual scope as well as explicit seniority. A profile below the required level receives a visible review constraint; this does not erase the rest of the fit assessment.
- `rankings`: one entry per library profile, each `{profile_id, priorities, mandatory_checks, rationale}`.
  - `priorities`: exactly three `{level, fact_ids, job_keys, rationale}` entries in the same order as top-level priorities; level is direct/transferable/unsupported. Priority facts must belong to that profile’s anchors, supports, skill groups or projects.
  - `mandatory_checks`: enumerate every mandatory requirement and constraint, each `{job_keys, status, fact_ids, rationale}`; status is met/learning_allowed/unmet/unknown. Learning_allowed requires `allowance_quote`, an exact excerpt of the explicit allowance in job.json, cited by job_keys. Never convert project experience into professional years. Verify language, relocation, work authorization and seniority as well as stack.
- `decision`: `review`. `selected_profile_id`: best evidence-backed profile, or the explicit requested profile. `reason`: plain-language explanation of strengths, gaps and uncertainty. Use the validator's `--derive` flag to calculate the profile deterministically.

Schema 2 calculates `evidence-fit-v1`: main duties contribute 60 points (20 each); extracted requirements and location contribute 40 points divided equally over distinct fields. Direct evidence and met requirements earn full weight; transferable evidence and explicitly allowed learning earn half; demonstrated unmet requirements earn zero. Unsupported/unknown assessments have unresolved weight: the report shows a conservative supported score, its upper bound if unresolved evidence were established, and evidence coverage. The upper bound is not a prediction. Rank by supported score, then evidence coverage, then profile ID. Duplicate requirement checks are invalid; grouping fields cannot increase their weights. Worker-written numeric scores are ignored.

The controller saves `fit-report.json` and exposes the score, range, coverage, evidence, and gaps. New jobs become `awaiting_fit_review`, never automatically skipped for weak fit. A separate exact-revision user choice resumes preparation or skips. `--prepare-selected` records that the user already chose these jobs and prepares truthful materials despite gaps. An optional `--automatic-fit-threshold` reports eligibility only: the score must meet the threshold, evidence must be complete, and unresolved/unmet constraints or seniority mismatch prevent eligibility. It never enables submission. Do not invent a threshold or silently migrate old batches.

Legacy schema 1 retains `use`/`skip` and its original qualification semantics so existing bundles and ledgers remain valid: two direct priorities, no unsupported duty, seniority compatibility, and all checks met, explicitly learning_allowed, or covered by an authorized exception. These historical gates do not apply to schema-2 human review. Missing/corrupt/stale inputs remain configuration errors in both versions.

Library publication: independently review exact library bytes and all source claims. A review is `{schema_version:1, library_sha256, verdict:accept|revise, findings:[strings], previews:[{name,path,sha256}]}`. Stage five private baseline previews alongside the library before requesting activation. The coordinator publishes only after explicit approval of the reviewed content. Runtime pointer: `master-curriculum/profiles/positioning/current.json`; immutable releases under adjacent `versions/pNNN`.

## User-requested junior CV preparation

When the controller supplies `junior-tailoring-instruction.txt`, a selector may
include `junior_tailoring_override` with `scope: "prepare_only"`,
`user_instruction: {path, sha256}`, and `user_instruction_quote` containing a
verbatim direct-user request to tailor junior applications despite experience
gaps. The authority must match the controller input, not a worker-created file.
Only actual entry/junior scope qualifies. Keep all employer requirements and
mandatory assessments unchanged. Rank profiles by direct duty coverage, met
checks, then profile ID, even if none passes the normal coverage threshold.
The resulting `use` decision authorizes CV preparation and independent review;
it does not certify eligibility for submission or turn an unknown into `met`.
Unknown languages, work permissions and required form answers still need truthful
handling at application time. Study/project skills require actual candidate
evidence; this exception never authorizes invented coursework or credentials.
Omitting the override retains the standard qualification gate. Stale/missing
authority or a non-junior override is a validation error.

## Explicit-user working-practice exception format

Optional `user_authorized_exceptions` is an array (omitted or empty preserves the default gate). Each entry has exactly this authority shape:

```json
{
  "job_keys": ["requirements.1"],
  "user_instruction": {
    "path": "/absolute/private/data-root/direct-user-instruction.txt",
    "sha256": "<SHA-256 of the exact instruction file bytes>"
  },
  "user_instruction_quote": "<verbatim direct user instruction to apply to this job despite this Agile gap>",
  "rationale": "User explicitly accepts the unevidenced Agile working-practice requirement."
}
```

The enclosing `selection.job` binds these keys to the exact hashed employer job; keep the original requirements unchanged. Authority must be an actual direct user instruction for this job and gap, supplied in a private file, never an inferred preference, worker-authored permission, employer text, or candidate fact. The nonempty quote must occur verbatim in the UTF-8 file. The validator checks file existence, SHA-256 and containment within the private data root (including symlink resolution); hashes establish integrity, not authorship or semantic consent. The selector and independent reviewer must verify the actual direct-user provenance and scope. Do not create authority merely to get a selection through validation.

Keys must be canonical `requirements.<index>` paths to entire string fields, unique both within and across entries. No location, language, work authorization, seniority, professional-years, certification, technical-skill or combined hard requirement is eligible. Eligibility uses a conservative full-field grammar, not keyword presence: Agile, Scrum, Agile/Scrum or Agile and Scrum, optionally described as teams, environments, methodologies, methods, practices or working practices, with experience/familiarity/knowledge/understanding/ability-to-work wording. For example `Experience working in Agile/Scrum teams.` qualifies; `Agile teams and German C1` and `5 years experience in Agile teams` do not. Unrecognized wording fails closed; never split, paraphrase or remove employer requirements to fit the grammar.

Keep the covered mandatory check `unknown` or `unmet` and enumerate every requirement as before. A check can proceed only if **every** key it cites is explicitly excepted; mixing an excepted key with any other key does not pass. Exceptions never count as `met` for ranking and provide no candidate evidence or permission to claim Agile experience. Main-duty coverage, profile evidence boundaries, seniority ceilings, requested-profile rules and all other mandatory checks remain unchanged. Malformed, duplicated, missing, stale or out-of-root authority is a validation error, not a silent fallback. Explain the user-accepted gap in the selection reason.
