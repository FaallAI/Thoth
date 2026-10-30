# Python workflow control plane operations

The Python control plane is the v1 product boundary for one source-investigation workflow.
It is the dashboard's only backend: no dashboard page and no control-plane route reaches the Rust
server (removed 2026-10-18). The frozen Rust media engine retires at Stage 10.

## Local topology

Run each process from its indicated directory in a separate terminal.

| Process | Local address / queue | Start | Graceful stop |
| --- | --- | --- | --- |
| Temporal development server | gRPC `127.0.0.1:7233`, UI `127.0.0.1:8233` | `temporal server start-dev --ip 127.0.0.1 --port 7233 --ui-port 8233` | `Ctrl+C` in its terminal |
| FastAPI | `127.0.0.1:8000` | From `python/`: `uv run uvicorn thoth_control_plane.api:create_app --factory --host 127.0.0.1 --port 8000` | `Ctrl+C`; Uvicorn drains in-flight HTTP requests |
| Temporal Python worker | `thoth-control-plane` and isolated `thoth-legacy-adapter` task queues | From `python/`: `uv run python -m thoth_control_plane.worker` | `Ctrl+C`; the worker asks Temporal to reschedule unfinished work |
| React dashboard | `127.0.0.1:5173` | From `dashboard/`: `bun run dev --host 127.0.0.1` | `Ctrl+C` |

Use Temporal's development server only for local work. It is separate from the existing Rust
`thoth worker`, whose SQLite queue and lifecycle remain documented in [RUNNING.md](RUNNING.md).
Start Temporal before FastAPI and the Python worker. Stop the dashboard, FastAPI, worker, then
Temporal so the durable service remains available while clients and workers drain.

`thoth_control_plane.api:create_app` is the zero-argument production ASGI factory used by the
Uvicorn command above. It constructs `Settings()` from the environment; tests may still supply
an explicit settings object and gateway to the same factory.

## Configuration without secret disclosure

Set secrets in the process environment or a local secret manager. Do not put values in command
history, documentation, screenshots, diagnostics, `git diff`, or commands such as `env`,
`Get-ChildItem Env:`, `set`, or `echo`. Verify presence with a boolean check, never by printing
the value.

| Variable | Process | Meaning |
| --- | --- | --- |
| `THOTH_CONTROL_PLANE_API_KEY` | FastAPI, CLI | Legacy service key: smokes, CI and deploy scripts. Required. People sign in instead (see "Sign-in and developer access"). |
| `THOTH_CONTROL_PLANE_CORS_ORIGINS` | FastAPI | JSON list of allowed dashboard origins, for example the local Vite origin. Empty by default. |
| `THOTH_CONTROL_PLANE_ARTIFACT_ROOT` | FastAPI, Python worker working directory | Root for safe relative artifact locations. Defaults to `.thoth-artifacts`; API and worker must resolve the same root. |
| `THOTH_EDITOR_DATABASE_URL` | FastAPI, `thoth-control editor migrate` | Secret PostgreSQL URL for immutable Creator Studio revisions. Stage 1 Compose derives it from the isolated editor database password. |
| `THOTH_ACCOUNT_VAULT_KEY` | FastAPI, Python worker | Optional secret Fernet key that seals source-account cookies and proxies in the editor database. Without it (or without `THOTH_EDITOR_DATABASE_URL`) source accounts are off and acquisition runs anonymously. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `THOTH_X_FXEMBED_URL` | Python worker | Base URL of the FxEmbed (FxTwitter) API that X acquisition and X profile listings read. Defaults to the public `https://api.fxtwitter.com`; set it to a self-hosted instance if the public edges prove unreliable. |
| `THOTH_SOURCE_VISION_MODEL` | Python worker | Vision model for source attribution; default `qwen/qwen3-vl-30b-a3b-instruct`. |
| `THOTH_OPENROUTER_API_KEY` | Python worker | Optional secret OpenRouter key for source attribution: cover vision and finalist classification (`THOTH_SOURCE_VISION_MODEL`), and TypeSafe Jev (`typesafe/jev-1.13`) typed decisions through the Decisions API. Without it attribution decides by deterministic credit rules. |
| `THOTH_FFMPEG` | Python worker | ffmpeg executable for attribution frames; default `ffmpeg`, `/usr/bin/ffmpeg` in the image. |
| `THOTH_SOURCE_ATTRIBUTION_ENABLED` | FastAPI | Default `true`. `false` starts `identify_original` workflows without the attribution stage. |
| `THOTH_TEMPORAL_TARGET` | FastAPI, Python worker | Temporal gRPC target; default `localhost:7233`. |
| `THOTH_TEMPORAL_NAMESPACE` | FastAPI, Python worker | Temporal namespace; default `default`. |
| `THOTH_SOURCE_INVESTIGATION_ACTIVITY_MODE` | Python worker / workflow start wiring | Worker-owned implementation choice: `python`, `python_tiktok_with_legacy_fallback` (migration default), or `legacy_scout`. It is never accepted from HTTP. |
| `VITE_CONTROL_PLANE_URL` | Dashboard build/dev server | FastAPI origin, normally `http://127.0.0.1:8000`. |

For Vite development, leave `VITE_CONTROL_PLANE_URL` unset: the dev server proxies `/api/v1` to
the local control plane, avoiding a browser CORS preflight. Set a
direct control-plane URL only when the API allows the exact dashboard origin through
`THOTH_CONTROL_PLANE_CORS_ORIGINS`.

