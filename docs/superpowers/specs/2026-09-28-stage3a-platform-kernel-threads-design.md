# Stage 3a: Platform-Neutral Acquisition Kernel and Threads

Status: design approved in chat on 2026-09-28; this written spec awaits operator review.

## 1. Context and scope

Stage 2 closed on 2026-09-28 with a TikTok-only Python acquisition kernel: headless
Scrapling, a TikWM fallback, an SSRF-safe materializer, real card crops, and
`TikTokSourceReport` schema v2. Stage 3 ports the remaining platform adapters and is split
into sub-projects (roadmap, operator decision 2026-09-28):

- 3a (this spec): a platform-neutral acquisition kernel with Threads as its first platform.
- 3b: Instagram. 3c: X. 3d: YouTube. Each gets its own spec.

Out of scope:

- Facebook and Reddit. The operator excluded them from Stage 3 and they are rejected as
  unsupported, never routed to legacy Scout (section 4).
- Threads replies and Threads discovery. Scout has neither, so parity does not need them.
- Any live test in the suite, any Rust change, and the Stage 5 content-set mapping.

## 2. Operator decisions (2026-09-28)

1. Decomposition into 3a-3d; Facebook and Reddit excluded.
2. Golden fixtures: one sanitized, read-only live capture per platform, authorized
   separately at capture time (ADR 0001 direction).
3. Method rule: each platform tries a plain Scrapling request (browser TLS impersonation,
   no browser) pushed as far as it goes, and the headless browser. If the request results
   match or beat headless, the platform uses the request method only. TikTok gets the same
   comparison after Stage 3.
4. Social card: the method is decided per capability; headless opens only when a card is
   needed.
5. Kernel approach A: a neutral SourceReport v3 plus an acquirer registry; TikTok writes
   v3. Approach B (a separate service per platform) is recorded as an escape hatch, used
   only if a platform truly needs one.
6. Facebook and Reddit are rejected directly as unsupported in every activity mode,
   including the `legacy_scout` rollback mode. There is no legacy fallback for them.
7. X and Threads posts are often text only. A text-only post is a first-class result and
   is never dropped; its special handling downstream belongs to Stage 5.
8. There is no runtime request-to-headless fallback. Adding one later, for example if
   live evidence shows intermittent request blocking, is a separate operator decision.

## 3. Architecture

### 3.1 Acquirer contract and registry

A new module `acquisition/registry.py` holds:

- `Acquirer` protocol: `platform: str`, `hosts: frozenset[str]`, and
  `async inspect(workflow_id, source_url, artifact_root) -> AcquisitionResult`.
- `platform_support(url) -> Literal["python", "legacy", "unsupported"]`, matching the URL
  hostname (lowercased, a leading `www.` or `m.` removed) against:
  - the registered acquirer hosts → `python`;
  - `UNSUPPORTED_HOSTS` = facebook.com, fb.com, fb.watch, reddit.com, redd.it, and their
    subdomains → `unsupported`;
  - anything else → `legacy` (unchanged behavior for platforms not yet ported).
- `acquirer_for(url)` returning the registered acquirer for a `python` URL.

Registered in 3a: TikTok (`ENTRY_HOSTS` in `acquisition/adapters/tiktok.py`, unchanged)
and Threads (threads.net, threads.com).

`safe_workflow_source` is unchanged; its platform label stays display metadata only.

### 3.2 SourceReport v3

`acquisition/models.py` gains a platform-neutral report:

- `SourceReport`: `schema_version: Literal[3]`, `workflow_id`, `source` (`platform`,
  `canonical_url`), `post`, `media`, `outcome`, `comments`, `post_card`, `profile_card`.
- `SourcePost`: `post_id` (platform-specific pattern, validated by the acquirer, stored as
  a safe string of 1-64 characters from `[A-Za-z0-9_-]`), `owner_handle` (same pattern as
  today), `text` (max 50,000 characters, default empty), `published_at`, `engagement`.
- `media`: 0 to 20 `MaterializedMedia` items, indexed 1..N in post order.
- `MaterializedMedia` is widened:
  - `kind`: `video` or `image`;
  - `media_type`: `video/mp4`, or `image/jpeg`, `image/png`, `image/webp`;
  - `index`: 1..20;
  - byte bounds per kind: video 10,000 B to 500 MiB (unchanged); image 1,000 B to 20 MiB.
