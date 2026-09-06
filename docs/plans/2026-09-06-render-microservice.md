## Goal

Let an agent or script send raw LaTeX sources to an available Dockerized XeLaTeX worker over HTTP and get the PDF back, without requiring Firestore or the emulator stack for local renders.

## Success Criteria

- A caller with a source directory and no Firestore credentials can produce the same PDF (byte-identical for deterministic inputs) as the current queue path.
- The existing Firestore queue path (`enqueue` → lease → heartbeat → artifact) keeps working unchanged, including the Cloud Run flow.
- Error taxonomy is identical on both paths (`COMPILE_ERROR`, `MISSING_DEPENDENCY`, `TIMEOUT`, `INVALID_REQUEST`, retryable flags preserved).
- Concurrent direct requests are bounded: overload fails fast with a retryable signal instead of piling up compiles.
- Warm-direct overhead over raw compile time is negligible (no 5s claim sleep, no 1s poll granularity, no Firestore roundtrips); raise-on-demand adds at most a short `docker start`, never the full compose/emulator stack.

## Context And Current Facts

Yes, this split is feasible, and it is smaller than it sounds: compilation is already containerized — only orchestration is Firestore-coupled.

- `deploy/docker/latex-worker/Dockerfile` + `deploy/compose.yaml` (`latex-worker` service, read-only FS, `cap_drop: ALL`, `no-new-privileges`) already run XeLaTeX in Docker. The proposal changes transport, not the compile engine.
- Today `RenderServiceClient.compile_and_wait` (`job_application_agents/render_service/client.py`) uploads the source dir to an `ArtifactStore`, enqueues a `RenderRequest` in Firestore, and polls `repository.get` every 1s for up to 330s. `Worker.process` (`worker.py`) extracts the artifact to temp dirs, calls `compile_request`, stores the output artifact.
- `server.py` already runs an HTTP server (Cloud Run entry) with `GET /healthz` (xelatex/pdfinfo/pdftotext capability probe) and `POST /process-job`, but `/process-job` still executes a Firestore job — there is no submit-source-directly endpoint yet.
- `compile_request` (`compiler.py`) already takes `(request, source_root, output_root)` on plain paths and already hardens untrusted input with `-no-shell-escape`, per-request deadlines, and `safe_relative_name` checks — all reusable unchanged for a direct endpoint.

## Constraints And Non-goals

- No change to the Firestore queue path, `RenderRequest` model, or Cloud Run flow in this plan.
- No new infrastructure: single `latex-worker` container, no load balancer, no registry, no additional compose services.
- Direct mode targets local/dev first; Cloud Run keeps the queue path (cold-start + IAM story unchanged).
- Non-goal: removing Firestore, multi-worker scheduling, or a public/shared render API.

## Key Decisions

1. **Sync request/response HTTP, not a second queue.** `POST /compile` accepts a zip of sources + JSON spec, returns a zip (PDFs, logs, `result.json`). Rejected async webhook callbacks: unjustified for one local worker; polling is what we are trying to escape.
2. **Keep the Firestore path as the durable option; direct is an additional transport.** Rejected full replacement: the queue path owns idempotency keys, lease/heartbeat, `user_id` tenancy, and the Firestore audit trail — all lost if removed.
3. **Reuse `compile_request` unchanged.** Rejected duplicating compile logic: one engine, two transports. The endpoint builds a `RenderRequest` in-memory and calls the same function on temp dirs.
4. **Bounded admission with fail-fast overload.** One active compile at a time (semaphore, configurable); saturated requests get `429`/`503` with `Retry-After`, mapped client-side to retryable. Rejected unbounded concurrency: XeLaTeX is memory-hungry and the container is sized for one job.
5. **Explicit URL config, no auto-discovery.** Client reads `JAA_RENDER_URL` (compose default `http://latex-worker:8000`), preflights via existing `/healthz`. Rejected Docker-socket probing from the client: needs socket mounts and platform-specific code for zero benefit locally.
6. **Shared-secret header only beyond loopback.** Local compose needs no auth (loopback + private network, same trust as the current shared `/artifacts` volume); if the port is ever published off-host, require `JAA_RENDER_TOKEN`. Rejected full IAM for local: the emulator path has none either.

