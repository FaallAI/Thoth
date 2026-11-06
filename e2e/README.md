# End-to-end tests of the dashboard

Browser tests with [e2e](https://github.com/tester-army/e2e). `AGENTS.md` (E2E audits) holds the rules.

| Tests | Needs | Writes |
|---|---|---|
| `tests/studio-*.e2e.ts` | a read-scope token, no model | nothing |
| `tests/story-assist.e2e.ts` | a read-scope token and `ZAI_API_KEY`: its `agent.*` steps call GLM 5.3 | nothing |
| `tests-write/*.e2e.ts` | a write-scope token and a throwaway project, no model | saves and renders in that project |

Plain `npx e2e run` includes `story-assist`, so name the files to stay model-free.

## Setup

From Windows, with the local stack up and a WSL session held open so its ports forward:

```bash
npm ci --ignore-scripts
npx e2e-web install chromium
```

## Read-only tests

```bash
E2E_TELEMETRY_DISABLED=1 \
THOTH_DEV_TOKEN=...        # read scope: thoth-control tokens create --scope read
THOTH_E2E_NARRATED_DRAFT=/studio/<project_id>/<document_id> \
npx e2e run tests/studio-audit-fixes.e2e.ts tests/studio-media.e2e.ts tests/studio-shell-v2.e2e.ts --target w1440
```

`tests/studio-id.e2e.ts` runs on an `*id` target (`w1440id`). `dev*` targets use a vite dev server on port 5199. In Git Bash, also set `MSYS2_ENV_CONV_EXCL="THOTH_E2E_DRAFT;THOTH_E2E_NARRATED_DRAFT"`, or it rewrites those routes into Windows paths. `THOTH_WEB_URL` overrides the default `http://127.0.0.1:8088` on the read config.

## Write tests

`e2e.write.config.ts` reads two files two folders above this one, or from the paths in `THOTH_E2E_WRITE_TOKEN_FILE` and `THOTH_E2E_WRITE_PROJECT_FILE`:

- `e2e-write-token`: `thoth-control tokens create --scope write --days 1`, stored without printing it.
- `e2e-write-project`: the id of a project made only for this.

```bash
E2E_TELEMETRY_DISABLED=1 THOTH_E2E_WRITE_PROJECT=<project_id> \
npx e2e run tests-write/studio-write.e2e.ts --config e2e.write.config.ts --target rw1440 --workers 1
```

The config sets no model, so an agent step cannot run. Its browser guard refuses every write except a preview capability and the throwaway project's own routes, and never lets a narration, Assist, a proposal, a run or an import start. Projects cannot be deleted through the API, so the project and what it holds stay.
