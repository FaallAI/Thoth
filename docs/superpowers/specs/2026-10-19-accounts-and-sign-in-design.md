# Accounts, sign-in and developer access (SaaS sub-project 1)

Status: design approved in conversation on 2026-10-19; this file awaits the operator's review.

## Why

The operator wants Thoth to become a SaaS: people sign up and pay a subscription priced from
the real cost of a workflow and a video. The work splits into four sub-projects, built in order:

1. **Accounts, sign-in and developer access** (this spec; roadmap UI phase 3, priority 5,
   moved ahead of priority 2 by the operator on 2026-10-19).
2. Multi-tenancy: every project, workflow, draft, asset and media object belongs to one workspace,
   and access follows membership. It must land before any public sign-up.
3. Metering and the cost model: the real cost of each workflow and video (LLM and vision tokens,
   TTS characters, render minutes, storage), which gives the price, the plans and the quotas.
4. Billing and payments: a payment provider, subscriptions with usage overage, invoices, webhooks,
   and quota enforcement.

Roadmap priority 2 (Workflow to Studio with media) resumes after this sub-project. Its brainstorm
checkpoint is kept in the gitignored SDD workspace.

Today the dashboard runs only through `vite dev` on the operator's laptop. The control-plane key
ships inside the JS bundle, and every request acts as the single `owner` actor.

## Outcome

- The deployed stack serves the dashboard from a `web` container at `http://localhost:8088`. A
  later deploy only needs a domain to get automatic HTTPS.
- People sign in with Google or GitHub, followed by a one-time code sent by email.
- The browser never holds an API key.
- Developers reach the API with scoped, expiring, revocable tokens. The local dashboard works
  without signing in, and the server has no bypass.

## Decisions (operator, 2026-10-19)

| Topic | Decision |
|---|---|
| Reach | Localhost first, ready for a domain (Caddy automatic HTTPS) without code changes |
| Who may sign in | Google accounts in one email domain; GitHub members of one organization |
| Verification | The provider must report the email as verified, **and** a one-time code is emailed |
| Code frequency | Once per browser; the browser is trusted for 30 days |
| Approach | Sign-in in the control plane with Authlib; Caddy serves the SPA |
| Developer access | Personal tokens for the internal team (API and CLI); workspace tokens for external developers (built now, issued only after sub-projects 2-4); local dashboard through a Vite proxy that injects a token |
| Sign-up | Closed (the domain and organization rules) until billing exists |

## 1. Serving: the `web` container

- **Image `thoth-web`,** built from a new `Dockerfile.web` in two stages:
  1. `bun install --frozen-lockfile` and `bun run build` of `dashboard/`;
  2. `caddy:2`, pinned by digest, with `dist/` and `deploy/web/Caddyfile`.
- **CI** builds and publishes `thoth-web` next to `thoth` and the renderer. Deploy pins
  `THOTH_WEB_IMAGE` by digest in `.env.stage1.local`.
- **Compose:** a new `web` service, published on `127.0.0.1:${THOTH_WEB_PORT:-8088}`. The `api`
  port 8000 stays published on localhost for the CLI and the smokes.
- **Caddyfile:**
  - the site address comes from `{$THOTH_SITE_ADDRESS::8088}`;
  - `/api/v1/*` and `/auth/*` go to `api:8000` through `reverse_proxy`. Caddy holds no credential;
  - every other path goes to `file_server`, with `try_files {path} /index.html` as the SPA fallback;
  - security headers:
    - a strict `Content-Security-Policy` (`default-src 'self'`; media, images and connections only
      from self);
    - `X-Frame-Options: DENY`;
    - `Referrer-Policy: strict-origin-when-cross-origin`;
    - `X-Content-Type-Options: nosniff`;
  - caching: `Cache-Control: no-store` for `index.html`, and a one-year immutable lifetime for the
    hashed files under `assets/`.
- **Vite dev** proxies `/api/v1` and `/auth` to the control plane (see 3.4).

## 2. Sign-in flow

All routes live in a new `thoth_control_plane.api.routes.auth` module under `/auth`.

1. **`GET /auth/me`** returns the signed-in user and workspace, or 401. The SPA calls it at start.
   The login pages are the only views shown without a session.
2. **`GET /auth/login/{provider}`,** where the provider is `google` or `github`. Authlib redirects
   with `state` and PKCE, plus a `nonce` for Google. The state lives in a signed cookie
   (`itsdangerous`, Starlette `SessionMiddleware`) scoped to `/auth`, which expires after 10 minutes.