- `post_card`: an optional `CardArtifact` holding a real crop of the post itself.
- A validator rejects a report whose `media` is empty and whose `post.text` is empty or
  whitespace. Text only (`media == []`, non-empty text) is valid and needs no extra marker.
- `TikTokSourceReport` (v1, v2) stays as-is so Stage 1 evidence and `tiktok_parity.py`
  keep reading it. TikTok's acquisition service writes v3 from 3a onward; its v3 report
  carries exactly one video, as today.

`AcquisitionResult` replaces `TikTokAcquisitionResult` as the activity-facing result
(`report: SourceReport | None`, `failure: AcquisitionFailure | None`, exactly one).
`AcquisitionFailure.code` extends today's set with `request_blocked`, `request_timeout`,
`request_incomplete`, `no_content`, and `invalid_source_url` (Threads; TikTok keeps
`invalid_tiktok_url`); `unsupported_platform` already exists.
`AcquisitionStrategy` gains `scrapling_request`.

### 3.3 Materializer

The materializer keeps its SSRF rules (public HTTPS, publicly routable host, at most 3
redirects, atomic write). It gains image support: the content is checked against its magic
bytes (JPEG `FF D8 FF`, PNG signature, WebP `RIFF....WEBP`) and the per-kind byte bounds
above. Video keeps the `ftyp` check.

### 3.4 Threads acquirer

`acquisition/adapters/threads.py` implements `Acquirer`:

- Two pure parsers, one per method, each producing a `SourcePost` plus media candidates:
  - request: parses the HTML or JSON a Scrapling `AsyncFetcher` request returns
    (`impersonate="chrome"`, stealthy headers, `follow_redirects="safe"`);
  - headless: parses the post response the page itself makes, captured in an
    `AsyncStealthySession` visit.
- Scout's Threads parser was never validated against a real capture (its own comment says
  so), so both parsers are written against the 3a live capture, not ported from Scout.
- A module constant records the chosen method for each capability (post, media, card)
  once section 6 decides it. Both parsers stay, because the comparison test in section 7
  replays them.
- The post card is captured only when the post has no video media (text-only or image
  posts). This matches the legacy decision that non-video posts get a real crop card.
  The card needs headless, so a video post decided for the request method never opens a
  browser. A card that cannot be cropped is absent and never fails acquisition, and it is
  never synthetic.
- Post id: the `/post/<code>` path segment, `[A-Za-z0-9_-]{1,64}`. Any other Threads URL
  shape fails as `invalid_source_url` (non-retryable, not fallback-eligible).

## 4. Data flow and routing

1. API intake: `WorkflowService.start` calls `platform_support`. `unsupported` raises
   `UnsupportedPlatform`, mapped in `api/app.py` to HTTP 422 with
   `{"detail": {"code": "unsupported_platform"}}`. No workflow is created.
2. The workflow's `_execute_source_activity` first applies the same check as a guard for
   workflows started directly on Temporal. `unsupported` ends the workflow with a
   non-retryable `unsupported_platform` failure in every activity mode, `legacy_scout`
   included, before any activity runs.
3. `python_tiktok_with_legacy_fallback` (the configured default): `python` platforms run
   the Python activity; `legacy` platforms (Instagram, X, YouTube until their
   sub-projects land) run legacy Scout as today.
4. `python` mode: `python` platforms run the Python activity; a `legacy` platform fails
   non-retryably with `unsupported_platform`. Today that mode sends every URL to the
   TikTok service, which fails a non-TikTok URL as `invalid_tiktok_url`.
5. `legacy_scout` rollback mode: every URL that passed the guard runs legacy Scout, as
   today.
6. The Python activity resolves `acquirer_for(url)` and calls `inspect`. The runner builds
   the shared browser, HTTP client, and materializer once per call and closes them.
7. Progress event stage names become `<platform>_<method>` (for example
   `threads_request`, `tiktok_headless`, `tiktok_cdn`). The existing TikTok names stay
   identical.

## 5. Error handling

