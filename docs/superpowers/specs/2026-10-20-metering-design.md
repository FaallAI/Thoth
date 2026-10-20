# Metering, cost model and the shared-pool quota (SaaS sub-project 3)

## Why

Thoth is becoming a usage-priced SaaS, built in four sub-projects:

1. Accounts, sign-in and developer access: deployed on 2026-10-19.
2. Workspace isolation: deployed on 2026-10-20
   (`docs/superpowers/specs/2026-10-19-workspace-isolation-design.md`).
3. **Metering and the cost model** (this spec).
4. Billing and payments.

Two problems remain after sub-project 2:

- **The shared pool has no per-workspace limit.** Every workspace's workflows lease the
  operator's source accounts and their DataImpulse proxies. One active workspace can spend the
  daily account budgets (Instagram allows about 20 searches a day), push the operator's accounts
  toward spam flags or bans, and use the proxy balance. The operator required a per-workspace
  quota before public sign-up (2026-10-19).
- **Nothing measures what a workflow or a video costs.** No provider adapter records its calls,
  tokens or characters, and source-account use is counted per account, not per workspace. Plan
  prices for sub-project 4 need this data.

## Outcome

- Each workspace leases at most its daily quota of source-account sessions per platform. Past
  the quota its workflows still run, without signing in, and the run report says why.
- However many workspaces there are, a reserved share of each platform's daily account capacity
  stays for the operator's own workflows.
- Every workflow, rendered video, stored byte, account lease and provider call is recorded
  against its workspace.
- A platform admin sets unit prices and reads the estimated cost per workspace, per workflow and
  per video. Users see their own usage and today's remaining quota, never money.

## Decisions (operator, 2026-10-20)

| Topic | Decision |
|---|---|
| First outcome | Protect the shared pool and collect pricing data |
| A workspace over its quota | Its acquisition runs anonymously, as when no account is available; the run report marks the quota; the workflow does not fail |
| Quota shape | Leases per platform per UTC day per workspace, with platform defaults an admin can override per workspace; `ws_bootstrap` is exempt |
| Operator reserve | Half of the pool's daily capacity per platform stays for `ws_bootstrap`; other workspaces stop leasing at that line. An admin can change the percentage per platform |
| Visibility | Users see their workspace's usage and remaining quota; only platform admins see costs |
| Approach | Usage events at the existing seams, priced by an admin-edited unit price table (approach A). Exact per-provider token accounting is out of scope |

## 1. The shared-pool quota

### 1.1 Quotas

- **Defaults** live in code next to `DEFAULT_DAILY_BUDGETS`, as `DEFAULT_WORKSPACE_DAILY_LEASES`:
  Instagram 3, TikTok 10, X 5, YouTube 10, Threads 5 leases per workspace per UTC day.
- **Overrides:** table `workspace_quotas (workspace_id, platform, daily_leases)`, primary key
  `(workspace_id, platform)`, foreign key to `workspaces`. A row replaces the default for that
  workspace and platform. `daily_leases = 0` turns source accounts off for that workspace.
- **`ws_bootstrap` is exempt.** The operator's workspace is limited only by each account's own
  daily budget.

### 1.2 The check

- Every source-account lease goes through one wrapper around `SourceAccountStore.lease()`. Today
  three callers lease: the acquisition `account_runner`, attribution discovery, and the X footage
  search. All three run inside Temporal activities.
- The wrapper finds the workspace from the workflow's memo: the gateway writes `workspace_id`
  into it when it starts the workflow. The `workflow_runs` row is written only after the start,
  so the first activity can run before it exists. Without a memo (a workflow started before this
  deploy), the wrapper uses `workflow_runs.actor_id`, mapped with `actor_workspace_id()`. With
  neither, the workflow is treated as `ws_bootstrap`, with a `warn` log.
- In one PostgreSQL transaction, the wrapper:
  1. locks the `ws_bootstrap` workspace row (1.4);
  2. counts that day's `account_lease` events for the workspace and platform;
  3. refuses when the count has reached the quota, or when the lease would cut into the
     operator reserve (1.4);
  4. otherwise leases and writes the `account_lease` event.
- Two activities racing at the last unit of quota get exactly one lease.
- **A refusal** behaves like "no account available": the acquisition runs anonymously, and
  `AccountUse` gains `quota_exhausted: bool = False`, set to `true`, so the run report explains
  the thin result. Attribution discovery and footage search skip their signed-in path, as they do
  today when no account is free.