3. **`GET /auth/callback/{provider}`** checks the identity on every sign-in:
   - **Google** (OpenID Connect, `server_metadata_url`):
     - Authlib validates the `id_token`;
     - `email_verified` must be true;
     - the email must end in `@{THOTH_AUTH_GOOGLE_DOMAIN}` (case-insensitive);
     - an `hd` claim, when present, must equal that domain.
   - **GitHub** (scopes `read:user user:email read:org`):
     - the primary email from `GET /user/emails` must be `verified`;
     - `GET /user/memberships/orgs/{THOTH_AUTH_GITHUB_ORG}` must report `state: active`.
   - **A failure** redirects to `/login?error=<code>`, with one of the fixed codes
     `unverified_email`, `not_allowed`, `provider_error` and `not_configured`. Provider text never
     reaches the page or the logs.
4. **An accepted identity** is matched to a user through `user_identities` (provider, subject). On
   a first sign-in it is matched by verified email: one person who uses Google and GitHub with the
   same email is one user. The very first user of the installation becomes the owner of the
   bootstrap workspace that migration `0013` creates, which owns the existing data (3.6). Every
   later new user gets a personal workspace as its owner.
5. **The email code.** When the browser holds no valid trusted-device cookie for this user, the
   server creates an email challenge:
   - a 6-digit code, stored only as an HMAC with `THOTH_AUTH_SECRET`;
   - valid for 10 minutes, with at most 5 attempts;
   - a resend no sooner than 60 seconds after the last one;
   - at most 10 codes per email per day.

   The code goes to the verified email over SMTP. The response redirects to `/login/verify` and
   sets a short-lived challenge cookie.
6. **`POST /auth/verify`** takes `{code, trust_device}`.
   - A match creates a session, rotating any previous one.
   - When `trust_device` is set (it is on by default in the UI), it also sets the trusted-device
     cookie for 30 days.
   - It then redirects to the validated `next` path.
7. **`POST /auth/resend`** sends a new code, subject to the limits above.
8. **`POST /auth/logout`** revokes the session. `{"forget_device": true}` also revokes the trusted
   device.

`next` is accepted only as a same-origin absolute path (it starts with `/` and not with `//`).
Anything else becomes `/workflows`.

## 3. Sessions, tokens and API protection

### 3.1 Tables

The tables go in editor database migration `0013_accounts.sql`, with SQLAlchemy models, following
the project direction.

| Table | Columns, in short |
|---|---|
| `users` | id, email (unique, lower-case), display_name, created_at, disabled_at |
| `user_identities` | provider, subject (unique together), user_id, email_at_sign_in, last_sign_in_at |
| `workspaces` | id, name, created_at |
| `workspace_members` | workspace_id, user_id, role (`owner`/`admin`/`member`), created_at |
| `sessions` | id, user_id, workspace_id, token_hash (unique), created_at, last_seen_at, expires_at, revoked_at |
| `trusted_devices` | id, user_id, token_hash (unique), created_at, expires_at, revoked_at |
| `email_challenges` | id, user_id, token_hash (the challenge cookie), code_hmac, attempts, created_at, expires_at, consumed_at |
| `access_tokens` | id, owner_kind (`user`/`workspace`), owner_id, name, prefix, token_hash (unique), scopes, created_at, expires_at, last_used_at, revoked_at |
| `auth_events` | id, at, kind, user_id, token_id, outcome, detail_code. It never holds a secret, a code or an email body. |

Every token is 32 random bytes from `secrets.token_urlsafe`. The database stores only its SHA-256
hash, and every comparison is constant-time.

### 3.2 Session cookie

- The cookie is `thoth_session`: `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` when the site
  is served over HTTPS (`THOTH_AUTH_COOKIE_SECURE`, on automatically when the site address is
  HTTPS).
- The session lasts 12 hours, renewed on use, and never longer than 7 days in all. It is rotated
  on sign-in.
- **Origin check.** Every unsafe method (POST, PUT, PATCH, DELETE) authenticated by the cookie must
  carry an `Origin` equal to the configured site origin; otherwise it is refused with 403. A
  bearer-token request needs no Origin.

### 3.3 Developer tokens

- **Format:** `thoth_pat_<random>`, sent as `Authorization: Bearer`. The fixed prefix lets
  secret-scanning tools recognise a leaked token.
- **Scopes:** `read`, `write` (implies read) and `admin` (implies both). Mutating routes require
  `write`; token and member management require `admin`.