## TikTok acquisition worker

From `python/`, install the optional acquisition runtime and its browser support before starting a
worker that can inspect public TikTok posts:

```powershell
rtk uv sync --extra acquisition
rtk uv run scrapling install
rtk uv run python -m thoth_control_plane.worker
```

The normal test suite deliberately does not run either installation command and does not launch a
browser, contact TikTok/TikWM, or invoke Bun. The opt-in live gate requires an approved public
post URL in `THOTH_LIVE_TIKTOK_URL`; provide it through the environment or a secret manager and
verify only its presence. Do not echo it, provider credentials, or provider URLs into shell
history, logs, diagnostics, screenshots, reports, or verification output.

### Stage 1 compatibility container

GitHub Actions builds the Linux AMD64 compatibility image at
`ghcr.io/faallai/thoth`. A branch or version tag is only a discovery aid; deployment and the
Stage 1 change record must use the immutable digest printed in the successful **Container image**
workflow summary. In PowerShell, pull the selected build without putting runtime secrets in the
command:

```powershell
$ImageDigest = Read-Host "Paste the sha256 digest from the successful workflow summary"
$Image = "ghcr.io/faallai/thoth@$ImageDigest"
docker pull $Image
docker image inspect $Image --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
```

The image defaults to `/opt/thoth/python/.venv/bin/python -m thoth_control_plane.worker`. Run the
FastAPI process from the exact same digest by overriding the command with
`/opt/thoth/python/.venv/bin/uvicorn thoth_control_plane.api.app:create_app --factory --host
0.0.0.0 --port 8000`.

While legacy fallback remains enabled, run a third container from the exact same digest with the
command `/opt/thoth/bin/start-legacy-cdp`. Give the sidecar the private service name `legacy-cdp`,
set `THOTH_CDP=http://legacy-cdp:18800` on the worker, and set
`THOTH_FFMPEG=/usr/bin/ffmpeg` plus `THOTH_FFPROBE=/usr/bin/ffprobe` on the worker. Port `18800` is
an unauthenticated browser-control boundary: it must not have public ingress or a host-port mapping,
and network policy must allow only the worker to reach it.

The sidecar mounts its sensitive persistent profile at `/var/lib/thoth/browser-profile`; never
archive that profile as soak evidence. Provision both that mount and `/var/lib/thoth/artifacts` as
UID/GID `10001:10001`, or use an equivalent `fsGroup: 10001` or init-container ownership step.
Do not run either process as root and do not make the mounts world-writable.

Before allowing a legacy-fallback activity, require
`GET http://legacy-cdp:18800/json/version` to return 2xx and
`GET http://legacy-cdp:18800/json` to contain a page target on `tiktok.com`. Restart an unhealthy
sidecar. Treat an authentication or challenge page during a legacy fallback as a release
blocker; do not attempt bypass behavior.

Both services must receive `THOTH_CONTROL_PLANE_API_KEY`, `THOTH_TEMPORAL_TARGET`,
`THOTH_TEMPORAL_NAMESPACE`, `THOTH_CONTROL_PLANE_ARTIFACT_ROOT`, and the deployment-owned activity
mode at runtime through the approved environment or secret manager. During the soak the activity
mode remains `python_tiktok_with_legacy_fallback`. Never bake these values or
`THOTH_LIVE_TIKTOK_URL` into an image, build argument, workflow, or command history.

Mount persistent storage at `/var/lib/thoth/artifacts` and set
`THOTH_CONTROL_PLANE_ARTIFACT_ROOT=/var/lib/thoth/artifacts` for both API and worker. This runtime
volume contains workflow artifacts; it is distinct from the approved external S3 prefixes used to
archive sensitive observation JSONL and the finished aggregate report.

Publishing the image does not deploy it to AWS, restart a worker, configure Temporal, start the
soak window, or approve the Python-only cutover. The soak begins only after the recorded digest is
deployed and a controlled canary passes.

`THOTH_SOURCE_INVESTIGATION_ACTIVITY_MODE` is a migration control. The API reads it when it starts
a workflow. **Since 2026-10-30 the default and the only approved stage1 value is `python`:** Scout
is retired, so an acquisition that fails is fixed in Python. The two Scout modes below are history
until the legacy activity is removed.

| Mode | Routing behavior |
| --- | --- |
| `python` | Use Python acquisition only; it never invokes the legacy activity. |
| `python_tiktok_with_legacy_fallback` | Former migration default. A TikTok post uses Python first; eligible safe failures may run the legacy activity once. Non-TikTok sources route directly to legacy during this slice. |
| `legacy_scout` | Route all source investigation through the isolated legacy activity. Use this as the rollback mode. |

For an eligible TikTok post, the route order is **Scrapling headless -> TikWM/CDN -> legacy
activity**. A successful headless result materializes media locally and does not call TikWM. A
headless failure never becomes the terminal failure code by itself: the service always continues
to TikWM/CDN afterward, so any actually-observed fallback trigger today is one of
`cdn_rate_limited`, `cdn_unavailable`, or `media_validation_failed` — these are the only codes
`python_tiktok_with_legacy_fallback` can invoke the legacy activity for in practice. The
allowlist that gates the fallback (`LEGACY_FALLBACK_ELIGIBLE_CODES`) also accepts
`headless_timeout`, `headless_blocked`, and `headless_incomplete`; these are attempt-reason codes
— they can appear in an activity's `attempts[]` but never as the terminal failure code for a
TikTok run, so a fallback debugged at the terminal-failure level will never show one of them. The
exact non-fallback safe codes are `invalid_tiktok_url`, `unsupported_platform`,
`artifact_persistence_failed`, `acquisition_dependency_unavailable`, and
`acquisition_runner_failed`; unsafe input and internal/persistence/dependency failures do not
silently fall back.

