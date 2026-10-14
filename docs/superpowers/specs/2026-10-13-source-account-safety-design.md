# Source account safety — design

Date: 2026-10-13. Status: design approved in conversation by the operator (choices below); this
document awaits the operator's review of the written text.

Research: `docs/research/2026-10-13-account-safety-research.md`. Trigger: an operator Instagram
account was flagged (`feedback_required`) after a burst of private-API probes. Signed-in
Instagram reels listing (`acquisition/instagram_reels.py`) and every other signed-in browser
session must not get accounts flagged again.

## 1. Operator decisions (2026-10-13)

| Decision |
|---|
| Do all four: report platform warnings; a persistent browser profile per account; a daily budget per account; Camoufox with BrowserForge as a second engine. |
| The profile is stored encrypted between uses, with the vault key. |
| The engine stays Patchright for every platform by default; switching a platform to Camoufox is a policy change made after a CreepJS/BrowserScan comparison. |
| Default daily budgets per account: Instagram 20, TikTok 40, X 30, YouTube 60, Threads 30; Instagram spacing at least 10 minutes. |
| The three pending Instagram reaction goldens are recaptured after this work, spaced 10 minutes apart. |
| Amendment (2026-10-14, operator asked for research on the engine–fingerprint mismatch): fingerprints and profiles are per engine. Patchright gets no injected fingerprint; Camoufox gets a Firefox fingerprint from its own generator (fpgen), not BrowserForge. See 3.2 and 3.4. |

## 2. Scope

In scope: the four defenses below, for signed-in sessions (an account is leased). Anonymous
sessions are unchanged.

Out of scope: proxy procurement (operational); account warm-up (operational); an automatic
engine switch.

## 3. Design

### 3.1 Platform warnings cool the account

- `DiscoveryReason` gains `CHALLENGE`. A signed-in Instagram session reports it when:
  - the final page path starts with `/challenge/` or `/accounts/suspended/`; or
  - a captured GraphQL body contains `feedback_required`, `checkpoint_required`, or
    `"spam":true`.

  A redirect to `/accounts/login` keeps `BLOCKED`. Patterns live in one table per platform, so
  TikTok and X can add theirs.
- `ProfileDiscoverer` maps reasons to lease outcomes:
  - `CHALLENGE` and `CAPTCHA` → `challenge`;
  - `BLOCKED` → `blocked`;
  - videos → `success`.

  The store's existing ladder (15 min, 1 h, 6 h, 24 h) then rests the account.
- A cooled account is never leased until its cooldown ends (existing behaviour). The new part is
  that Instagram's own warning now triggers it.

### 3.2 A persistent browser profile per account

- Each account has a profile, stored as a tar archive of the browser's user data directory,
  encrypted with the vault key (Fernet), at
  `THOTH_ACCOUNT_PROFILE_DIR/<account_id>.<engine>.profile`. A Chromium user data directory
  and a Firefox profile are different formats, so each engine keeps its own archive; switching
  a platform's engine and back finds the earlier profile again.
  `THOTH_ACCOUNT_PROFILE_DIR` defaults to `/var/lib/thoth/account-profiles`, a volume of its own.
- On lease:
  - the profile is decrypted into a private temporary directory (mode 0700);
  - `SessionAccess.browser_kwargs()` passes `user_data_dir`, and the account's `locale` and
    `timezone_id`.

  On release, the directory is archived and encrypted back, then removed. Cache directories
  (`Cache`, `Code Cache`, `GPUCache`, `Service Worker/CacheStorage`) are left out, and an
  archive over 64 MB drops them first.
- Cookies are still injected from the vault on every use. The vault remains the source of truth.
  A profile that cannot be decrypted is discarded, and a fresh one starts (a warning is logged).
- New columns on `source_accounts`:
  - `locale`, default `id-ID`;
  - `timezone`, default `Asia/Jakarta`.

  Both are editable in the dashboard.
- Deleting an account, or resetting its device fingerprint, deletes its profiles; a lease
  still open cannot write them back. Re-importing cookies keeps the profile: it is the same
  account on the same device (amended 2026-10-14).

### 3.3 A daily budget per account

- `source_account_policies` gains `daily_budget` (0 means unlimited). A new table
  `source_account_usage (account_id, day, uses)` counts leases per account per UTC day.
- `lease()` skips accounts whose `uses` for today reached the platform's budget, and increments
  `uses` when it leases. When every account is cooling down or over budget, there is no account
  for that lease. Discovery and acquisition already treat that as "no account", so they run
  anonymously, or end blocked in `always` mode.
- Defaults are written by the migration: Instagram 20, TikTok 40, X 30, YouTube 60, Threads 30.
  The Instagram `min_spacing_seconds` is raised to 600. The dashboard edits the budget next to
  the mode and spacing.

