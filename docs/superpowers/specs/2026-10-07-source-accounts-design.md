# Source Accounts: Multi-Account Rotating Login for Acquisition

Status: design approved section by section by the operator on 2026-10-07; written spec
awaiting operator review.

## 1. Context and scope

Stages 2 and 3 ported acquisition for TikTok, Threads, Instagram, X, and YouTube to the
Python kernel. Every platform runs anonymously. Anonymous access caps what acquisition can
read: Instagram hides views and later comment pages, X serves short timelines and few
replies, and YouTube refuses age-restricted videos. This feature lets acquisition use
logged-in sessions: each platform has a pool of accounts used in rotation, managed from the
dashboard.

The operator chose:

- **Cookie import only.** The operator logs in with a normal browser, exports the cookies,
  and uploads them in the dashboard. Interactive login through a worker-run browser is a
  follow-up (section 10). Username and password login is never automated.
- **Storage A.** Encrypted columns in the existing editor Postgres, through SQLAlchemy ORM
  and an Alembic revision, with the key in `THOTH_ACCOUNT_VAULT_KEY`.
- **Usage mode C.** One mode per platform, set in the dashboard: `anonymous`, `fallback`
  (default), or `always`.
- **The rotation and health policy in section 4.**
- **An optional proxy per account**, from the first version.
- **Integration A.** One shared `AccountBroker`; the acquirers only receive a session.
- **Decomposition.** This spec covers the account core and its dashboard page. Login-only
  platform capabilities (Instagram views and comment pages, longer X timelines, and so on)
  are a later sub-project.
- **UI design.** A design agent draws the "Source Accounts" page in
  `design/thoth-dashboard.pen`; the implementation follows those frames.

These stay as they are:
- With every platform in `anonymous` mode, or with the feature unavailable, acquisition
  behaves exactly as today.
- No new failure codes. `RETRYABLE_FAILURES` and `LEGACY_FALLBACK_ELIGIBLE_CODES` are
  unchanged.
- No live test in the suite.
- The Temporal workflows do not change; no account data enters Temporal history.

## 2. Data model and vault

An Alembic revision in the editor database adds two tables, mapped with SQLAlchemy ORM.

**`source_account_policies`**, one row per platform:

| Column | Type | Notes |
|---|---|---|
| `platform` | text, primary key | `tiktok`, `threads`, `instagram`, `x`, `youtube` |
| `mode` | text | `anonymous`, `fallback`, or `always`; a missing row means `fallback` |
| `min_spacing_seconds` | integer | default 60, between 0 and 86400 |
| `updated_at` | timestamptz | |

**`source_accounts`**:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid, primary key | |
| `platform` | text | as above |
| `label` | text | operator-chosen, 1–64 characters, unique per platform |
| `status` | text | `healthy`, `cooldown`, `expired`, or `disabled` |
| `cooldown_level` | smallint | 0–4 |
| `cooldown_until` | timestamptz, nullable | |
| `leased_until` | timestamptz, nullable | set while an acquisition holds the account |
| `last_used_at` | timestamptz, nullable | |
| `last_outcome` | text, nullable | an outcome enum (section 4) |
| `success_count`, `failure_count` | integer | |
| `cookies_ciphertext` | bytea | Fernet token of the cookie set |
| `cookie_names` | text[] | names only, for display |
| `cookies_earliest_expiry` | timestamptz, nullable | earliest expiry among session cookies |
| `proxy_ciphertext` | bytea, nullable | Fernet token of the full proxy URL |
| `proxy_display` | text, nullable | `host:port` only |
| `created_at`, `updated_at` | timestamptz | |

**Vault.**
- `THOTH_ACCOUNT_VAULT_KEY` is a `SecretStr` holding a Fernet key.
- Cookie values and proxy credentials are decrypted only in the worker or the API process, at
  the moment a session is built.
- No key rotation in this version. If the key is missing, the feature is unavailable. If the
  key is wrong, an account that fails to decrypt is marked `expired` with the outcome
  `undecryptable`, and the operator re-imports it.

**Availability.** The feature is available when both `THOTH_ACCOUNT_VAULT_KEY` and
`THOTH_EDITOR_DATABASE_URL` are set. Otherwise:
- the API reports `available: false`, and write routes return 503
  `source_accounts_unavailable`;
- the dashboard shows a banner and disables its actions;
- acquisition runs anonymously, and the worker logs one `warn` at startup.

