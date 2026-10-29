# Agentic end-to-end tests (trial)

Read-only browser tests of the dashboard with [e2e](https://github.com/tester-army/e2e).
Agent steps run on GLM 5.3 through z.ai's Anthropic-compatible Coding Plan endpoint and read
the page as text; GLM 5.3 cannot see images there, so vision stays off. Assertions are
deterministic and need no model. Recorded steps replay from `.e2e/cache/`.

The tests never press Assist's suggest, apply or save, so no provider is called and no draft
changes. A read-scope developer token enforces that on the server too.

## Run

From Windows (the docs ask for WSL; this trial ran on Node 24.13 on Windows), with the local
stack up and a WSL session held open so its ports forward:

```bash
npm ci --ignore-scripts
npx e2e-web install chromium
E2E_TELEMETRY_DISABLED=1 \
ZAI_API_KEY=...            # GLM Coding Plan key, from the root .env
THOTH_DEV_TOKEN=...        # read scope: thoth-control tokens create --scope read
THOTH_E2E_DRAFT=/studio/<project_id>/<document_id> \
npx e2e run
```

In Git Bash, also set `MSYS2_ENV_CONV_EXCL=THOTH_E2E_DRAFT`, or it rewrites the route into a
Windows path. `THOTH_WEB_URL` overrides the default `http://127.0.0.1:8088`.