### 1.3 Proxies

A DataImpulse proxy is attached to its source account, so one lease is one proxied session, and
the lease quota also limits proxy use. Bytes through the proxy are not measured: DataImpulse
reports no per-session usage to Thoth. The meter counts proxied sessions, and the unit price is
per session.

### 1.4 The operator reserve

Per-workspace quotas do not bound the total: seven workspaces at three Instagram leases each
spend a 20-lease account before the operator's workflows run. The reserve keeps a share for
`ws_bootstrap`.

- **Capacity** of a platform today = the sum of the daily budgets of its accounts that are
  `healthy`, or in a `cooldown` that ends today. **Used** = their uses today
  (`source_account_usage`). **Remaining** = capacity − used.
- **Reserve** = `ceil(capacity × reserve_percent / 100)`. The default `reserve_percent` is 50.
  Column `operator_reserve_percent` (nullable, 0–100) on `source_account_policies` overrides it
  per platform.
- A lease for any workspace other than `ws_bootstrap` is refused when `remaining − 1 < reserve`,
  exactly like a quota refusal (`quota_exhausted`, anonymous run). `ws_bootstrap` leases are
  never refused by the reserve. They are refused only by each account's own budget, as today.
- A platform whose budget is unlimited (`daily_budget = 0`) has no reserve.
- **Races:** every lease of a workspace other than `ws_bootstrap` first locks the
  `ws_bootstrap` row of `workspaces` (`SELECT … FOR UPDATE`). This serializes the reserve and
  the per-workspace quota checks across all workspaces. Two workspaces racing at the reserve
  line get at most one lease. Leases are rare, so one lock costs nothing measurable.

### 1.5 Administration

- CLI: `thoth-control quotas set <workspace_id> <platform> <n>`, `quotas clear <workspace_id>
  <platform>`, `quotas show <workspace_id>`, and `quotas reserve <platform> <percent>`.
- The existing `PUT /api/v1/source-accounts/policies/{platform}` accepts an optional
  `operator_reserve_percent`, and the policy view shows it.
- API: `GET` and `PUT /api/v1/admin/workspaces/{workspace_id}/quotas`, platform admin and the
  `admin` scope only (the existing `platform_actor` dependency).

## 2. The meter and the cost model

### 2.1 Usage events

Table `usage_events`, append-only:

| Column | Meaning |
|---|---|
| `event_id` | primary key |
| `workspace_id` | foreign key to `workspaces`, not null |
| `workflow_id` | nullable |
| `project_id` | nullable |
| `kind` | one of the kinds below |
| `key` | what was used, e.g. `instagram` or `novita/qwen2.5-vl-72b` |
| `quantity` | numeric |
| `unit` | `session`, `workflow`, `second`, `byte`, `call`, `token_in`, `token_out`, `character` |
| `at` | UTC timestamp |

Index `(workspace_id, at)` and `(workspace_id, kind, key, at)`.

| kind | Written | Rows |
|---|---|---|
| `account_lease` | by the lease wrapper, in the quota transaction (1.2) | 1 `session`, key = platform |
| `workflow_completed` | by the workflow itself as its last step when it succeeds (a local activity), so a run nobody opens is still counted | 1 `workflow` |
| `video_rendered` | when a render job succeeds | output length in `second` |
| `media_stored` | when an editor asset, a render output or a workflow artifact is stored | its size in `byte` |
| `provider_call` | by each provider adapter: vision, captions, figures, footage queries, voice (TTS), the prompt provider | 1 `call`, plus `token_in`/`token_out` or `character` rows when the provider's response reports them |

### 2.2 The meter scope

- Adapters do not take a new parameter. A context variable holds the meter scope:
  `workspace_id`, `workflow_id` and `project_id`.
- It is set:
  - once per Temporal activity, by a wrapper that resolves the workspace from the workflow ID
    (as 1.2 does);
  - per API request, by the authenticated dependency, from the actor, for calls made by Studio
    and the prompt lab.
- `meter.record(kind, key, quantity, unit)` reads the scope.

### 2.3 Unit prices and the estimate

- Table `unit_prices (kind, key, unit, usd_per_unit, updated_at)`, primary key
  `(kind, key, unit)`. A key of `*` prices every key of that kind and unit that has no price of
  its own.