## 3. Cookie import

A pure module parses and validates an import; it holds no state.

**Formats.**
- Netscape `cookies.txt`, the format exported by yt-dlp and "Get cookies.txt"-style
  extensions. The `#HttpOnly_` prefix is honored.
- A JSON array of cookie objects, as exported by Cookie-Editor or EditThisCookie (keys
  `name`, `value`, `domain`, `path`, `expirationDate` or `expires`, `secure`, `httpOnly`,
  `sameSite`).

**Validation.**
- Keep only cookies whose domain belongs to the platform; drop the rest silently. The
  platform domains are:
  - TikTok: `tiktok.com`;
  - Threads: `threads.net`, `threads.com`, `instagram.com`;
  - Instagram: `instagram.com`;
  - X: `x.com`, `twitter.com`;
  - YouTube: `youtube.com`, `google.com`.
- Drop expired cookies. If none remain, reject with `all_cookies_expired`.
- Require the platform's authentication cookies, else reject with `missing_required_cookie`
  and the missing names:

  | Platform | Required cookies |
  |---|---|
  | Instagram | `sessionid` |
  | Threads | `sessionid` |
  | X | `auth_token`, `ct0` |
  | TikTok | `sessionid` |
  | YouTube | `SAPISID`, `__Secure-3PSID` |

- Reject input over 256 KB or with more than 500 cookies, with `invalid_cookie_file`.
- The result is a `CookieSet` plus a safe summary: count, names, earliest expiry, and the
  error code if any. No message ever contains a cookie value.

**Proxy.** An optional URL with scheme `http`, `https`, or `socks5`, a host, a port, and
optional credentials. It is validated, encrypted whole, and displayed as `host:port`.

## 4. Rotation and health

**`AccountBroker`** (`acquisition/accounts/broker.py`).

`lease(platform) -> AccountLease | None`, in one transaction:
- `SELECT … FOR UPDATE SKIP LOCKED` over accounts of the platform where:
  - `status = 'healthy'`, or `status = 'cooldown'` and `cooldown_until <= now()`;
  - `last_used_at` is null or at least `min_spacing_seconds` ago;
  - `leased_until` is null or in the past;
- order by `last_used_at` (nulls first), take one;
- set `leased_until = now() + 10 minutes` and `last_used_at = now()`;
- decrypt; on failure, mark it `expired` with `undecryptable` and try the next account.

`report(lease, outcome)` clears `leased_until` and applies:

| Outcome | Effect |
|---|---|
| `success` | `healthy`, `cooldown_level = 0`, `success_count + 1` |
| `blocked`, `challenge`, `rate_limited` | `cooldown`; `cooldown_level` rises by 1 (at most 4); `cooldown_until = now()` + 15 min, 1 h, 6 h, then 24 h for levels 1–4; `failure_count + 1` |
| `login_wall` | `expired`; `failure_count + 1` |
| `undecryptable` | `expired` |

A `disabled` account is never leased and is only changed from the dashboard. A lease whose
holder died expires after 10 minutes, which is longer than the 5-minute acquisition activity.

## 5. Integration with acquisition

**The seam** is `build_production_acquisition_runner` in
`activities/source_investigation.py`. The runner reads the platform's policy, leases when
the mode requires it, builds the acquirer, and reports the outcome.

**`SessionAccess`** holds the decrypted cookies and proxy of one lease. Each access path
gets an adaptor:
- **Scrapling browser** (TikTok headless, every card browser): `cookies=` (Playwright
  cookie dicts) and `proxy=` when the `AsyncStealthySession` is created.
- **Request fetchers** (Threads, Instagram, X): `cookies=` and `proxy=` on
  `AsyncFetcher.get`.
- **yt-dlp**: `cookiefile` (a temporary Netscape file, mode 0600, under the activity's work
  directory, deleted in `finally`) and `proxy`.

`acquirer_for(source_url, *, client, materializer, access=None)` passes `access` to the
platform's fetcher, browser, and yt-dlp client. The acquirers know nothing about rotation.

**Modes.**
- `anonymous`: run as today.
- `always`: lease. If an account is leased, run with it; otherwise run anonymously and emit
  `no_account_available`.
- `fallback`: run anonymously. If the result is blocked or hit a login wall, lease one account
  and run once more with it. One retry only, to stay inside the activity budget.