`unsupported_platform` is deliberately outside the allowlist. It is a pre-provider rejection:
decided before any provider or legacy attempt exists, so its observation is `route="invalid_input"`
with zero attempts and no fallback transition — the shape the `legacy_fallback` route rejects.
Sending a non-TikTok platform to the legacy activity under an explicit migration mode is a
separate routing seam, decided by the activity mode and the platform before the Python activity
runs, never by a failure code returned after it.

The worker limits both the Python acquisition queue and isolated legacy queue to one concurrent
activity. Scrapling fetches have a 45-second deadline, TikWM resolution has a 15-second deadline,
media downloads have a 30-second deadline, and the source and legacy Temporal activities have
five-minute start-to-close deadlines; Python may retry up to three attempts while the legacy
activity has one attempt. Reports are written atomically at
`reports/<workflow-id>/source-report.json`, with media at
`reports/<workflow-id>/media/tiktok-<post-id>.mp4`, all relative to
`THOTH_CONTROL_PLANE_ARTIFACT_ROOT`. Legacy reports remain under
`legacy-scout/<workflow-id>/source-report.json`.

To roll back, set `THOTH_SOURCE_INVESTIGATION_ACTIVITY_MODE` to `legacy_scout` through the
approved deployment environment and restart the Python worker. This preserves the isolated,
single-concurrency legacy queue and process ownership; it does not expose a per-request or HTTP
switch.

## TikTok Stage 1 operational soak

The migration default, `python_tiktok_with_legacy_fallback`, is not changed by this section. It
documents the evidence a future operator must gather and the approval a human must give before
anyone proposes changing that default. Nothing here performs, simulates, or records that change.

1. Deploy with `THOTH_SOURCE_INVESTIGATION_ACTIVITY_MODE=python_tiktok_with_legacy_fallback`.
2. Export only completed workflow summaries plus safe source events through the approved Temporal
   operations channel; never export source/provider URLs or raw logs.
3. Convert each exported run to the strict schema version 1 JSONL observation contract outside
   Git (see "Observation contract" below), and designate at least two of the converted runs as
   controlled parity samples, each from a distinct approved, public, first-party TikTok post. The
   isolated activation parity pair is separate pre-window evidence: it is collected before the
   window opens, it is not an observation, and it never counts toward those two samples. The
   activation parity gate must pass before a window opens; read its current state from the operator
   change record. An activation pair whose reference fails, produces no Scout media, or leaves any
   Scout-side artifact-integrity check false is `evidence_incomparable`, and that failed evidence
   stays in restricted evidence and the change record rather than satisfying the gate.
   Reconcile every workflow in the window to exactly one observation, each with a real source of
   cleanup evidence (see "Cleanup evidence per route").
4. Collect at least 24 hours (1 day) and 12 valid completed runs before evaluating.
5. From `python/`, run:

   ```powershell
   rtk uv run thoth-control operations tiktok-stage1-soak --observations <approved-jsonl> --output-directory <approved-aggregate-directory>
   ```

6. Archive only the aggregate report file, `tiktok-stage1-soak-report.json`, written into
   `<approved-aggregate-directory>`. Investigate every sorted blocker it lists without editing the
   evidence to force a pass. Bind that report in the operator change record to all six evidence
   identities: the deployed acquisition digest, the acquisition implementation commit, the
   evaluator implementation commit, the policy values embedded in the report, the provider
   configuration reference, and the dataset/window identity. Acquisition identity and evaluator
   identity are distinct: the evaluator implementation commit is the commit containing the
   `TikTokSoakPolicy` and `evaluate_tiktok_soak` implementation that produced the report, resolved
   per evaluation with
   `git log -1 --format=%H -- python/src/thoth_control_plane/operations/tiktok_soak.py`. A later
   documentation-only commit does not replace it. At the current checkpoint that resolves to
   `c7b2def746e5f0cc27b71cb747db5d1e846329e4`; treat that as an example, not a fixed value.
   Archived reports keep their original embedded policy and recorded provenance.
7. Require `ready: true` in that report, explicit human approval, and the rollback drill under
   "Verification and smoke scope" below, in that order, before anyone proposes the default-mode
   commit. A passing report is evidence for that decision, never the decision itself, and never a
   substitute for the human approval step. `ready: true` is necessary but not sufficient: the
   controlled fallback exercise, the restart-recovery check, the rollback drill, and the human
   approval all remain required, and approving Python as the default neither removes nor disables
   the TypeScript Scout path, which stays available as the bounded rollback mechanism.

### Observation contract

Each line of the JSONL input is one `TikTokSoakObservation` (schema version 1). Its `route` field
is exactly one of five values:

| Route | Meaning |
| --- | --- |
| `python_native` | Python acquisition succeeded terminally; no legacy fallback was used. |
| `legacy_fallback` | An eligible safe Python failure triggered the temporary legacy activity, which then succeeded. |
| `failed` | A terminal failure with no eligible fallback (for example a persistence, dependency, or runner failure). |
| `invalid_input` | Rejected before any attempt: an invalid TikTok URL or an unsupported platform. |
| `operator_cancelled` | The operator cancelled the run before a terminal outcome. |

