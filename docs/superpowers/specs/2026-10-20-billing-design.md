# Billing: plans, payment and limits (SaaS sub-project 4)

## Why

Thoth is becoming a usage-priced SaaS, built in four sub-projects:

1. Accounts, sign-in and developer access: deployed on 2026-10-19.
2. Workspace isolation: deployed on 2026-10-20.
3. Metering, the cost model and the shared-pool quota: deployed on 2026-10-20
   (`docs/superpowers/specs/2026-10-20-metering-design.md`).
4. **Billing** (this spec).

After sub-project 3 every workspace's usage is measured, but nothing limits how much a workspace
may run or charges for it. Public sign-up must not open before this sub-project ships.

## Outcome

- Every workspace is on a plan with a monthly allowance of workflows and videos. Past the
  allowance, new workflows and renders are refused; running work finishes.
- New workspaces start on a small free plan.
- A workspace owner or admin buys or renews a paid plan with any Indonesian payment method
  through a Xendit invoice. A paid webhook extends the plan.
- The operator sets and changes plans, prices and allowances at any time without a deploy, and
  can compare each plan's price with its metered cost.
- Public sign-up exists behind a flag that is off by default.

## Decisions (operator, 2026-10-20)

| Topic | Decision |
|---|---|
| Market | Indonesia first: rupiah (IDR) |
| Billing model | Monthly subscription with an allowance of workflows and videos per period |
| Payment gateway | Xendit, through its Invoice API (one payment link with QRIS, bank virtual accounts, e-wallets, cards). Each renewal is a new invoice; there is no automatic debit |
| Allowance exhausted | New workflows and renders are refused; running work finishes |
| New users | Start on a small free plan |
| Public sign-up | Built in this sub-project behind `THOTH_AUTH_PUBLIC_SIGNUP` (default `false`); the operator turns it on later |
| Approach | Plan catalog in the database, editable by the admin; subscription and invoice tables; Xendit Invoice per period; allowance checked where work starts (approach A) |
| Plan values | Never in code. Only the free plan is seeded, and it is editable. Plan prices are judged against metered cost |

The operator deferred, until every feature is finished:
- setting meter unit prices;
- the Xendit keys;
- creating paid plans;
- turning public sign-up on;
- the live checks.

## 1. Plans, subscriptions and allowances

### 1.1 Plans

Table `plans`:

| Column | Meaning |
|---|---|
| `plan_id` | primary key, e.g. `free`, `starter`, `pro` (lowercase letters, digits, `-`, up to 32) |
| `name` | display name |
| `price_idr` | integer rupiah per period, `>= 0` |
| `workflows_per_period` | integer `>= 0` |
| `videos_per_period` | integer `>= 0` |
| `period_days` | integer, 1–366, default 30 |
| `active` | a plan that is not active cannot be bought; current subscribers keep it until their period ends |
| `updated_at` | |

- Migration `0016` seeds one row: `free`, `Free`, Rp0, 3 workflows, 1 video, 30 days, active. Every
  other plan is created by the operator.
- The operator edits plans with `thoth-control plans set <plan_id> --name … --price-idr …
  --workflows … --videos … --period-days … --active/--inactive` and `plans list`, or with
  `GET` and `PUT /api/v1/admin/plans` (platform admin and the `admin` scope).
- A changed allowance applies at once, including to current periods. A changed price applies to
  the next invoice; an issued invoice keeps its amount.
- The `free` plan cannot be deactivated or deleted; it is the fallback (1.2).

### 1.2 Subscriptions

Table `subscriptions`, one row per workspace: `workspace_id` (primary key, foreign key to
`workspaces`), `plan_id` (foreign key to `plans`), `period_start`, `period_end`, `updated_at`.

- **A workspace without a row is on `free`.** Its row is created on first use with
  `period_start` = now and `period_end` = now + the free plan's `period_days`.
- **Whenever a subscription is read and `now >= period_end`**, it rolls forward in place:
  - a `free` subscription starts a new period of its `period_days`;
  - a paid subscription that was not renewed falls back to `free` with a new period starting
    now.
  - There is no past-due state and no debt.
- `ws_bootstrap` is exempt: it has no allowance and is never billed.
- The operator can grant a plan without payment:
  `thoth-control subscriptions set <workspace_id> <plan_id> <days>` starts a period of that many
  days now.

### 1.3 Allowance use

A workflow start calls Temporal and a render calls the renderer, so a database lock cannot be
held across the start itself. Each unit is therefore recorded in a small ledger when it is
admitted.