## Recommended Approach

Extend the existing `server.py` HTTP server with `POST /compile` running inside the current `latex-worker` container (publish its port in `compose.yaml`), add `RenderServiceClient.compile_direct`, and wire a `compile` command through `scripts/render_service.py` with a three-stage fallback chain: warm worker (`/healthz` OK → post immediately) → raise on demand (`docker compose up -d --no-deps latex-worker`, scoped to that one container, never the full stack) → queue path (with `--cloud`/`--live`). Response reuses the `result.json` manifest so the client keeps its request-id verification.

Implementation note (approved execution): instead of a new zip-upload endpoint, the dormant `POST /compile` (JSON spec + pre-staged `input_artifact` ref via the shared compose-mounted artifact root) was hardened with admission control, error-code-preserving status mapping, a body cap, and graceful shutdown, then reused. The queue worker loop still runs — embedded as a thread in `run_server` via a compose `command:` override; Dockerfile entrypoint and live stacks are untouched.

## Work Plan

1. **Server endpoint** (`render_service/server.py` only): `POST /compile` — enforce body size cap, unzip to temp dir, validate spec into `RenderRequest` via existing models, run `compile_request` under the semaphore with `request.timeout_seconds`, zip `output_root` (+`result.json`) as the response. Map `CompileFailure` codes to HTTP status (`INVALID_REQUEST`→400, `MISSING_DEPENDENCY`→422, `TIMEOUT`→504, compile/infra→500/502) while returning the code string in the body so the taxonomy survives.
2. **Client method** (`render_service/client.py` only): `compile_direct(url, source_directory, documents, ...)` — zip sources (reuse `ArtifactStore` layout or plain zip), `POST`, verify `result.json` request-id match exactly like `compile_and_wait`, extract PDFs to `destination`. `429`/`503` surface as retryable.
3. **Wiring**: publish the worker HTTP port + keep the existing healthcheck in `deploy/compose.yaml`; add `JAA_RENDER_URL` to config; add `--direct` to `scripts/render_service.py` implementing warm → raise → queue: probe `/healthz` with a short timeout; if unreachable, run `docker start latex-worker` (single container only, no emulator/`depends_on` chain) and re-probe; only if still unreachable, fall back to the queue path with a one-line notice. No changes to `worker.py`, `repository.py`, or Cloud Run handling.
4. **Tests**: endpoint contract test (bad zip → 400, failing `.tex` → 500 with `COMPILE_ERROR` code); parity test compiling a golden fixture via both paths and diffing PDFs; fallback test (no server → queue path used). Extend `scripts/check_render_service.py` with one direct-mode compile against the compose stack.

## Validation Plan

- `python -m unittest job_application_agents.render_service.test_server -v` plus the new contract/parity tests — expected: all pass, golden PDFs identical across paths.
- Live smoke: `compose up`, `curl POST /compile` with a sample bundle → valid PDF + `result.json`; `curl /healthz` → READY; two concurrent compiles → second gets `429`/`503`, not a second `xelatex` process (highest-risk check: overload behavior).
- Regression: `python3 scripts/check.py` still passes (queue path untouched).
- Manual: stop the worker, run CLI with `--direct` → container is raised on demand (~1–2s) and the compile succeeds without the emulator; remove the container image entirely and rerun → clean fallback to queue path with a one-line notice.

## Risks / Rollback

- Risk: long sync connections idle through proxies/timeouts — mitigated by reusing the existing 300s request timeout and documenting it; Cloud Run path unaffected.
- Risk: zip-slip / zip-bomb via upload — mitigated by reusing `safe_relative_name`, a body size cap, and temp-dir confinement already proven in `worker.py`.
- Risk: behavior drift between two transports — mitigated by the shared `compile_request` and the parity test; any new compile feature lands in the engine, never per-transport.
- Rollback: remove the endpoint, client method, and compose port; queue path never depended on them.

## Open Questions

None blocking. Post-approval runtime question: make `--direct` the default for local dev (recommended: yes, with queue fallback) or opt-in only.
