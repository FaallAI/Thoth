# Workspace isolation (SaaS sub-project 2)

## Why

Thoth is becoming a usage-priced SaaS. The work splits into four sub-projects, built in order:

1. Accounts, sign-in and developer access: done and deployed on 2026-10-19
   (`docs/superpowers/specs/2026-10-19-accounts-and-sign-in-design.md`).
2. **Workspace isolation** (this spec): every user's data is isolated in their workspace.
3. Metering and the cost model.
4. Billing and payments.

Sub-project 1 gave every user a workspace, but data ownership did not change:
`current_actor` still returns the single data actor `owner` for every caller. Every signed-in
person therefore sees, and can change, the one existing dataset. Public sign-up must not open
until this sub-project ships.

## Outcome

- A user sees and changes only the projects, workflows, drafts, assets, renders and media of
  their own workspace. Anything else answers exactly as if it did not exist.
- The existing data stays with the operator, who owns the bootstrap workspace.
- Source accounts and proxies stay a platform resource that only platform admins manage. Every
  workspace's workflows still use them.
- A route added later cannot skip the isolation silently: a structural test fails CI.

## Decisions (operator, 2026-10-19)

| Topic | Decision |
|---|---|
| Workspace model | Personal workspace per user now. Authorization is already membership-based, so team invitations can be added later without migrating data again. No invitation UI in this sub-project |
| Source accounts and proxies | Owned by the platform, managed by platform admins only; every workspace's workflows share the pool |
| Isolation approach | In the application: a workspace-keyed data actor, a project guard, and a structural route test. No Postgres row-level security |

## 1. Ownership model

### 1.1 The data actor is the workspace

`current_actor` returns the actor of the caller's workspace instead of the constant `owner`:

| Workspace | `Actor.actor_id` |
|---|---|
| `ws_bootstrap` | `owner` (the legacy actor, so existing runs, Temporal workflows and workflow IDs keep resolving) |
| any other | its `workspace_id` (`ws_<hex>`) |

- `actor_type` stays `user`, and `display_name` keeps carrying the caller's email for audit.
- The mapping lives in one function, `data_actor_id(workspace_id)`.
- Everything already keyed by the actor becomes workspace-scoped with no further change:
  - workflow IDs are derived from the actor, so the same idempotency key in two workspaces
    starts two workflows;
  - the Temporal gateway refuses a handle whose `owner_actor` differs (`WorkflowNotFound`);
  - `workflow_runs` lists and updates filter by the actor;
  - approval signals carry the actor, and the workflow checks it.

### 1.2 Projects belong to a workspace

- Editor migration `0014` adds `projects.workspace_id TEXT NOT NULL REFERENCES workspaces`, fills
  every existing row with `ws_bootstrap`, and adds an index on `(workspace_id, created_at)`.
- `GET /projects` lists the caller's workspace only; `POST /projects` creates in it.
- **The project guard** is one FastAPI dependency used by every route with `{project_id}` in its
  path. It loads the project and answers **404** when it does not exist or belongs to another
  workspace, with the same body in both cases.
- Every project-scoped table is isolated through its project: editor assets and previews, edit
  documents, render jobs and render capability, Studio imports and decisions, prompt-lab layers,
  proposals and provider preferences, and Studio review events.
- Registering a workflow run under a project (`POST /projects/{project_id}/workflows`) passes the
  guard as well, so a run cannot be attached to another workspace's project.

### 1.3 Platform resources

- A principal is a **platform admin** when it is the service key, or a user principal (session or
  personal token) whose membership in `ws_bootstrap` has the role `owner` or `admin`. A workspace
  token is never a platform admin.
- Every `/source-accounts` and `/source-proxies` route requires a platform admin and the `admin`
  scope. Anyone else gets the existing 403 `Not authorized` contract.
- Workflows of every workspace keep leasing accounts and proxies from the shared pool; nothing in
  the acquisition path changes.

### 1.4 The structural lock

A test walks the FastAPI route table and fails when:

- a route with `{project_id}` in its path does not depend on the project guard;
- a `/source-accounts` or `/source-proxies` route does not depend on the platform-admin check;
- a data route under `/api/v1` depends on neither `current_actor` nor `current_principal`
  (public auth routes and the internal renderer routes are listed as explicit exceptions).

## 2. Users, credentials, media and dashboard

### 2.1 Users and workspaces