- CLI: `thoth-control prices set <kind> <key> <unit> <usd>` and `prices list`. API:
  `GET`/`PUT /api/v1/admin/prices`, platform admin only.
- **Estimate** = Σ quantity × unit price over a period. Events without a price are reported as
  `unpriced` (with their quantities), never as zero cost.
- Currency is USD, the currency providers bill in.

### 2.4 Who sees what

- **Users:** `GET /api/v1/usage?month=YYYY-MM` returns their workspace's totals: workflows,
  videos, rendered seconds, stored bytes, leases per platform, and today's quota and remaining
  leases per platform. No money. The dashboard gets a "Usage" page.
- **Platform admins:** `GET /api/v1/admin/usage?from=…&to=…` returns per workspace: the totals,
  the estimated cost, and the unpriced items. This is the pricing input for sub-project 4.
  - **No cost is counted twice.** Each priced event falls in exactly one bucket:
    - **workflow:** it carries a `workflow_id` (leases, provider calls and media inside a
      workflow);
    - **video:** a render, meaning `video_rendered` or a render's stored output;
    - **other:** everything else (Studio and prompt-lab calls, editor uploads).
  - The cost per workflow is the workflow bucket ÷ completed workflows; the cost per video is the
    video bucket ÷ rendered videos. A plan can bill one basis or both without double counting.
  - `complete` is false while any event has no unit price. The estimate is then too low.

## 3. Errors, testing and rollout

### 3.1 Errors

| Case | Behaviour |
|---|---|
| The quota or reserve check, or the lease event, cannot be written (database unavailable) | No lease; acquisition runs anonymously; `warn`. The pool stays protected when the meter is down |
| Any other event cannot be written | `warn`; the work continues. The meter loses that event, never the user's work |
| A provider call outside any meter scope (e.g. an operator CLI command) | Recorded against `ws_bootstrap` with `warn` |
| A non-admin calls a quota or price route | 403 `Not authorized` (existing contract) |

### 3.2 Testing

All offline; no live test until the final acceptance.

1. **Quota:**
   - platform defaults and per-workspace overrides;
   - `0` turns source accounts off;
   - `ws_bootstrap` is exempt;
   - `quota_exhausted` reaches the run report;
   - each of the three lease callers goes through the wrapper.
2. **Races on PostgreSQL:**
   - two concurrent leases of one workspace with one unit of quota left produce exactly one
     lease and one `account_lease` event;
   - two workspaces racing one lease above the reserve line produce exactly one lease.
3. **Operator reserve:**
   - at 50% of a 20-lease account, other workspaces stop after 10 leases a day while
     `ws_bootstrap` still leases;
   - capacity counts only healthy accounts and cooldowns ending today;
   - an unlimited budget has no reserve;
   - the per-platform percentage override applies.
4. **Meter:**
   - every event kind is written at its seam with the right workspace, workflow and project;
   - tokens or characters are taken from the provider response when present;
   - every activity that calls a provider sets the meter scope (a test fails when one does not).
5. **Cost:** unpriced items are reported as `unpriced`; the `*` key fallback; averages per
   workflow and per video.
6. **Isolation:** workspace B never sees A's usage; the sub-project 2 structural route test covers
   the new routes, and the admin routes require a platform admin.
7. **Dashboard:** the Usage page shows usage and remaining quota, and no money.
8. **Stack smoke in CI:** after the smoke render, `/api/v1/usage` for its workspace reports at
   least one rendered video.

### 3.3 Rollout

- Editor migration `0015` adds `usage_events`, `workspace_quotas` and `unit_prices`, and the
  nullable column `source_account_policies.operator_reserve_percent`. Nothing is dropped.
- No backfill: the meter counts from the deploy. Old provider calls were never recorded, so a
  partial backfill would distort the cost estimate.
- **Operator gates after the deploy:** set unit prices with `thoth-control prices set`, and check
  the default quotas.
- Public sign-up stays closed until sub-project 4.

## Out of scope

- Exact token accounting for every provider adapter (approach B); it can be added per adapter
  later without a schema change.
- Bytes through the proxy.
- Sale prices, plans, payment, and limits other than the source-account quota (sub-project 4).
- Storage cost over time (GB-months); the meter records bytes when they are stored.