An operator does not hand-write this file. It is the output of converting exported, redacted run
summaries into this strict shape; the loader rejects any line that does not match it, including
extra fields.

### Cleanup evidence per route

Every observation's cleanup booleans must come from measured evidence. Absence of evidence is
never a cleanup PASS, and no route may have its cleanup result assumed.

- Routes that reach a terminal activity result — `python_native`, `legacy_fallback`, `failed`,
  and `invalid_input` — carry cleanup evidence from the activity's own `tiktok_cleanup` event.
  This includes `acquisition_dependency_unavailable`: that branch returns zero acquisition
  attempts and exactly one `tiktok_cleanup` event carrying both booleans, keeping those runs
  inside the terminal-failure denominator instead of silently disappearing from it.
- `operator_cancelled` is different. A cancelled Temporal activity cannot be relied on to return
  a terminal result, and the workflow has no way to know what the activity actually cleaned up —
  so the workflow does not synthesize a cleanup event after cancellation, and an operator must
  not invent one either. Cleanup for this route is proven by the **controlled cancellation
  cleanup gate**: a deliberate cancellation run in which the operator, after cancellation
  settles, measures the same two invariants the activity's cleanup event reports — that no
  `.part` file remains under the run's report directory, and that no Scrapling browser session
  is still live — and records those measured values.
  - An `operator_cancelled` observation may only be created from that gate's result.
  - Its `partial_cleanup_passed` and `browser_cleanup_passed` values must be the gate's measured
    values, never a workflow assumption or an operator default.
  - Every workflow that falls inside the soak window must reconcile to exactly one observation.
  - A workflow that is missing from the dataset, or that has no source of cleanup evidence,
    leaves the dataset not yet fit to inform a cutover decision. Reconcile or re-run it; do not
    drop it and do not record it as passing.

### Readiness policy, counts, and rates

`evaluate_tiktok_soak` applies a fixed policy — none of these thresholds is operator-configurable:

| Policy field | Value |
| --- | --- |
| `minimum_window_days` | 1 |
| `minimum_valid_completed_runs` | 12 |
| `minimum_parity_samples` | 0 (Scout is retired, so the soak is Python-only; archived reports keep their own 2) |
| `minimum_python_native_success_rate` | 0.95 |
| `maximum_legacy_fallback_rate` | 0.05 |
| `maximum_terminal_failure_rate` | 0.02 |

The window, run-count, and parity values are the accelerated acceptance policy defined in
`docs/superpowers/specs/2026-09-07-stage1-accelerated-acceptance-design.md`, which supersedes only
those three numbers from the original Stage 1 cutover design. The three rate thresholds, the
zero-tolerance cleanup and audit rules, the schema version, and every human gate are unchanged. At
12 valid completed runs the unchanged rates leave no room for a single legacy fallback (one is
8.33 percent against a 5 percent ceiling) or a single terminal failure.

Each report embeds the policy it was evaluated with, so an archived report keeps its own original
thresholds. Archived evidence is never re-evaluated or reclassified under the accelerated defaults;
an accelerated decision requires a new dataset collected after the accelerated window is approved
and opened.

The aggregate report carries only counts, rates, a window, `ready`, and blockers — never a
per-run identity, URL, or timestamp.

Counts (`valid_completed` is `python_native + legacy_fallback + failed`, the denominator for the
rates below): `valid_completed`, `python_native`, `legacy_fallback`, `failed`, `invalid_input`,
`operator_cancelled`, `parity_samples`.

Rates, each a fraction of `valid_completed`: `python_native`, `legacy_fallback`,
`terminal_failure`.

Blockers are sorted lexicographically by their fixed string value and are the closed set:
`insufficient_window`, `insufficient_valid_completed_runs`, `insufficient_parity_samples`,
`python_native_rate_below_minimum`, `legacy_fallback_rate_above_maximum`,
`terminal_failure_rate_above_maximum`, `artifact_persistence_failure_present`,
`acquisition_dependency_failure_present`, `acquisition_runner_failure_present`,
`redaction_audit_failure_present`, `absolute_path_audit_failure_present`,
`partial_cleanup_failure_present`, `browser_cleanup_failure_present`, `parity_failure_present`. A
report with `ready: true` never carries any blocker.

### Fail-closed CLI behavior

`rtk uv run thoth-control operations tiktok-stage1-soak` fails closed. Any I/O error, encoding
error, blank line, malformed JSON, per-observation validation failure, or dataset-level problem
(for example an empty dataset, a duplicate id, or observations out of chronological order) aborts
the entire run before any report is written. It prints the fixed message
`tiktok stage 1 soak evaluation failed` to stderr and exits with status code `1`. It never writes
a partial report, never prints a diagnostic derived from the offending line, and never names an
observation id, workflow id, or path in that message. On success it prints
`tiktok stage 1 soak report written` and writes the report atomically: a sibling `.part` file is
written, flushed, and `fsync`'d, then renamed onto `tiktok-stage1-soak-report.json`; the `.part`
file is removed on any failure or cancellation, so a reader never observes a truncated report.

### Observation evidence is sensitive

Every field in the strict observation contract is aggregate-safe by construction — no URL, no
caption, no checksum, no absolute path. The exported JSONL as a whole is still sensitive
operational evidence: it carries real observation and workflow identifiers and real occurrence
timestamps that can correlate with actual acquisition activity. Do not commit it, paste it into a
ticket, chat, or code review, or print it to a terminal session that is logged or shared. The
repository's `.gitignore` matches the naming convention `tiktok-stage1-soak-observations*.jsonl`
and the atomic partial-write suffix `tiktok-stage1-soak-report.json.part`; write the finished
report only into an approved directory outside the repository tree, never the working directory
default.