- **Lifetime:** 90 days by default and 1 year at most; nothing lasts forever. `last_used_at` is
  updated at most once a minute.
- **Visibility and limits:**
  - the token text is shown once, at creation;
  - each user may hold at most 20 active tokens;
  - revoking takes effect immediately.
- **API:**
  - `GET /api/v1/me` returns the principal's user, workspace and scopes.
  - `GET /api/v1/me/tokens` and `POST /api/v1/me/tokens` list and create the caller's personal
    tokens.
  - `DELETE /api/v1/me/tokens/{token_id}` revokes one.
  - All three need a signed-in user (a session, or a personal token with `admin`). The service key
    has no user, so it gets 403 `user_required`.
- **Bootstrap CLI:** `thoth-control tokens create --email EMAIL --name NAME [--scope write]
  [--days 90]`.
  - It needs database access, so it is an operator command.
  - It creates the user when missing; the first user becomes owner of the bootstrap workspace.
  - It prints the token once.
  - This is how a developer gets `THOTH_DEV_TOKEN` before OAuth is configured, and how the smoke
    gets a token.
- **Owners:**
  - **Personal tokens** belong to a user, for the internal team, the CLI and scripts.
  - **Workspace tokens** belong to a workspace, for external developers. The code path exists and
    is tested, but issuing one is refused (`workspace_tokens_disabled`) until
    `THOTH_AUTH_WORKSPACE_TOKENS=true`. That flag waits for sub-projects 2-4, so that external use
    counts against quotas.

### 3.4 The local dashboard without signing in

The server never bypasses authentication. During development, `dashboard/vite.config.ts` adds
`Authorization: Bearer ${THOTH_DEV_TOKEN}` to proxied `/api/v1` requests.
- `THOTH_DEV_TOKEN` is a personal token read from the developer's local environment by Node; it is
  never a `VITE_` variable, so it never enters a bundle.
- Without the variable, the dev dashboard shows the normal login page.

### 3.5 The legacy owner key

- `THOTH_CONTROL_PLANE_API_KEY` stays accepted as a **service token** for the smokes, CI and the
  deploy scripts. It maps to the bootstrap owner with every scope. Its use is recorded in
  `auth_events` at most once a minute per API process, so a smoke does not write a row per
  request.
- `vite build` fails when `VITE_CONTROL_PLANE_API_KEY` is set, so the key can never be bundled
  again.
- Removing the service key is a follow-up, once every script uses a personal token.

### 3.6 Principal and authorization

- **`current_principal`** accepts a session cookie, a developer token or the service key. It returns a
  `Principal(user_id | None, workspace_id, scopes, via)`, where `via` is `session`, `token` or
  `service`.
- **`current_actor` keeps returning the data actor `Actor(actor_id="owner", actor_type="user")`**
  for every principal of the bootstrap workspace.
  - Today data ownership is keyed by `actor_id`: workflow IDs are derived from it, Temporal checks
    the owner, and the run lists filter by it. Giving each user their own actor ID would hide the
    existing data from everyone.
  - Sub-project 2 replaces this with workspace ownership.
  - `display_name` carries the user's email, for audit.
- **Existing routes keep their signatures** (48 routes depend on `current_actor`).
  - `current_actor` requires the `write` scope for every unsafe method (POST, PUT, PATCH, DELETE),
    and answers 403 `insufficient_scope` otherwise.
  - It also applies the Origin check (3.2) to cookie-authenticated requests.
- **Data ownership is unchanged in this sub-project.** Every authenticated principal still sees the
  single existing dataset. Sub-project 2 scopes data by workspace, and public sign-up stays closed
  until then.
- **Bootstrap.** Migration `0013` creates one bootstrap workspace, which the service key maps to and
  which sub-project 2 assigns the existing data to. The first user to sign in becomes its owner.

## 4. Dashboard

- **`/login`:** "Continue with Google" and "Continue with GitHub", plus fixed copy for each error
  code.
- **`/login/verify`:**
  - a 6-digit input (`inputmode="numeric"`, `autocomplete="one-time-code"`);
  - resend with a countdown;
  - "Trust this browser for 30 days", checked by default.
- **Auth gate:**
  - The app calls `/auth/me` at start, which answers 401 when nobody is signed in.
  - The API keeps its existing contract: a request without valid credentials gets 403 `Not
    authorized`, which 19 tests already pin.
  - When any API call gets that 403, the app re-checks `/auth/me`. A 401 there redirects to
    `/login?next=<current path>`.
