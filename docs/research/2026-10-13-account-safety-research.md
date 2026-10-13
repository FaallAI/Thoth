# Keeping source accounts from being flagged — research

Date: 2026-10-13. One operator Instagram account was flagged during probing (`feedback_required`,
"Try Again Later") after about eight calls to the mobile private API in a short window. The
operator asked how to stop it happening again, and which open-source tools fit this project.

## 1. Why accounts get flagged

Platforms score a session on several signals at once (sources below):

| Signal | What looks automated |
|---|---|
| Rate and rhythm | bursts, many actions in minutes, fixed intervals |
| Endpoint | calls the official client does not make (mobile private API from a web session) |
| Network | datacenter IPs, the IP changing between logins, IP country different from the account's usual |
| Device | a new device fingerprint on every visit, a headless or automation fingerprint, a user agent that disagrees with the fingerprint |
| Account | a new account doing heavy work before a warm-up, simultaneous logins from different places |
| Reaction to warnings | carrying on after a challenge, which extends or escalates the block |

The 2026-10-13 flag hit three of these at once: a private endpoint, a burst, and a fresh
browser-less client.

## 2. What Thoth already has

| Defense | Where |
|---|---|
| Leasing one account at a time, with a minimum spacing per platform (`min_spacing_seconds`) | `infrastructure/source_account_store.py` |
| Escalating cooldown on `blocked`, `challenge`, `rate_limited`: 15 min, 1 h, 6 h, 24 h | `acquisition/accounts/policy.py` |
| A proxy bound to each account | `acquisition/accounts/access.py` |
| Signed in only where signed out is weaker (thin-listing rule) | `attribution/adapters/discovery.py` |
| A stealth browser (Scrapling on Patchright), TLS impersonation (curl_cffi) | Stage 3 |
| Reels through a real browser page, never the private API | `acquisition/instagram_reels.py` |

## 3. Gaps

1. **Every browser session is a new device.** Scrapling opens a temporary profile each time, so
   Instagram sees fresh local storage and device ids on every visit. Scrapling 0.4.15 accepts
   `user_data_dir`, `timezone_id`, `locale`, `block_webrtc`, and `hide_canvas`. One persistent
   profile per account, with a fixed locale and timezone matching the proxy's country, is the
   human pattern.
2. **Instagram's warnings are not reported.** The reels discovery treats only a login redirect as
   blocked. A `/challenge/` or `/accounts/suspended/` page, or a GraphQL body with
   `feedback_required`, `checkpoint_required`, or `login_required`, should report `challenge`,
   so the existing cooldown ladder rests the account at once.
3. **No daily budget.** Spacing limits the rhythm but not the volume. A per-account daily cap
   per platform stops a busy day from turning into a burst.
4. **Proxy quality is unknown.** Residential or mobile IPs, sticky per account, in the account's
   country, are what the sources agree on; datacenter IPs are flagged fastest.
5. **Account hygiene is operational.**
   - Dedicated accounts, never personal ones.
   - A 7–30 day warm-up of light manual use.
   - The manual login made through the same proxy the automation uses.
   - No logins from other places at the same time.
   - 2FA on.

## 4. Open-source tools

| Tool | License | Fit for Thoth | Verdict |
|---|---|---|---|
| **Scrapling** (Patchright inside) | BSD-3 | already in use; supports a persistent profile, timezone, locale, WebRTC and canvas protection | **keep; use its profile options** |
| **BrowserForge** | Apache-2.0 | generates a consistent fingerprint and header set; one could be stored per account | optional, if a fixed fingerprint per account is needed beyond Scrapling's |
| **Camoufox** | MPL-2.0 | Firefox patched at the C level; leads lab JS-fingerprint tests; a second browser engine in the image | fallback, if Patchright's fingerprint gets flagged |
| **nodriver** | AGPL-3.0 | leads live Cloudflare tests | not recommended: AGPL obligations, and Cloudflare is not our problem |
| **instagrapi** | MIT | private mobile API with delays and challenge handlers | **avoid**: its route flagged an account here |
| **Instaloader** | MIT | built-in rate controller; GraphQL | not needed: our browser route already covers it |
| **CreepJS, BrowserScan, Pixelscan** | open, or free web tools | check what a profile's fingerprint looks like before using it on a platform | use when tuning the profile |

## 5. Recommendation

No new framework. Harden what exists, in this order:

1. **Report Instagram warnings as `challenge`** from the reels discovery, so the cooldown ladder
   rests the account. This is the cheapest change and the one that stops a flagged account from
   being used again.
2. **One persistent browser profile per account** (`user_data_dir`), stored with the account, with a
   locale and timezone matching its proxy.
3. **A daily budget per account per platform**, next to `min_spacing_seconds` in the account
   policy. For Instagram, a spacing of at least 10 minutes between page loads.
4. **Operations**:
   - residential or mobile sticky proxies, one per account, in Indonesia;
   - a warm-up for new accounts;
   - the manual login through that same proxy;
   - dedicated accounts with 2FA.
5. **Later, only if needed**: Camoufox with BrowserForge, after CreepJS shows the Patchright
   profile being singled out.

## Sources

- [instagrapi: FeedbackRequired and challenge handling](https://docsearch.algolia.com/mcp/docs/repo/subzeroid/instagrapi)
- [Pixelscan: "feedback required" on Instagram](https://pixelscan.net/blog/follow-feedback-required-instagram/)
- [Pixelscan: action blocked on Instagram](https://pixelscan.net/blog/action-blocked-on-instagram/)
- [Pixelscan: Instagram disabled due to data scraping](https://pixelscan.net/blog/instagram-disabled-due-to-data-scraping/)
- [Databay: mobile proxies for Instagram 2026](https://databay.com/blog/best-mobile-proxies-for-instagram)
- [Scrappey: residential proxies for Instagram](https://blog.scrappey.com/blog/residential-proxies-for-instagram-unlock-data-avoid-blocks)
- [Anti-detect browser benchmark 2026 (Patchright, nodriver, Camoufox)](https://ianlpaterson.com/blog/anti-detect-browser-benchmark-patchright-nodriver-curl-cffi/)
- [What is Camoufox](https://www.centinelanalytica.com/blog/what-is-camoufox)
- [Scrapling stealthy fetcher docs](https://huggingface.co/spaces/lenson78/Scrapling/blob/main/docs/fetching/stealthy.md)
- [ZenRows: stealth browser tools](https://www.zenrows.com/blog/top-stealth-browser-tools)