### 3.4 Camoufox as a second engine

- `source_account_policies` gains `engine`: `patchright` (default) or `camoufox`.
- A fingerprint must match the browser that presents it (research, 2026-10-14):
  - **Patchright** runs a real Chromium. It gets no injected fingerprint and no user-agent
    override: Scrapling's default user agent already carries the driven Chromium's version and
    the host OS, so it agrees with `sec-ch-ua` and `navigator.platform`. A stored Chrome user
    agent would drift from them after a Chromium upgrade, or claim another OS than the
    worker's. The account stays one returning device through its profile, locale, timezone,
    and proxy.
  - **Camoufox** is Firefox. camoufox 0.5.8 dropped BrowserForge for its own generator
    (fpgen) and raises `NonFirefoxFingerprint` for any other browser's fingerprint. Each
    account gets one Firefox fingerprint from `camoufox.fingerprints.generate_fingerprint()`
    on its first Camoufox lease, stored encrypted in `source_accounts.fingerprint_ciphertext`.
    Passing the same fingerprint back on every launch keeps Camoufox's identity salt stable,
    so fonts, voices, and noise seeds stay the same between visits (daijro/camoufox#442,
    #765). Camoufox fills the user-agent version from the installed browser.
  - The fingerprint never changes unless the operator resets it. A reset also deletes the
    account's profiles of both engines: the account becomes a new device.
- Switching a platform's engine makes each account appear once on a new device (another
  browser). The operator switches rarely, and only after the comparison below.
- An adapter, `CamoufoxSession`, implements the part of Scrapling's session interface that
  signed-in discovery uses: `fetch(url, page_setup=, page_action=, timeout=)` returning `url`,
  `status`, and `body`. It wraps Camoufox's Playwright browser.
  - Discovery sessions use the platform's engine.
  - Acquisition's card-cropping sessions stay on Scrapling and Patchright in this stage (they
    rely on Scrapling's selectors); that is a follow-up.
- `camoufox` (MIT; the browser binary is MPL-2.0; it brings `fpgen`) joins the `acquisition`
  extra. BrowserForge stays only as Scrapling's own dependency. The Dockerfile fetches the
  pinned Camoufox browser (and fpgen's model) at build time, and checks its import and binary
  as it does for the speech models.
- The engine is a policy value, switched per platform in the dashboard. The operator switches
  only after comparing both engines on CreepJS and BrowserScan with the account's profile, a
  live check under its own gate.

## 4. Failures

- A profile that fails to decrypt or archive is a warning: the session runs on a fresh profile.
  It never fails the acquisition.
- A missing `camoufox` package or browser, when a policy selects it, is an explicit error at
  worker start (`camoufox_missing`), following the operator's required-tools rule.
- Budget and cooldown exhaustion are "no account", never an error.

## 5. Security

- Profiles at rest are encrypted with the vault key. The temporary directory exists only during
  a lease, under a private mode-0700 directory, and is removed on release, including on failure.
- The fingerprint ciphertext, like cookies, never reaches logs, events, artifacts, or the
  dashboard. The dashboard shows only "fingerprint set" and a reset action.
- The vault key's rotation (a parked backlog item) must re-encrypt profiles and fingerprints too.
  That is noted for that feature.

## 6. Testing

- Unit:
  - warning detection, one fixture per pattern;
  - reason-to-outcome mapping;
  - budget accounting, including the day boundary;
  - profile pack and unpack round-trip, cache pruning, and the size cap;
  - an undecryptable profile;
  - fingerprint generation and persistence;
  - engine selection;
  - the `CamoufoxSession` adapter against a fake browser.
- Migration 0009: upgrade and downgrade, on SQLite and on the disposable Postgres used by the
  existing migration tests.
- API and dashboard:
  - policy fields `daily_budget` and `engine`;
  - account fields `locale` and `timezone`;
  - the fingerprint reset;
  - the generated client types.
- Required tools: a test fails, never skips, when `camoufox` or its browser is missing.
- Live, under its own operator gate:
  - a CreepJS and BrowserScan comparison of Patchright and Camoufox with one account's profile;
  - then the recapture of the three pending Instagram reactions, 10 minutes apart.

## 7. Operator gates

1. The live fingerprint comparison.
2. The recapture.
3. Push, merge, deploy. The deploy adds the `account-profiles` volume and runs migration 0009.

## 8. Follow-ups

- Camoufox for acquisition's card-cropping sessions.
- Per-platform warning patterns for TikTok and X.
- Proxy health checks (residential or datacenter, geo).
- Profile and fingerprint re-encryption when the vault key rotates.