- **Clients:** `control-plane.ts` and `source-accounts.ts` drop the `Authorization` header and
  `VITE_CONTROL_PLANE_API_KEY`. Requests are same-origin and carry the cookie.
- **Workspace menu:**
  - shows the user's initials and email;
  - **Developer tokens** opens `/settings/tokens`: create (name, scope, lifetime; the text is shown
    once with a copy button), list (name, prefix, scope, created, last used, expires), and revoke
    with a confirmation;
  - **Sign out**, and **Sign out and forget this browser**;
  - the disabled "Account settings" entry goes.

## 5. Errors, security, testing and operations

**Failures:**
- An unreachable provider gives `provider_error`.
- An SMTP failure creates no usable challenge. The page says the code could not be sent, and the
  server logs a `warn` without the address.
- With no OAuth credentials configured, the login page says sign-in is not configured, and the API
  accepts only tokens.

**Configuration** (new settings, all optional; missing values degrade as described):

| Setting | Holds |
|---|---|
| `THOTH_AUTH_SECRET` | The secret for HMACs and cookie signing |
| `THOTH_AUTH_GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `THOTH_AUTH_GOOGLE_CLIENT_SECRET` | Google OAuth client secret (secret) |
| `THOTH_AUTH_GOOGLE_DOMAIN` | The one email domain Google sign-in accepts |
| `THOTH_AUTH_GITHUB_CLIENT_ID` | GitHub OAuth App client ID |
| `THOTH_AUTH_GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret (secret) |
| `THOTH_AUTH_GITHUB_ORG` | The organization GitHub sign-in requires |
| `THOTH_SMTP_HOST` | SMTP server host |
| `THOTH_SMTP_PORT` | SMTP server port |
| `THOTH_SMTP_USERNAME` | SMTP user |
| `THOTH_SMTP_PASSWORD` | SMTP password (secret) |
| `THOTH_SMTP_FROM` | The sender address |
| `THOTH_SITE_ORIGIN` | The site origin, for redirect URIs and the Origin check |
| `THOTH_AUTH_WORKSPACE_TOKENS` | Enables issuing workspace tokens; off by default |

- A provider is offered only when its client ID, secret and rule (domain or organization) are all
  set.
- Email codes need the SMTP values. Without them no one can complete sign-in: sign-in fails closed.

**Security:**
- Secrets live only in `.env`, and logs never print them.
- Tokens, codes and HMACs are compared in constant time.
- Sessions rotate on sign-in.
- Rate limits are kept in the database (section 2). A per-IP limit at Caddy needs a plugin and is a
  follow-up.

**Dependencies:** `authlib` and `itsdangerous`, added to the control-plane package. Email uses the
standard library's `smtplib`, run through `asyncio.to_thread`.

**Testing** (offline only, per the operator's rule):
- **Python:**
  - Google and GitHub are faked with `httpx.MockTransport`: the token endpoint, a signed `id_token`
    from a test JWK, `/user/emails` and the organization membership;
  - mail goes through a fake sender port;
  - the cases cover each refusal (unverified email, wrong domain, wrong `hd`, not an organization
    member, membership pending), the code limits, a trusted device, session expiry and rotation,
    the Origin check, token scopes, expiry and revocation, the service key, `next` validation, and
    `vite build` refusing a bundled key;
  - the new tables are tested on Postgres.
- **Dashboard:** the login, verify and tokens pages, the 401 redirect, and the menu.
- **Stack smoke:**
  - `web` serves `index.html` on a deep path;
  - `/api/v1/workflows` through `web` answers 401 without a session;
  - a personal token created through the service key is accepted, then refused after revocation.
- A real OAuth round trip happens only at the final live acceptance.

**Operator gates:**
- Create a Google OAuth client of type Web application, with redirect
  `http://localhost:8088/auth/callback/google`.
- Create a GitHub OAuth App with callback `http://localhost:8088/auth/callback/github`, and approve
  it in the organization's third-party access settings.
- Provide an SMTP account.
- Set the env values above.
- Push, merge and deploy.
- Optionally set `networkingMode=mirrored` in `%UserProfile%\.wslconfig`, then run `wsl --shutdown`.
  Without it, Windows reaches the WSL ports only while a WSL session is open.

## Out of scope

- Data isolation between workspaces (sub-project 2).
- Inviting members.
- Public sign-up.
- Metering, prices, plans, quotas and payments (sub-projects 3-4).
- Per-IP rate limiting at Caddy.
- Removing the service key.
