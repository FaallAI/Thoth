# Running Thoth

Thoth runs as the Python control plane (FastAPI + a Temporal worker), the Remotion renderer
and the React dashboard. The Stage 1 stack runs them in Docker; see
[the Stage 1 runbook](operations/stage1-local-docker.md). The Rust engine and Scout were
retired on 2026-10-31.

## Local development

Run the control plane's four terminals,
ports, environment, safe shutdown sequence, retry limitation, and offline smoke exactly as
documented in [python-control-plane.md](python-control-plane.md).

The short local sequence is:

1. start Temporal development server on `7233` (UI `8233`);
2. from `python/`, start FastAPI on `8000` and `python -m thoth_control_plane.worker`;
3. from `dashboard/`, start Vite on `5173` with `VITE_CONTROL_PLANE_URL` pointing at FastAPI; and
4. stop dashboard, API, worker, then Temporal with `Ctrl+C` in each terminal.

Never print or commit the API keys while configuring these processes. The worker polls the
`thoth-control-plane` Temporal task queue.

### The `thoth-control` client

`thoth-control` is the thin operator client for the Python control plane. Run it from `python/`
after `uv sync --all-groups`:

```powershell
uv run thoth-control workflow start --url https://example.com/source --style news-vertical
uv run thoth-control workflow watch <workflow_id>
uv run thoth-control workflow approve <workflow_id> --approval-id <approval_id> --decision approve
uv run thoth-control workflow cancel <workflow_id>
uv run thoth-control workflow retry <workflow_id> --from-stage source
```

Set `THOTH_CONTROL_PLANE_URL` (default `http://localhost:8000`) and
`THOTH_CONTROL_PLANE_API_KEY` without printing or committing their values. Every command sends the
same typed `/api/v1/workflows` HTTP contract used by the dashboard. It has no Scout/Bun subprocess
route and does not implement alternate orchestration. Durable retry is deliberately unavailable
and returns `503` until checkpoint and artifact-fingerprint validation can prevent duplicate side
effects.

`workflow watch` opens the authorized `/events` Server-Sent Events stream and prints each typed
lifecycle event until the server closes the stream; it is not a one-time status lookup.

### Deploy with reports in PostgreSQL

Workflow reports (source investigation, attribution, assembly, footage) live in
the `workflow_reports` table of the editor PostgreSQL, not in report files. `make deploy` runs, in
this order: `editor migrate` -> stop the old worker -> `thoth-control reports import` (imports the
existing report files once) -> check the import printed `invalid=0` -> `up -d --wait`. If the
import is not clean the script exits with the old worker still stopped; decide, then re-run.

- Back up PostgreSQL and the artifact volume together; media stays on the volume.
- Every workflow depends on the editor PostgreSQL. Without it the worker does not start and the
  API answers `503 report_store_unavailable` for report artifacts.
- Never roll the image back while workflows are in flight: an older image does not read the
  stored reports.