The synthetic, non-live example at
`docs/operations/tiktok-stage1-soak-observation.example.jsonl` is safe to commit: it uses a
placeholder observation id, workflow id, and timestamp, and validates against the real
`TikTokSoakObservation` model. It is a fixture for documentation and tooling checks, never a
soak dataset.

## v1 HTTP contract

Every response carries `X-Thoth-Contract-Version: 1`. All state-changing endpoints require
`Authorization: Bearer …`; workflow creation also requires a non-empty `Idempotency-Key`.

| Method and path | Purpose |
| --- | --- |
| `GET /healthz`, `GET /readyz` | Process liveness and Temporal readiness. |
| `GET /api/v1/style-presets` | Safe user-facing style choices. |
| `POST /api/v1/workflows` | Submit a typed workflow request; repeated actor/key/body returns the same workflow. |
| `GET /api/v1/workflows/{workflow_id}` | Read the authoritative summary. |
| `GET /api/v1/workflows/{workflow_id}/events` | Read the current snapshot and ordered SSE replay. |
| `POST /api/v1/workflows/{workflow_id}/approve` | Record the exact active approval decision. |
| `POST /api/v1/workflows/{workflow_id}/cancel` | Idempotently request cancellation. |
| `POST /api/v1/workflows/{workflow_id}/retry` | Request retry from a validated stage. Currently returns `503` because no durable checkpoint policy is implemented. |
| `GET /api/v1/workflows/{workflow_id}/artifacts/{artifact_id}` | Authorize through workflow ownership and stream one referenced artifact. |
| `GET /api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import` | Read-only: what opening the run in Studio would import, what Studio leaves out, and the drafts already made from it. |
| `POST /api/v1/projects/{project_id}/workflows/{workflow_id}/studio-import` | With `Idempotency-Key`: create (or replay) a Studio draft from the run's Content Set, assigning an unassigned run to the project. Each media item is reused by checksum or probed in place and copied server side into `uploads/<project>/`; an item that fails stays unresolved, and a replay of the key retries it. Stage 5c-1 adds overlay roles (`slide`, `profile_card`, `comment_card`) placed over the main scene once the main is attached (`main_not_attached` until then); a comment card the reaction beat has no room for ends `excluded` with outcome `not_placed`. Detected subtitle regions land on the clip as `blur_regions` with `blur_enabled = false`, switched by the `set_clip_blur` edit operation. Stage 5c-2 adds the style A roles: `post_card` (an overlay from 0 s for its reading time, the profile card moving after it), and `profile_page`, `creator_footage` and `creator_photo`, each a scene after the main (the page and photos held 3 s, letterboxed). A Content Set assembled with them (`style_a`) lists a missing post card or profile page as "Not captured". Refusals: `409 content_set_unavailable`, `409 content_set_invalid`, `409 workflow_in_other_project`, `404`, `503`. |

Opening a workflow in Studio probes each media object where it is stored: ffprobe reads a
five-minute signed MinIO URL, limited to the `http`, `https`, `tcp` and `tls` protocols (a
local store path may open `file` only).
`THOTH_MEDIA_S3_REGION` (default `us-east-1`) is the region the API signs those URLs with; it
must match MinIO's region.

The API also sweeps `uploads/` at startup and then hourly for objects over an hour old that no
`editor_assets` row of any project points at. Such an object is left when a process is killed
between copying an upload or import and registering it. By default the sweep only logs them
(`upload sweep: N unregistered upload(s) found (report only)`). Setting
`THOTH_UPLOAD_SWEEP_DELETE=true` lets it delete them. Every batch is checked against the database
before anything is deleted, so if the database cannot answer, nothing is deleted.

The retryable flag on a failure states whether the failed activity is safe to consider for a
future checkpointed retry. It is not permission to rerun now. Until artifact fingerprint and
side-effect checkpoint validation exist, the Temporal gateway rejects retry rather than risk a
duplicate publish, download, or other side effect.

## Events and reconnect

A fresh SSE response begins with `workflow.snapshot`, followed by durable events whose sequence is
after the requested cursor. Durable v1 kinds are `workflow.queued`, `workflow.started`,
`workflow.completed`, `workflow.failed`, `workflow.cancelled`, `stage.started`, `stage.progress`,
`stage.completed`, `approval.required`, `approval.recorded`, `artifact.created`, and
`diagnostic.recorded`.

Durable event `sequence` values strictly increase. Store the last durable SSE `id` and reconnect
with `Last-Event-ID`; do not manufacture a cursor from list position or raw legacy output. The
snapshot is authoritative current state, while replayed events are the audit trail after the
cursor. Reconnect can repeat a snapshot, so clients must apply events idempotently.

## Sign-in and developer access

Spec: `docs/superpowers/specs/2026-10-19-accounts-and-sign-in-design.md`, SaaS sub-project 1.

### Serving

The stack serves the dashboard from the `web` container (`compose.stage1.web.yml`, image
`THOTH_WEB_IMAGE`) at `http://localhost:8088`.

- **Routing:** Caddy serves the built SPA with a fallback to `index.html`, and forwards `/api/v1`
  and `/auth` to the API.