**Outcome mapping** from the acquisition result to the account outcome:
- No failure: `success`.
- `request_blocked`, `headless_blocked`: `blocked`.
- `cdn_rate_limited`, or an HTTP 429 seen by a fetcher: `rate_limited`.
- A captcha or challenge page: `challenge`.
- The new internal reason `login_wall` in `outcome.attempts`, only when an account was used:
  `login_wall`.
- Timeouts and `media_validation_failed` do not change the account's health. The lease is
  released with `success` counters untouched.

**Login wall detection.**
- `AcquisitionReason.LOGIN_WALL = "login_wall"` is an attempt reason. The failure code stays
  `request_blocked`. This adds no failure code.
- Per platform:
  - Instagram: a redirect to `/accounts/login`;
  - Threads: a redirect to its login page;
  - X: a redirect to `/i/flow/login`, or a login page instead of the post;
  - TikTok: a login page or a login modal instead of the post;
  - YouTube: "Sign in to confirm" while cookies were supplied.

**Events.** Temporal progress events carry only enums and booleans: `account_used`,
`account_outcome`, `no_account_available`. They never carry an account id, a label, or a
proxy.

## 6. API

Routes on the Python control plane, with the API key auth and prefix of the `workflows`
routes. They are added to `python/openapi.json`, and the dashboard regenerates its types
with `generate:control-plane-types`.

| Route | Purpose |
|---|---|
| `GET /source-accounts` | `available`, plus per platform: mode, spacing, counts per status, and accounts with safe fields only |
| `PUT /source-accounts/policies/{platform}` | set `mode` and `min_spacing_seconds` |
| `POST /source-accounts/validate` | dry run of an import: the safe summary, nothing stored |
| `POST /source-accounts` | add an account: platform, label, cookies, optional proxy |
| `PUT /source-accounts/{id}/cookies` | re-import: status `healthy`, cooldown reset |
| `PATCH /source-accounts/{id}` | label, proxy (omitted keeps it, `null` clears it, a value sets it), disabled flag |
| `DELETE /source-accounts/{id}` | delete |
| `POST /source-accounts/{id}/test` | the session check (below) |

- Safe account fields: id, platform, label, status, cooldown until, last used, last
  outcome, counters, cookie names, earliest expiry, proxy display, timestamps.
- Request bodies are never logged. Validation errors name fields and codes, never values.
- A route that changes an account never returns the cookies or the proxy.

**Session check.**
- It runs in the API process: one impersonated request per platform to a logged-in-only
  page or endpoint, with the account's cookies and proxy, and a 20-second timeout.
- It returns `valid` (status `healthy`), `expired` (status `expired`), or `inconclusive`
  (timeout or blocked; status unchanged).
- The check endpoint of each platform is fixed by a live probe in the planning step, under
  the operator's authorization at probe time, and pinned by fixtures. The suite stays
  offline.

## 7. Dashboard

- A "Source Accounts" page follows the frames in `design/thoth-dashboard.pen`. If the frames
  are not ready when implementation reaches the UI task, the work stops and asks.
- Navigation: a "Source Accounts" item in the sidebar's "Tools" group. Eyebrow
  "Access / 07"; description "Logged-in sessions that acquisition rotates through, per
  platform."
- Per platform:
  - the mode selector and the spacing field;
  - status counts;
  - the account table: label, status, proxy display, cookie names, earliest expiry, last
    used, last outcome, counters, and actions (test, re-import, edit, disable or enable,
    delete).
- The add and re-import dialogs call `validate` as the input changes and show its safe
  summary before saving.
- States:
  - unavailable;
  - an empty platform;
  - mixed statuses;
  - "no healthy account" on a `fallback` or `always` platform;
  - dialog errors;
  - narrow width.
- Code: `dashboard/src/components/SourceAccounts.tsx` with its tests, reusing `PenDialog`, the
  badges, and the existing page patterns.

## 8. Security

- Cookie values and proxy credentials exist only in three forms:
  - as ciphertext in the database;
  - in process memory while a session is built;
  - in the yt-dlp temporary cookie file, which is deleted in `finally`.
- Logs, reports, Temporal events, API responses, and error messages never contain a cookie
  value, a proxy credential, or a URL. Events never contain an account id or a label.
- A leak test feeds sentinel cookie and proxy values through import, lease, acquisition,
  report, and every API route. It asserts that the sentinels appear in no log record, no
  response, and no event.