- Sub-project 1 already creates a personal workspace (`ws_<hex>`, role `owner`) for every new
  user, and gives the very first user `ws_bootstrap`.
- **The first-user race is closed.** Owning `ws_bootstrap` now means being a platform admin, so
  `ensure_user` locks the `ws_bootstrap` row (`SELECT … FOR UPDATE`) before it counts its members.
  Two first sign-ins racing produce exactly one owner. The `ponytail` note that tolerated the race
  is removed.
- Sign-up stays closed to the configured Google domain and GitHub organization until billing.

### 2.2 Sessions and tokens

- Sessions and personal tokens already carry a `workspace_id`; the service key maps to
  `ws_bootstrap`. The principal's workspace decides the data actor (1.1).
- **Membership is checked on every request.** Resolving a session or personal token also loads the
  user's membership in that workspace. Without one, the credential resolves to no principal, as if
  signed out. The membership's role joins the `Principal` (`role: str | None`) for the
  platform-admin check. Removing a member later cuts their access at once, with no session
  sweep.
- Workspace tokens stay behind `THOTH_AUTH_WORKSPACE_TOKENS=false` until sub-projects 3 and 4.

### 2.3 Media store

- Object keys do not change (`renders/<job>/…`, editor assets, workflow artifacts). The MinIO
  bucket is private and only reachable on the Docker network.
- Media is only served through routes that pass the project guard or the workflow owner check, so
  section 1 isolates it.
- No workspace prefix in object keys. Metering (sub-project 3) can sum storage per workspace from
  the database records.

### 2.4 Dashboard

- `GET /api/v1/me` adds `workspace: {id, name, role}` and `platform_admin: bool`.
- The workspace menu shows the workspace name.
- The Source Accounts navigation entry and route are hidden from anyone who is not a platform
  admin; a direct visit shows the existing not-authorized state.
- A new user's empty workspace shows a "Create your first project" state. No page may assume a
  project exists.

### 2.5 Existing data

Every existing project, run, draft, asset and render stays with `ws_bootstrap`, which the operator
owns. The operator's view does not change.

## 3. Errors, testing and rollout

### 3.1 Errors

| Case | Answer |
|---|---|
| A project or workflow of another workspace | 404, identical to a missing one |
| A platform route called by a non-admin | 403 `Not authorized` (existing contract) |
| A session or token whose membership is gone | No principal: `/auth/me` 401, API 403 (existing contracts) |

### 3.2 Testing

All offline; no live test until the final acceptance.

1. **Structural route test** (1.4).
2. **Cross-workspace behaviour.** Workspaces A and B; for each route family, B cannot read,
   change or start anything of A's, and gets the 404 a missing resource gets:
   - projects (list, get, create);
   - editor assets and preview capability;
   - edit documents;
   - render jobs and render capability;
   - Studio imports;
   - prompt lab and proposals;
   - Studio review;
   - workflows: start, get, artifacts, events, cancel, retry, approve, run lists and `PATCH`.
3. **Further behaviour:**
   - the service key and the `ws_bootstrap` owner still see all existing data;
   - source-account and proxy routes admit platform admins only;
   - a removed membership cuts access on the next request;
   - two racing first sign-ins leave exactly one `ws_bootstrap` owner.
4. **Migration `0014` on PostgreSQL:** existing projects land in `ws_bootstrap`, the column is
   `NOT NULL`, and the foreign key holds.
5. **Dashboard:**
   - Source Accounts is hidden for a non-admin;
   - an empty workspace shows the create-project state;
   - the workspace name appears in the menu.
6. **Stack smoke in CI:** the smoke creates two users with `thoth-control tokens create`, then shows
   through the `web` container on `:8088` that neither user sees the other's project.

### 3.3 Rollout

- Migration `0014` only adds and fills a column; nothing is dropped.
- Temporal is untouched: `ws_bootstrap` keeps the `owner` actor, so running and finished
  workflows resolve as before.
- After the deploy: the operator's existing projects and runs are all visible.
- **Operator gate:** a second real account (another member of the GitHub organization) signs in
  and sees an empty workspace.

## Out of scope

- Team invitations, member management UI, and switching between workspaces.
- Per-workspace source accounts or proxies.
- PostgreSQL row-level security.
- Workspace prefixes in media object keys.
- Metering, quotas and billing (sub-projects 3 and 4).
- Public sign-up.