- **No credential in the container:** Caddy holds no key, and the browser never holds an API key.
- **Container hardening:** it runs as uid 10001, read-only, with every capability dropped. Caddy
  listens only on unprivileged ports: 8088 for the site, 8080 and 8443 for a later domain.
- **A real domain:** set `THOTH_SITE_ADDRESS` to the domain and `THOTH_SITE_ORIGIN` to
  `https://<domain>`, and set `THOTH_WEB_HTTP_BIND=0.0.0.0:80` and
  `THOTH_WEB_HTTPS_BIND=0.0.0.0:443` (they map to container 8080 and 8443). Caddy then obtains
  certificates itself, and the healthcheck accepts either site.

### Who may sign in

| Provider | Accepted when |
| --- | --- |
| Google | The email is verified by Google, ends in `@THOTH_AUTH_GOOGLE_DOMAIN`, and any `hd` claim equals that domain |
| GitHub | The primary email is verified, and the user is an `active` member of `THOTH_AUTH_GITHUB_ORG` |

The rule is checked again on every sign-in.

After the provider, a 6-digit code goes to that verified email.
- **Code limits:** valid 10 minutes, 5 attempts, a resend no sooner than 60 s, and at most 10 codes
  a day.
- **Trusted browser:** once a code succeeds, the browser is trusted for 30 days and later
  sign-ins there skip the code.
- **Sessions:** 12 h, renewed on use, and never longer than 7 days in all.

Every signed-in user still acts as the data actor `owner` and sees the one shared dataset.
Per-user workspaces arrive in SaaS sub-project 2, so keep the domain and the organization limited
to people you trust.

### Settings

| Variable | Process | Meaning |
| --- | --- | --- |
| `THOTH_SITE_ORIGIN` | FastAPI | The site origin; default `http://localhost:8088`. It builds the OAuth redirect URIs, and cookie-authenticated writes must carry it as `Origin`. |
| `THOTH_AUTH_SECRET` | FastAPI | Secret for the code HMACs and the OAuth state cookie. Generate it with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `THOTH_AUTH_GOOGLE_CLIENT_ID` | FastAPI | Google OAuth client of type Web application. |
| `THOTH_AUTH_GOOGLE_CLIENT_SECRET` | FastAPI | Secret for that client. |
| `THOTH_AUTH_GOOGLE_DOMAIN` | FastAPI | The one email domain Google sign-in accepts. |
| `THOTH_AUTH_GITHUB_CLIENT_ID` | FastAPI | GitHub OAuth App client ID. |
| `THOTH_AUTH_GITHUB_CLIENT_SECRET` | FastAPI | Secret for that app. |
| `THOTH_AUTH_GITHUB_ORG` | FastAPI | The organization GitHub sign-in requires. |
| `THOTH_SMTP_HOST` | FastAPI | SMTP server host for sign-in codes. |
| `THOTH_SMTP_PORT` | FastAPI | SMTP server port; default 587 (STARTTLS). 465 means implicit TLS. |
| `THOTH_SMTP_USERNAME` | FastAPI | SMTP user. |
| `THOTH_SMTP_PASSWORD` | FastAPI | SMTP password (secret). |
| `THOTH_SMTP_FROM` | FastAPI | The sender, for example `Thoth <no-reply@example.com>`. |
| `THOTH_AUTH_WORKSPACE_TOKENS` | FastAPI | `true` allows workspace tokens for external developers. Keep it off until multi-tenancy and billing exist. |

Every variable is optional, and an empty value means not configured:
- a provider is offered only when its client ID, secret and rule are set, together with
  `THOTH_AUTH_SECRET`, the editor database and SMTP;
- without SMTP nobody can finish signing in, so sign-in fails closed;
- developer tokens and the service key keep working either way.

### Creating the OAuth apps (operator)

- **Google Cloud console:** under APIs & Services, Credentials, create an OAuth client ID of type
  Web application. Add the authorised redirect URI
  `http://localhost:8088/auth/callback/google`, or `<THOTH_SITE_ORIGIN>/auth/callback/google`.
- **GitHub:** under Settings, Developer settings, OAuth Apps, create a new OAuth App.
  - Set the homepage to `THOTH_SITE_ORIGIN`.
  - Set the callback URL to `<THOTH_SITE_ORIGIN>/auth/callback/github`.
  - Then, in the organization's settings under Third-party access, approve the app. Otherwise the
    membership check cannot see the organization and refuses everyone.

### Cookies and failure codes

| Cookie | Path | Holds |
| --- | --- | --- |
| `thoth_session` | `/` | The session token: HttpOnly, SameSite=Lax, Secure on HTTPS |
| `thoth_device` | `/auth` | The trusted-browser token, for 30 days |
| `thoth_challenge` | `/auth` | The pending email code, for 10 minutes |
| `thoth_oauth` | `/auth` | Authlib's signed state and PKCE verifier, for 10 minutes |

The server stores only hashes of the tokens and an HMAC of each code.

**Failure codes:**
- `/login?error=`: `unverified_email`, `not_allowed`, `provider_error`, `not_configured`,
  `too_many_codes`, `code_not_sent`, `unavailable`.
- Code errors: `wrong_code`, `expired`, `too_many_attempts`, `resend_too_soon`, `daily_limit`.
- Authorization errors: `insufficient_scope`, `cross_site_request`, `user_required`,
  `token_limit`, `workspace_tokens_disabled`.
- `GET /auth/me` answers 401 `signed_out` when nobody is signed in.
- The rest of the API keeps answering 403 `Not authorized` to a request without valid credentials.