Table `allowance_uses`:
- `use_id`;
- `workspace_id` and `kind` (`workflow` or `video`);
- `ref`: a hash of the actor and the idempotency key for a workflow, or the render job ID for a
  video;
- `created_at` and `released_at`.
- `(workspace_id, kind, ref)` is unique.

**Used** = the rows of the kind in the current period (`created_at >= period_start`) that are not
released.

- A workflow start that fails, or a render that fails or is cancelled, releases its unit.
- An idempotent retry of the same workflow start finds its own row and is admitted without
  consuming a second unit.

### 1.4 Where the allowance is checked

- **Workflows:** in the workflow-run service, before the start. This covers both
  `POST /api/v1/workflows` and `POST /api/v1/projects/{project_id}/workflows`.
- **Renders:** in the render service, before a render job is reserved. This covers create and
  retry.
- The check and the ledger insert run in one transaction that first takes
  `SELECT … FOR NO KEY UPDATE` on the workspace's `subscriptions` row. Two starts racing at the
  last unit therefore admit exactly one.
- Exhausted: **402** with
  `{"detail": {"code": "plan_limit_reached", "kind": "workflow"|"video", "used": n,
  "allowance": n, "period_end": …}}`.

### 1.5 Pricing against metered cost

`GET /api/v1/admin/plans/margin?from=…&to=…` (platform admin) returns, per active plan:
- its price per period;
- the average metered cost per completed workflow and per rendered video over the range (the
  sub-project 3 buckets, across all workspaces);
- the cost of a fully used allowance (workflows × cost per workflow + videos × cost per video);
- the margin (price − that cost);
- `complete`, false while any metered usage in the range has no unit price.

Unit prices apply when the report is computed, so prices set later cover usage metered since
2026-10-20.

## 2. Payment through Xendit

### 2.1 Checkout

`POST /api/v1/billing/checkout {plan_id}`, allowed to a workspace's `owner` or `admin` member
(the role sub-project 2 keeps on the principal) and to platform admins:

1. Refuse an unknown or inactive plan (404 `unknown_plan`). `ws_bootstrap` gets 409
   `operator_workspace`.
2. A plan priced Rp0 changes the subscription at once (rules of 2.2), with no invoice.
3. Otherwise, write an `invoices` row with `status` `pending`. Then create a Xendit Invoice:
   - `external_id` = the `invoice_id`;
   - `amount` = the plan's current `price_idr`;
   - `payer_email` = the caller's email;
   - `description` = the plan name;
   - `invoice_duration` = 86400 seconds;
   - `success_redirect_url` and `failure_redirect_url` = the dashboard Billing page on
     `THOTH_SITE_ORIGIN`.
4. Store Xendit's invoice ID and `invoice_url`, then answer `{invoice_id, invoice_url}`. The
   dashboard redirects there.

Table `invoices`:
- `invoice_id` (primary key, `inv_<hex>`);
- `workspace_id`, `plan_id` and `amount_idr`;
- `status` (`pending`, `paid`, `expired` or `failed`);
- `provider_invoice_id` and `invoice_url`;
- `created_at` and `paid_at`.

### 2.2 The webhook

`POST /billing/webhooks/xendit` is public, outside `/api/v1`, and has no session:

- The `x-callback-token` header must equal `THOTH_XENDIT_CALLBACK_TOKEN` (constant-time compare).
  Otherwise the answer is 401 and nothing changes.
- The body's `external_id` names the invoice. An unknown invoice answers 200 and is ignored with
  a `warn`, so Xendit stops retrying.
- **`PAID` or `SETTLED`:** in one transaction, and only from `pending`:
  1. The invoice becomes `paid` with `paid_at`.
  2. The subscription is updated:
     - **same plan and still in its period:** `period_end` += the plan's `period_days`;
     - **otherwise:** a new period of the purchased plan starts now, with no proration.
  - A paid amount different from `amount_idr` is not applied, and is logged with a `warn`.
- **`EXPIRED`:** the invoice becomes `expired` (only from `pending`).
- Repeated webhooks are idempotent: only the transition out of `pending` acts.

### 2.3 Configuration and degradation

- `THOTH_XENDIT_SECRET_KEY` and `THOTH_XENDIT_CALLBACK_TOKEN` live in `.env.stage1.local`. They
  are never logged or returned.
- Without them:
  - checkout answers 503 `billing_unavailable` and the webhook answers 503;
  - allowances still apply.
