# Additions review contract

Write one review after drafting the complete staged source directory. Use absolute paths and the exact top-level shape in `additions-review-template.json`.

Each `inputs` item contains exactly `id`, `kind`, `path`, `sha256`, `snapshot_path`, and `snapshot_sha256`. Use a unique `I###`; set `kind` to `document` or `user_statement`; and preserve an original plus a UTF-8 reviewed snapshot.

Each `changes` item contains exactly:

- `action`: `add`, `modify`, or `remove`
- `fact_id`: stable master fact ID
- `before` and `after`: exact claim text without the bullet ID; use null on the absent side
- `evidence`: non-empty `{source_id, quote}` citations. Use an input ID or current fact ID, quote verbatim, and include at least one input citation per change.
- `verdict`: `accept`, `revise`, or `reject`
- `rationale`: concise semantic review
- `issues`: zero or more concise strings

Cover every actual fact-level difference exactly once and omit unchanged facts. Set the overall verdict to `reject` if any change is rejected, otherwise `revise` if any change needs revision, otherwise `accept`. An accepted review has no unresolved questions.

Review truthfulness and precision, not formatting alone. Reject or revise invented metrics, unsupported technologies or proficiency, implied seniority, exaggerated ownership, conflicting dates, duplicate claims, unsupported personal attribution, and removals that were not explicitly requested.

Stage only durable facts that could safely support an application document. Do not turn subjective impressions, speculation, or explicitly unmeasured outcomes such as “felt faster” into canonical facts, even when quoted accurately. Preserve the objective supported addition and disclose the omitted weak outcome in that change's rationale or issues. Treat it as blocking only when the requested update depends on claiming that outcome.