### Developer tokens

- **Format:** personal tokens start with `thoth_pat_` and are sent as `Authorization: Bearer`.
- **Scopes:** `read`, `write` (implies read) or `admin` (implies both). A request that changes data
  needs `write`.
- **Lifetime and limits:** 90 days by default, 365 at most, and at most 20 active per user.
- **Visibility:** the text is shown once.
- **Where to manage them:** the dashboard's **Developer tokens** page, or `GET/POST
  /api/v1/me/tokens` and `DELETE /api/v1/me/tokens/{token_id}`, with a session or an `admin`
  token.

The first token, before OAuth is configured, comes from the operator command below. It needs
database access, creates the user when missing (the first user it creates owns the bootstrap workspace), and
prints only the token:

```bash
docker compose --env-file .env.stage1.local -f compose.stage1.local.yml exec -T api \
    thoth-control tokens create --email you@example.com --name laptop --scope admin
```

**The legacy service key.** `THOTH_CONTROL_PLANE_API_KEY` still works as a service token for the
smokes, CI and the deploy scripts. It has no user, so it cannot manage personal tokens, and its
use is recorded in `auth_events` at most once a minute.

### Local development without signing in

The server has no bypass. Put a personal token in your own shell environment and run the dev
server:

```bash
THOTH_DEV_TOKEN=thoth_pat_... bun --cwd=dashboard run dev
```

The Vite proxy adds `Authorization: Bearer $THOTH_DEV_TOKEN` to `/api/v1` and `/auth` requests.
It is not a `VITE_` variable, so it never enters a bundle, and `vite build` refuses to run while
`VITE_CONTROL_PLANE_API_KEY` is set.

To test the real sign-in through Vite instead, set `THOTH_SITE_ORIGIN=http://localhost:5173` on
the API.

### Workspaces

Every user works in their own workspace. The first user the operator command creates owns the
bootstrap workspace, which holds every record made before workspaces existed, and owning it makes
a platform admin. A sign-in never claims it, even on an empty database (audit 2026-10-30): run the
operator command for the operator first. Every other user gets a personal workspace on their first
sign-in.

- Projects belong to a workspace, and every route under `/api/v1/projects/{project_id}` answers
  404 `project_not_found` for another workspace's project, exactly as for a missing one.
- Workflows belong to their workspace's data actor: the bootstrap keeps the legacy `owner`, and
  any other workspace uses its own ID.
- Source accounts and proxies are a platform resource. Only the service key and the owners and
  admins of the bootstrap workspace manage them, with the `admin` scope; every workspace's
  workflows share the pool.
- A session or token stops working as soon as its user is no longer a member of its workspace.

### Metering

Every workspace's usage is recorded in `usage_events`, one row per event: `account_lease` (one
proxied source-account session), `workflow_completed`, `video_rendered` (output seconds),
`media_stored` (bytes), and `provider_call` (calls, plus tokens or characters when the provider
reports them). Activities are metered for the workspace their workflow's memo names; API requests
for the caller's workspace.

- **Quota.** A workspace other than the bootstrap leases at most its daily quota per platform:
  Instagram 3, TikTok 10, X 5, YouTube 10, Threads 5 per UTC day by default.
  `thoth-control quotas set <workspace> <platform> <n>` overrides it; `0` turns source accounts
  off for that workspace.
- **Operator reserve.** Other workspaces stop leasing when a lease would leave less than
  `ceil(capacity × reserve%)` of the platform's daily account capacity. The reserve is 50% by
  default; `thoth-control quotas reserve <platform> <percent>` changes it.
- **Past either limit** the acquisition runs without signing in, and the run report carries
  `quota_exhausted`. The workflow does not fail.
- **Usage.** `GET /api/v1/usage` and the dashboard's Usage page show a workspace its month and
  today's remaining sessions, with no money.
- **Costs.** `/api/v1/admin/usage`, `/api/v1/admin/prices`,
  `/api/v1/admin/workspaces/{id}/quotas` and `thoth-control prices set|list` are for platform
  admins.
  - The estimate splits costs into three buckets, with no cost in two:
    - **workflow:** events inside a workflow;
    - **video:** renders;
    - **other:** Studio and uploads.
  - It reports the cost per workflow and per video from their own buckets.
  - `complete` is false while any usage has no unit price. Set prices with
    `thoth-control prices set <kind> <key|*> <unit> <usd>` after a deploy.

### Billing

Every workspace is on a plan with a monthly allowance of workflows and videos (spec
`docs/superpowers/specs/2026-10-20-billing-design.md`).

- **Plans** live in the database, never in code. Migration `0016` seeds only `free` (Rp0, 3
  workflows, 1 video, 30 days).
  - Edit them with `thoth-control plans set <id> --name … --price-idr … --workflows …
    --videos …`, `plans list`, or `/api/v1/admin/plans`.
  - A changed allowance applies at once; a changed price applies from the next invoice.
- **Subscriptions:** a workspace without one is on `free`. A paid plan that is not renewed falls
  back to `free` at its period end. `thoth-control subscriptions set <workspace> <plan> <days>`
  grants a plan without payment. `ws_bootstrap` is never limited.
- **Allowance:** each workflow start and each render takes one unit from the `allowance_uses`
  ledger, under a row lock on the subscription. A failed workflow start, or a failed or
  cancelled render, gives its unit back. Past the allowance the answer is 402:
  `{"detail": {"code": "plan_limit_reached", "kind", "used", "allowance", "period_end"}}`.