## 9. Testing (offline only)

- **Cookie parser:**
  - Netscape and JSON formats, and the `#HttpOnly_` prefix;
  - domain filtering, required cookies, expiry;
  - the size and count limits, and broken input.
- **Vault:** round trip; a wrong key gives `undecryptable`.
- **Broker**, on the test Postgres pattern the repositories already use:
  - least-recently-used order, spacing, and `SKIP LOCKED` under two concurrent leases;
  - lease expiry, the cooldown ladder, `expired`, and `disabled`.
- **Runner:**
  - all three modes, and the single `fallback` retry;
  - `no_account_available`, the outcome mapping, and that timeouts leave health alone.
- **Adaptors:** cookies and proxy reach the Scrapling session, the fetcher, and the yt-dlp
  options (through fakes); the cookie file is deleted.
- **Login wall detection** per platform, from fixtures.
- **API:** every route; 503 when unavailable; no secret in any response.
- **Dashboard:** component tests for each state and both dialogs.
- **The leak test** in section 8.

Verification: the full Python suite, Ruff, the dashboard tests and type check, and the
Alembic upgrade and downgrade. No Rust changes.

## 10. Follow-ups (out of scope, recorded)

1. **Interactive login through a worker-run browser.** The dashboard opens a browser the
   worker runs, through a remote view. The operator logs in there, including 2FA, and the
   session goes straight into the vault. This is the operator's option B, deferred by
   decision on 2026-10-07.
2. **Login-only platform capabilities:**
   - Instagram views and later comment pages;
   - longer X timelines and more replies;
   - age-restricted YouTube videos;
   - TikTok content that needs a session.
3. **Vault key rotation.**

## 11. Gates outside this spec

- The session-check probe in the planning step needs operator authorization at probe time.
- One live smoke with real accounts joins the final acceptance (ADR 0001).
- Push, merge, and deploy are each a separate operator authorization.
- Buying proxies and creating accounts are the operator's.

## Appendix: proxy recommendations (researched 2026-10-07)

**What to buy.**
- One **dedicated static ISP (static residential) IP per account**, in the country where the
  account normally logs in. A login from a new country is a common trigger for challenges.
- Avoid rotating residential proxies for accounts: a changing IP looks like account sharing.
- Avoid shared IPs: other users' traffic burns them.
- Prefer **unlimited bandwidth**. Media downloads (YouTube DASH, TikTok and Instagram video)
  go through the proxy, so per-GB pricing grows quickly.

**Shortlist.** Listed prices are from the providers' pages and third-party reviews at
research time; confirm at checkout.

| Provider | Product | Indicative price | Notes |
|---|---|---|---|
| Webshare | Dedicated static residential | about $1.80/IP/month at volume | Its $0.23–0.30/IP static residential plans are shared; take the dedicated ones for accounts |
| Proxy-Cheap | Static residential (ISP) | about $1.27–1.99/IP/month | Low entry price |
| IPRoyal | ISP (static residential) | about $2.40–2.70/IP/month | Widely used; daily plans exist |
| Rayobyte | ISP | from $0.95/IP/month | Annual commitment, mostly US |
| NodeMaven | ISP | about $2.99/IP/30 days | Fraud-score checked IPs |

**Suggested start.** Two or three accounts on the platforms that need login most (Instagram,
then X), each with one dedicated ISP IP from Proxy-Cheap or Webshare (dedicated). Check that
the provider has IPs in the accounts' country. Indonesian ISP IPs are scarcer and cost more
than US ones.

Sources:
- [Proxyway: best ISP proxies 2026](https://proxyway.com/best/isp-proxies)
- [Webshare static residential](https://www.webshare.io/static-residential-proxy)
- [Webshare dedicated static residential](https://www.webshare.io/dedicated-static-residential-proxy)
- [Proxy-Cheap ISP proxies](https://www.proxy-cheap.com/services/isp-proxies)
- [IPRoyal ISP proxies](https://iproyal.com/isp-proxies/)
- [Rayobyte ISP proxies](https://rayobyte.com/products/isp-proxies/)
- [ProxyEmpire: cheapest static residential compared](https://proxyempire.io/best-cheap-static-residential-proxies/)
- [HypeProxies: best ISP proxy providers](https://hypeproxies.com/blog/best-isp-proxy-providers)
