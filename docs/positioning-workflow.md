# Evidence-backed CV positioning

New application batches select a profile from a private, reviewed positioning
library before drafting. Selection uses three actual job duties, explicit
requirements and source facts. A generic job title does not determine the CV.

The sequence is extraction → profile selection → writing → humanization →
independent review → rendering. A profile needs direct evidence for two duties,
at least transferable evidence for the third, sufficient seniority, and all
mandatory checks satisfied. Unknown eligibility or unmet mandatory requirements
end the job as `skipped`, with a reason, before document generation. An explicit
`--role-profile` selects a library ID but cannot bypass qualification. There is
no generic fallback or automatic profile proposal.

The selector is a semantic worker, not a keyword classifier. Deterministic checks
validate source hashes, complete assessments, fact references, seniority ceilings
and the resulting decision. Independent bundle review rechecks the substance of
qualifying selections. A valid citation alone does not establish a truthful claim.

## Stage and activate a library

Keep all candidate material outside the repository, under the configured data
root. Use `maintain-master-curriculum` for separate fresh author and reviewer
sessions. The library format and selection contract are defined in
[contracts.md](../skills/select-application-profile/references/contracts.md).

For each profile, stage a focused headline/narrative, anchors, distinct supporting
facts, skill groups, project evidence, seniority ceiling and claim restrictions.
Provide Markdown, editable LaTeX and a PDF baseline preview. A separate review
must accept the exact library and bind all preview hashes. Sources may include
separately staged direct user statements; never infer nationality from language.

Validate without activating:

```bash
python3 scripts/publish_positioning_library.py \
  --library /private/data/staging/positioning-library.json \
  --review /private/data/staging/review.json --data-root /private/data
```

After the user approves those exact reviewed artifacts, repeat with
`--approval APPROVED`. This creates `master-curriculum/profiles/positioning/versions/pNNN`
and atomically updates that branch's `current.json`. The legacy catalog is
untouched. Preserve hashed source files; later source changes invalidate the
library until it is reviewed again. Never hand-edit an immutable version.

Run future batches with `scripts/run_application_batch.py` and omit
`--role-profile` for automatic selection. Missing approval, corrupt files or
stale hashes are configuration errors, not weak-match skips. Do not silently
fall back to an older private driver that forces one source profile.

## Document checks and compatibility

Positioned bundles bind the exact selection and job, use the approved headline,
and cite canonical fact IDs directly. They must visibly substantiate an anchor
and at least two supporting facts. Role-relevant contribution is grounded in
work evidence; personal passion and company affinity must not be invented.
Body length is flexible. Standard small-text commands are raised to 10pt for
positioned renders; the final PDF must contain readable text on one page.
Overflow requires content or template revision, not automatic shrinking.

Schema-2 batches persist their complete stage sequence. Schema-1 batches retain
the legacy sequence with no inserted selection step; callers with custom legacy
stages must supply their original sequence when resuming. Existing applications
and generated CVs are not regenerated. Publication and tests do not submit
applications, write Notion records or contact production services.

Validation: `python3 scripts/check.py`. The synthetic tests cover qualification,
skips, stale evidence, explicit selection, mandatory constraints, seniority,
claim provenance, protected bindings, legacy resume order, publication approval
and PDF readability. Local baseline previews are additionally compiled and
independently reviewed before activation.