- Fallback-eligible codes (`LEGACY_FALLBACK_ELIGIBLE_CODES`) add `request_blocked`,
  `request_timeout`, and `request_incomplete`, matching the `headless_*` codes: a Python
  attempt was made and legacy might still recover while it exists (until Stage 10).
- Not fallback-eligible: `unsupported_platform`, `invalid_source_url`, `no_content` (the
  post was parsed and holds neither text nor media), `artifact_persistence_failed`, and
  `acquisition_dependency_unavailable`.
- A failed card crop, a missing comment, or a missing optional field never fails
  acquisition; a missing required field (post id, owner handle) is `*_incomplete`.
- No raw diagnostic, URL, or provider body crosses into Temporal history; only enums,
  counts, and elapsed milliseconds do, as today.

## 6. Method comparison and golden fixtures

### 6.1 Live capture (operator authorization at capture time)

- One read-only anonymous session against three public Threads posts chosen at capture
  time: one video, one image or carousel, one text-only.
- Each post is fetched once per method: the request response body, and the headless
  visit's post responses plus the post card crop.
- A manual CLI `operations/threads_capture.py` does the capture. It is outside the suite
  and writes only under `D:/thoth-tmp/`. Raw captures are never committed or printed.

### 6.2 Comparison (offline)

Both parsers replay the raw capture. For each capability the comparison counts:

- post fields present: post id, owner, text, published_at, each engagement counter;
- media candidates found and media that pass the materializer's validation rules;
- blocked or captcha outcomes.

The request method wins a capability when it matches or beats headless on every count and
was not blocked. The card capability is always headless. The result is recorded as
restricted evidence (counts, keys, enums only) in `CHANGELOG.md` and the checkpoint, and
it sets the module constant in section 3.4.

### 6.3 Golden fixtures

- `operations/threads_fixture.py` sanitizes the capture, reusing the Stage 2 helpers:
  text pseudonymization (including stylized letters and combining marks), handles and ids
  replaced by stable pseudonyms, synthetic timestamps on a one-hour grid, and counters kept
  to two significant digits.
- The committed fixtures hold both methods' sanitized responses and the expected parser
  output for each post, and pass a leak check with 0 leaks. Card PNGs are not committed;
  tests use `png_fixtures.make_png`.

## 7. Testing (offline only)

The conftest `_offline_unless_live` guard is not changed. New or changed tests:

- `platform_support`: every registered host and alias, `www.`/`m.` prefixes, Facebook and
  Reddit hosts and subdomains, unknown hosts.
- API: 422 `unsupported_platform` for a Facebook and a Reddit URL; no gateway start.
- Workflow: the unsupported guard in all three modes, never reaching legacy; Threads runs
  Python in fallback mode; Instagram still runs legacy in fallback mode and fails as
  `unsupported_platform` in `python` mode; `request_*` failures fall back.
- SourceReport v3: text-only valid; empty text with no media rejected; 20 media accepted
  and 21 rejected; image bounds; v1 and v2 `TikTokSourceReport` still validate.
- Materializer: JPEG, PNG, and WebP accepted; a mismatched magic or out-of-bounds size
  rejected.
- TikTok service writes a v3 report with the same post, media, comments, and cards.
- Threads: both parsers replay the golden fixtures to the expected output exactly; the
  text-only fixture yields `media == []`; a method-decision test asserts the chosen method
  still matches or beats the other on the fixtures; the card is requested only for
  non-video posts.

Verification: WSL Python 3.12 full suite and ruff check and format. No Rust changes are
planned, so `build_cuda.bat` is not required unless Rust changes.

## 8. Success criteria

1. Threads URLs run the Python acquirer in the default mode and produce a valid v3 report,
   including text-only posts.
2. Facebook and Reddit URLs are rejected at intake with 422 and, if started directly, fail
   as `unsupported_platform` in every mode without touching legacy Scout.
3. TikTok behavior is unchanged apart from writing v3.
4. The Threads method decision is recorded with offline-reproducible evidence.
5. The full suite passes with no new failures and no live test.

## 9. Gates outside this spec

- The Threads live capture needs operator authorization at capture time.
- Push, deployment, and any live smoke stay operator gates; live smokes wait for the
  final acceptance (ADR 0001).