- Xendit unreachable or refusing at checkout: 502 `payment_provider_unavailable`. The invoice is
  marked `failed`, and the subscription does not change.

### 2.4 What a workspace sees

`GET /api/v1/billing` (any member) returns:
- the plan and its period;
- workflows and videos used and allowed;
- the active plans with their prices;
- the workspace's invoices (status, amount, and the payment link while pending).

`ws_bootstrap` shows `unlimited: true`.

## 3. Dashboard, sign-up, errors, testing and rollout

### 3.1 Dashboard

- **A "Billing" page:**
  - the current plan and period;
  - this period's remaining workflows and videos;
  - the active plans with their prices and a "Choose" button (checkout, then a redirect to
    Xendit);
  - the invoice history.
  - The operator's workspace shows "Unlimited (operator)".
- **At the limit:** the workflow start form and the render action turn a 402 into "This month's
  allowance is used up", with a link to Billing.

### 3.2 Public sign-up

- `THOTH_AUTH_PUBLIC_SIGNUP` (default `false`).
- When `true`, a new user is admitted without the Google-domain or GitHub-organization
  restriction. The provider still verifies the email, and the emailed code still applies.
- When `false`, sign-in behaves exactly as today.

### 3.3 Errors

| Case | Answer |
|---|---|
| Allowance used up at a workflow start or a render | 402 `plan_limit_reached` with `kind`, `used`, `allowance`, `period_end` |
| Checkout without Xendit configured | 503 `billing_unavailable` |
| Xendit unreachable or refusing at checkout | 502 `payment_provider_unavailable`; invoice `failed` |
| Unknown or inactive plan | 404 `unknown_plan` |
| Checkout by a member who is not owner or admin | 403 `Not authorized` |
| Checkout for `ws_bootstrap` | 409 `operator_workspace` |
| Webhook with a wrong token | 401; nothing changes |
| Billing tables unavailable during an allowance check | 503: the start is refused, never admitted, so costs never exceed what was paid |

### 3.4 Testing

All offline. Xendit is faked at the HTTP layer; no call reaches Xendit until the final
acceptance.

1. **Allowances:**
   - the free plan admits 3 workflows and 1 video, then answers 402;
   - a failed render gives its unit back;
   - `ws_bootstrap` is never refused;
   - an operator-granted plan applies.
2. **Race on PostgreSQL:** two starts at the last unit admit exactly one.
3. **Periods:**
   - free rolls forward;
   - an unpaid plan falls back to free at `period_end`;
   - a payment extends the same plan or starts a new one.
4. **Webhook:**
   - a wrong token answers 401;
   - `PAID` twice extends once;
   - a mismatched amount is not applied;
   - `EXPIRED` changes only the invoice;
   - an unknown invoice is ignored.
5. **Checkout:**
   - the Xendit request carries the amount, `external_id`, email and redirect URLs;
   - a Rp0 plan needs no invoice;
   - Xendit down answers 502.
6. **Admin:**
   - plans can be edited from the CLI and the API;
   - `free` cannot be deactivated;
   - the margin report is `complete: false` without unit prices;
   - admin routes require a platform admin, and billing routes pass the sub-project 2
     structural route test.
7. **Sign-up:** the flag off keeps the restriction; the flag on admits an outside user to `free`.
8. **Dashboard:** the Billing page, and the limit message on start and render.
9. **Stack smoke in CI:** a second workspace sees `free`, and its fourth workflow start answers
   402.

### 3.5 Rollout

- Migration `0016` adds `plans` (seeded with `free`), `subscriptions` and `invoices`. Nothing is
  dropped.
- On deploy, every workspace except `ws_bootstrap` is held to the free allowance. Today only the
  operator's workspace exists.
- **Operator gates, deferred until every feature is finished:**
  - a public HTTPS address for Thoth (a domain, or a tunnel for testing). Xendit calls the
    webhook from the internet and cannot reach `localhost:8088`. Then set `THOTH_SITE_ORIGIN` and
    the OAuth redirect URIs to that address, and register
    `https://<host>/billing/webhooks/xendit` in the Xendit dashboard;
  - the Xendit keys;
  - paid plans and their prices (judged with the margin report once meter unit prices are set);
  - turning public sign-up on.

## Out of scope

- Tax invoices (PPN, e-Faktur).
- Automatic refunds; refunds go through the Xendit dashboard by hand.
- Proration when changing plans mid-period.
- Coupons and discounts.
- Currencies other than rupiah.
- Automatic debit and card-on-file renewals.
