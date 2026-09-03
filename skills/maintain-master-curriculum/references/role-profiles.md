# Role profile contract

Keep professional positioning separate from canonical facts. A profile is an
approved strategy backed by stable `MC-*` facts; it is never a new candidate
fact.

Each object in `profiles` contains exactly:

- `id`: stable lower-case slug.
- `label`: human-facing profile name.
- `narrative`: concise positioning boundary, not résumé prose.
- `target_roles`: non-empty role/title patterns this profile may address.
- `canonical_headline`: headline without unsupported seniority. It may be
  translated, but not broadened, during tailoring.
- `seniority_ceiling`: `entry`, `junior`, `mid`, `senior`, or `lead`.
- `anchor_fact_ids`: at least one direct professional, project, or education
  fact that establishes the profile.
- `supporting_fact_ids`: at least two distinct supporting facts.
- `technology_fact_ids`: demonstrated technology facts; exposure-only facts
  remain eligible only when their limitation is preserved.
- `allowed_positioning_fact_ids`: the complete set allowed to support the
  profile headline, summary, fit arguments, and core bullets. It must include
  every anchor, supporting, and technology fact.
- `prohibited_claims`: explicit boundaries such as unsupported titles,
  deployment ownership, or model lifecycle claims.
- `risk_notes`: credibility or transition risks the tailoring reviewer must
  consider.

Use an open hybrid catalog. Discover profiles from the evidence and also assess
profiles explicitly requested by the user. Do not hardcode a catalog or publish
a requested profile that fails the same evidence requirements.

Bind the catalog to the exact canonical source manifest. Any source-manifest
change makes the catalog stale and requires rediscovery/review before new
applications can use it.