- **Payment:** `POST /api/v1/billing/checkout` opens a Xendit invoice (QRIS, bank transfer,
  e-wallet, card). Xendit then calls `POST /billing/webhooks/xendit`, checked against
  `THOTH_XENDIT_CALLBACK_TOKEN`, which extends or starts the plan once.
- **Margin:** `/api/v1/admin/plans/margin` compares each plan's price with metered cost,
  converted at the admin rate (`thoth-control plans rate <idr_per_usd>`).
- **Public sign-up:** `THOTH_AUTH_PUBLIC_SIGNUP=true` admits verified users outside the Google
  domain or GitHub organization.
- **Go-live steps, deferred by the operator until every feature is finished:**
  - a public HTTPS address (Xendit cannot reach `localhost`);
  - the Xendit keys, plus the webhook URL registered in the Xendit dashboard;
  - the paid plans, the exchange rate and the meter unit prices;
  - the sign-up flag.

## Authorization and approvals

Every principal (a session, a developer token or the service key) maps to the audited data
`Actor` of its workspace (see "Workspaces"). Authorization is
checked again at the application/gateway boundary for summary, events, controls, and artifact
download. A missing, wrong, or non-Bearer credential receives `403`; an invisible workflow or
artifact receives the same safe not-found boundary as an absent one.

Approval requires the workflow to be waiting for the exact active `approval_id`, an allowed
`approve` or `reject` decision, and the authenticated workflow owner. Agent SDK pause/resume data
is never authorization. Approval is persisted and signalled through Temporal; restarting FastAPI
or the worker while waiting does not create a second decision or activity execution.

## Redaction and artifact policy

Workflow history and events contain only small typed identifiers, safe source display URLs,
stage state, stable error codes/messages, safe metrics, and `ArtifactRef` metadata. They must not
contain bearer tokens, API keys, cookies, signed URLs, absolute paths, raw provider/model payloads,
browser traces, media bytes, or unredacted stdout/stderr. Query strings and fragments are removed
from stored display URLs. Legacy diagnostic text is redacted before persistence and never drives
workflow state.

Artifact locations are validated relative durable paths. The API resolves them beneath
`THOTH_CONTROL_PLANE_ARTIFACT_ROOT` only after actor/workflow/artifact authorization; it never
returns the storage path or a signed source URL.

## Temporary Legacy Scout activity

`LegacyScoutActivity` is a worker-only compatibility seam. FastAPI routes and requests cannot
select it. When `THOTH_SOURCE_INVESTIGATION_ACTIVITY_MODE=legacy_scout`, the Temporal gateway
records the fixed worker configuration and the workflow dispatches only to
`thoth-legacy-adapter`.

That queue has maximum activity concurrency one to match the single-browser limit. The adapter
launches the registered `bun scout/cli.ts run <canonical-source-url> --out <configured-report>`
command from the repository root, without a shell. It creates the configured report directory
first and returns an artifact only after the report exists below
`THOTH_CONTROL_PLANE_ARTIFACT_ROOT`; otherwise it returns a typed safe failure. It heartbeats
while waiting, owns its process group/tree, gives that tree a bounded graceful-stop interval, then
escalates the full group/tree and reaps the original process. Typed events and safe artifact/error
results cross the activity boundary; stdout and stderr do not.

### Exact retirement gate

Do not remove the adapter until the Python source activity:

1. passes the same offline candidate fixture;
2. completes a controlled live smoke with equivalent safe artifacts and stable failure codes;
3. demonstrates equivalent cancellation and no orphaned browser/process tree;
4. survives API and worker restart with the same retry/rate-limit behavior and performance budget;
5. preserves safe artifact, error, event, and redaction semantics; and
6. repository search plus production smoke prove there is no import, reference, or execution of
   `scout/cli.ts` or Bun on the production source-investigation path.

Only after all six proofs are recorded may the isolated adapter queue and its worker wiring be
removed. A later migration plan must name one bounded replacement activity and its parity fixture;
it must not begin a broad Scout TypeScript or Rust media rewrite.

## Verification and smoke scope

The deterministic offline smoke uses Temporal's time-skipping test server and the real FastAPI,
gateway, workflow, worker, SSE, authorization, approval, cancellation, failure eligibility, and
artifact route seams:

```powershell
cd python
uv run pytest tests/integration/test_control_plane_smoke.py -q
```

This is not a controlled live provider/Scout smoke. A live run additionally requires operator
credentials, network/provider availability, and explicit selection of an approved fixture; never
paste those credentials into the test command or report.

### Required rollback drill

Run this drill before approving a cutover away from the migration default, and keep it as the
standing emergency procedure afterward. It does not run automatically and a passing soak report
does not substitute for it.

1. Set `THOTH_SOURCE_INVESTIGATION_ACTIVITY_MODE=python_tiktok_with_legacy_fallback` for ordinary
   recovery, or `legacy_scout` for full acquisition rollback, through the approved deployment
   environment.
2. Restart the Python worker; in-flight workflows retain their durable input mode from when they
   started.
3. Confirm newly gateway-started workflows carry the selected mode.
4. Run one approved public TikTok post and verify exact Python/legacy activity counts against the
   selected mode's expected routing.
5. Audit logs and source events for zero source URLs, signed URLs, provider payloads, exception
   text, and absolute paths.

Do not include real workflow IDs, URLs, environment values, report paths, screenshots, or live
output when recording that this drill was run.
