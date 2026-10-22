# Stage 5c-2 Style A Materials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every workflow gathers style A's materials and Studio places them:
- a post card for every main;
- the creator's profile page;
- the creator's on-topic videos and photos.

**Architecture:** The work extends existing paths and adds no new service.
- **Cards:** the card croppers (`card_browser.py`, `browser.py`, `threads_service.py`) also
  crop the post card for video posts, measure its media box, and crop the profile page.
- **Discovery:** profile discovery also returns photo posts.
- **Footage:** the footage builder adds creator candidates and runs them through its gates, with
  a three-step relevance check for weak captions.
- **Content Set:** assembly carries everything as optional fields.
- **Studio:** the 5c-1 import path places the new roles.

**Tech Stack:** Python 3.12, Pydantic v2, Scrapling/Playwright page actions, PostgreSQL (psycopg),
Alembic, React/TypeScript (gate labels only), Remotion composition unchanged.

**Spec:** `docs/superpowers/specs/2026-10-22-stage5c2-style-a-materials-design.md`

## Global Constraints

- **Content Set schema:** stays version 1. Every new field is optional, with a default.
  - The 23 stored Content Sets must still validate.
  - `Main.card` keeps its meaning (the card of a text-only post).
- **Cards are real crops or absent, never synthetic.**
  - A missing material degrades to absent and logs `warn` with counts only: no URL, handle or
    text.
- **Tests are offline only:** fakes and recorded fixtures. No live request; no Instagram private
  API.
- **Creator footage limits:**
  - `MAX_FOOTAGE` stays 6.
  - At most 2 creator clips (`PER_QUERY = 2` on the `creator:@<handle>` query).
  - Search fills the rest.
- **Creator photos:** at most 3, held `SLIDE_SECONDS` (3.0) each, fit `contain`.
- **Creator listing:** the 24 most recent posts (`CREATOR_LISTING = 24`), using the existing
  `ProfileDiscoverer` access policy (`fallback` leases an account on a thin or blocked listing).
- **Relevance:**
  - `story_min` stays as configured (`THOTH_FOOTAGE_STORY_MIN`, 0.36);
  - a weak caption has under 15 characters of body (`WEAK_BODY = 15`) once `#tags` and
    `@mentions` are removed;
  - undecided posts are kept only within 7 days (`CLOSE_DAYS = 7`), at most 3
    (`CLOSE_CAP = 3`), nearest first.
- **Post card:**
  - X, Threads and Instagram always crop it, now also for video posts;
  - TikTok crops the author header plus caption, with no media box;
  - YouTube crops none;
  - a text-only main (`main.kind == "card"`) gets no separate post-card overlay.
- **Profile page:** header plus the first grid rows, for TikTok, Instagram, X and YouTube.
  Threads gets none.
- **Studio:**
  - the post card is an overlay at 0 s for `reading_seconds(main.description)`;
  - the profile card starts at `max(PROFILE_AT, post end + CARD_GAP)`;
  - scene order: main, profile page, creator footage, creator photos, search footage, then
    plain comments.
- **Live gates:** Task 0 (page recon) and Task 12 (crop check) are live and run only on the
  operator's authorisation, each as its own gate. Every other task is offline.
- **No silent gaps:** a missing post card or profile page is shown in the Studio import gate,
  never only logged.
- **Commits:** one `git commit -m "<subject>"`, with no body and no trailer.
- **Repository text:** in English.
- **Tests:**
  - Python via WSL: `wsl -e bash -lc 'cd /mnt/d/thoth-tmp/wt-5c2 && make test T=<path>'`;
  - Postgres: `bash scripts/dev/pytest-postgres.sh <path>`;
  - dashboard: `bun test` in `dashboard/`.

## Review Focus

1. **A creator with zero posts, a private account or a blocked listing.** The workflow continues
   with search footage only, and `footage_status` is unaffected. Covered in Task 8:
   `test_creator_listing_failure_keeps_search_footage`.
2. **The main has no `published_at`.** Undecided creator posts cannot be judged by closeness and
   are all rejected as `story`, never kept. Covered in Task 6:
   `test_no_main_date_keeps_no_undecided`.
3. **A creator post that is the main itself** (same URL, or the same video id under another URL
   form). It never becomes footage. Covered in Task 8: `test_the_main_is_never_creator_footage`.
4. **A stored Content Set from before 5c-2** opens in Studio unchanged:
   - no post card, so the profile card stays at 3 s;
   - no profile page scene.

   Covered in Task 10: `test_an_old_content_set_places_as_before`.
5. **A post card whose media box falls outside the card** (bad bounding box). It is dropped to
   `None`; the card is kept. Covered in Task 2: `test_a_media_box_outside_the_card_is_dropped`.

---

### Task 0: Live page recon and recorded DOM fixtures (operator gate)

Runs only after the operator authorises it as its own gate. Without that authorisation, Tasks
2-4 use selectors from the existing replay fixtures and are marked unproven in the ledger.

**Files:**
- Create: `python/tests/acquisition/pages/<platform>-post.html` and
  `<platform>-profile.html` for TikTok, Instagram, X and YouTube (Threads: post only). These are
  `page.content()` dumps of one public post page and its creator's profile page.
- Create: `python/tests/acquisition/test_live_page_selectors.py`

**Interfaces:**
- Produces: one recorded DOM per page that Tasks 2-4 build their selectors against. Each
  selector constant is tested against it.

**How to capture:**
- Use the existing headless stack and access policy: Camoufox for Instagram, leased accounts
  with their proxies when signed-out pages are thin. Never use the Instagram private API.
- Make one request per page, paced at least 30 s apart.
- Use public posts the operator names, or one post from the deployed Content Sets per platform.
- Strip cookies, tokens and `<script>` bodies from the dumps before they are written. Keep only
  the DOM structure and its text.

- [ ] **Step 1: Capture the dumps** (live, authorised) and inspect each for the elements the
  spec names:
  - the post element and its media element;
  - the TikTok author header and description;
  - the profile header and the first grid rows.
- [ ] **Step 2: Write `test_live_page_selectors.py`.** Load each dump with Playwright
  `page.set_content` and assert that every selector constant matches exactly one element
  (`count() == 1`), or at least two grid items for the grid. Before Tasks 2-4 add the constants,
  this test fails on import.
- [ ] **Step 3: Commit the dumps and the test** (the test is skipped until its constants exist).
  `git commit -m "test(acquisition): recorded pages for style A selectors"`

### Task 1: Models for the new materials

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (`CardArtifact`, `SourceReport`,
  `TikTokSourceReport`)
- Modify: `python/src/thoth_control_plane/assembly/models.py` (`Main`, `Footage`, `ContentSet`)
- Test: `python/tests/acquisition/test_models.py`, `python/tests/assembly/test_models.py`

**Interfaces:**
- Produces:
  - `MediaBox(StrictModel)` in `acquisition/models.py`. Fields `x, y, w, h: float`, each in
    [0, 1], with `x + w <= 1` and `y + h <= 1`.
  - `CardArtifact.media_box: MediaBox | None = None`.
  - `SourceReport.profile_page: CardArtifact | None = None`.
  - `TikTokSourceReport.post_card: CardArtifact | None = None` and
    `TikTokSourceReport.profile_page: CardArtifact | None = None`, both refused on
    `schema_version == 1`, like comments.
  - In `assembly/models.py`, `PostCardRef(MediaRef)` adding `media_box: MediaBox | None = None`
    (MediaBox imported from acquisition).
  - `Main.post_card: PostCardRef | None = None`.
  - `Main.profile_page: MediaRef | None = None`.
  - `Footage.source: Literal["search", "carousel", "creator"]`.
  - `Photo(StrictModel)` with these fields:
    - `source: Literal["creator"]`, `url: HttpUrl`;
    - `platform: Literal["tiktok", "instagram", "x"]`;
    - `owner_handle: TikTokHandle`, `caption: str` (max 2,000);
    - `image: MediaRef`, which must not be `video/mp4`;
    - `story_score: Fraction`.
  - `ContentSet.photos: list[Photo] = Field(default_factory=list, max_length=MAX_PHOTOS)`, with
    `MAX_PHOTOS = 3`. Photo URLs must be unique and never the main's.

- [ ] **Step 1: Write the failing tests**

```python
def test_media_box_stays_inside_the_card():
    assert MediaBox(x=0.1, y=0.2, w=0.8, h=0.5).w == 0.8
    with pytest.raises(ValidationError):
        MediaBox(x=0.5, y=0.0, w=0.6, h=0.5)

def test_v1_tiktok_report_refuses_new_cards():
    with pytest.raises(ValidationError):
        TikTokSourceReport.model_validate({**V1_REPORT, "post_card": CARD})

def test_old_content_sets_still_validate():
    # the 5c-1 shape: the existing content_set() builder, none of the new keys
    data = content_set()
    assert "photos" not in data and "post_card" not in data["main"]
    assert ContentSet.model_validate(data).photos == []

def test_photos_are_capped_unique_and_never_the_main():
    with pytest.raises(ValidationError):
        ContentSet.model_validate({**SET, "photos": [PHOTO] * 4})
    with pytest.raises(ValidationError):
        ContentSet.model_validate({**SET, "photos": [{**PHOTO, "url": SET["main"]["url"]}]})
```

Use the existing builders in those test files (`content_set()` in `tests/assembly/test_models.py`) for `V1_REPORT`, `CARD` and `SET`.
`PHOTO` is a new valid photo dict built from them.

- [ ] **Step 2: Run them.** Run `make test T=tests/acquisition/test_models.py tests/assembly/test_models.py`.
  Expected: FAIL, with `MediaBox` undefined.
- [ ] **Step 3: Implement the models above.**
- [ ] **Step 4: Run them again.** Same command; expected: PASS. Then run the full suite and export
  OpenAPI (`bash D:/thoth-tmp/export-openapi.sh D:/thoth-tmp/wt-5c2`). If the generated
  `dashboard/src/api/generated/control-plane.ts` changed, regenerate it, and add any newly
  required fields to the TypeScript fixtures.
- [ ] **Step 5: Commit.** `git commit -m "feat(content): models for style A materials"`

### Task 2: Card browser crops the post card always, its media box, and the profile page

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/card_browser.py`
- Modify: `python/src/thoth_control_plane/acquisition/x_service.py`, `instagram_service.py`,
  `youtube_service.py` (layouts, `want_post`, the `persist_cards` callers)
- Modify: `python/tests/acquisition/fakes.py` (`FakeLocator.bounding_box`)
- Test: `python/tests/acquisition/test_card_browser.py`, `test_x_service.py`,
  `test_instagram_service.py`, `test_youtube_service.py`

**Interfaces:**
- Consumes: `MediaBox`, `CardArtifact.media_box` and `SourceReport.profile_page` (Task 1).
- Produces:
  - `CardLayout` gains `media_selector: str | None = None` (relative to the post element) and
    `page_selector: str | None = None` (the profile page's header plus grid region).
  - `Cards` gains `post_media_box: MediaBox | None` and `profile_page_png: bytes | None`.
  - `media_box(card: dict, media: dict) -> MediaBox | None`, a pure function. The arguments are
    Playwright `bounding_box()` dicts. It returns `None` when the media is outside the card or
    has zero size.
  - `persist_cards(...) -> PersistedCards`, a frozen dataclass with fields `post_card`,
    `comments`, `profile_card` and `profile_page`. It replaces the tuple; update every caller.
    It saves `profile-page.png` and puts `media_box` on the post card.
  - X and Instagram call `cards(..., want_post=True, ...)` always. YouTube keeps
    `want_post=False` but sets `page_selector`.
  - Each platform's `SourceReport` gets `profile_page`.

- [ ] **Step 1: Write the failing tests**

```python
def test_media_box_is_relative_to_the_card():
    box = media_box({"x": 100, "y": 200, "width": 400, "height": 600},
                    {"x": 120, "y": 350, "width": 360, "height": 300})
    assert box == MediaBox(x=0.05, y=0.25, w=0.9, h=0.5)

def test_a_media_box_outside_the_card_is_dropped():
    assert media_box({"x": 0, "y": 0, "width": 100, "height": 100},
                     {"x": 50, "y": 50, "width": 100, "height": 100}) is None

async def test_profile_page_and_post_media_follow_the_layout():
    # LAYOUT with media_selector=".media", page_selector=".page"; the fakes report bounding boxes
    cards = await browser.cards(POST, PROFILE, want_post=True, targets=[])
    assert cards.post_media_box is not None
    assert cards.profile_page_png is not None
    assert profile_page.shots == [".profile", ".page"]

def test_x_crops_the_post_card_for_a_video_post():  # in test_x_service.py
    # a video post: the fake card browser is called with want_post=True
    ...
```

The last test asserts the recorded `want_post` argument of the fake `cards` call. Write the same
test for Instagram. In `test_youtube_service.py`, assert that the profile page is persisted as
`reports/<wf>/cards/profile-page.png`.

- [ ] **Step 2: Run them.** Run
  `make test T=tests/acquisition/test_card_browser.py tests/acquisition/test_x_service.py tests/acquisition/test_instagram_service.py tests/acquisition/test_youtube_service.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `_on_post`: after the post crop, read the bounding box of the post element and of
    `post_selector + " " + media_selector`, and store `media_box(...)`. A failure leaves `None`.
  - `_on_profile`: crop `page_selector` after the profile card, when it is set.
  - Choose `media_selector` and `page_selector` per platform from the recorded replay fixtures
    (`tests/acquisition/*_replay*`). Name each in a comment with the element it targets.
  - `log_outcome` adds `profile_page=<bool>` to the info line, and adds `page` to `missing` when
    a page was asked for and is absent.
- [ ] **Step 4: Run them again.** Same command; expected: PASS. Then run
  `make test T=tests/acquisition`.
- [ ] **Step 5: Commit.** `git commit -m "feat(acquisition): post card for video posts and the profile page"`

### Task 3: Threads post card always, with its media box

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/threads_service.py` (`_crop_post_card`,
  `_persist_post_card`)
- Test: `python/tests/acquisition/test_threads_service.py`

**Interfaces:**
- Consumes: `media_box` (Task 2) and `CardArtifact.media_box` (Task 1).
- Produces: the Threads `SourceReport.post_card` for every post, with `media_box` when the post
  has media. `profile_page` stays `None`.

- [ ] **Step 1: Write the failing test** `test_threads_crops_a_video_post_with_its_media_box`.
  The fake page holds a post with a video. Assert that the report's `post_card.media_box` is not
  `None` and that the card PNG exists.
- [ ] **Step 2: Run it.** Run `make test T=tests/acquisition/test_threads_service.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement.** Remove the condition that crops only media-less posts. Measure the
  media element inside the pressable container; the selector comes from the replay fixture.
- [ ] **Step 4: Run it again.** Same command; expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(threads): post card for every post"`

### Task 4: TikTok post card (header plus caption) and profile page

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/browser.py` (`_Visit`, `_visit_action`,
  `_crop_profile_card`, `extract_browser_snapshot`, and new JS constants)
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (`BrowserSnapshot` gains
  `post_card_png` and `profile_page_png`, excluded from dumps like `profile_card_png`)
- Modify: `python/src/thoth_control_plane/acquisition/service.py` (persist both to
  `cards/post.png` and `cards/profile-page.png` on the TikTok report)
- Test: `python/tests/acquisition/test_browser.py`, `python/tests/acquisition/test_service.py`

**Interfaces:**
- Consumes: `TikTokSourceReport.post_card` and `.profile_page` (Task 1).
- Produces: TikTok reports with `post_card` (no `media_box`) and `profile_page`.

- [ ] **Step 1: Write the failing tests.**
  - `test_visit_crops_the_post_header_and_caption`: the fake page answers `POST_CARD_JS` with a
    rectangle. Assert that the visit holds `post_card` bytes.
  - `test_profile_tab_also_crops_the_page`: after the profile card, `PROFILE_PAGE_JS` returns a
    rectangle that covers the header plus the first grid rows. Assert `profile_page` bytes.
  - `test_service_persists_tiktok_post_card_and_page`: assert both artifacts are on the report.
- [ ] **Step 2: Run them.** Run
  `make test T=tests/acquisition/test_browser.py tests/acquisition/test_service.py`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `POST_CARD_JS` returns the union rectangle of the author header (`data-e2e` author avatar and
    name) and the description container.
  - `PROFILE_PAGE_JS` returns the union of the profile header and the first two rows of
    `[data-e2e="user-post-item"]`.
  - Both are screenshot with `clip=rect`, in the same best-effort style as
    `_crop_profile_card`.
  - Choose `data-e2e` keys from the existing recorded TikTok fixtures.
- [ ] **Step 4: Run them again.** Same command; expected: PASS. Then run
  `make test T=tests/acquisition`.
- [ ] **Step 5: Commit.** `git commit -m "feat(tiktok): post card and profile page crops"`

### Task 5: Profile discovery returns photo posts

**Files:**
- Modify: `python/src/thoth_control_plane/acquisition/models.py` (`DiscoveredPhoto`,
  `DiscoveryResult.photos`)
- Modify: `acquisition/discovery.py` (TikTok `imagePost`), `instagram_discovery.py`
  (`GraphImage` / carousel nodes), `x_discovery.py` (tweets with photos)
- Modify: `python/src/thoth_control_plane/attribution/adapters/discovery.py`
  (`ProfileDiscoverer.creator`)
- Test: `python/tests/acquisition/test_discovery.py`, `test_instagram_discovery.py`,
  `test_x_discovery.py`, `python/tests/attribution/test_discovery.py` (the existing
  `ProfileDiscoverer` tests)

**Interfaces:**
- Produces:
  - `DiscoveredPhoto(StrictModel)`, with fields:
    - `post_id`, `owner_handle`, `canonical_url`, `caption`, `published_at`, `hashtags`;
    - `image_urls: list[HttpUrl]` (1 to 20).
  - `DiscoveryResult.photos: list[DiscoveredPhoto] = []`.
    - Photo posts that were previously only counted in `drops.photo_posts` are now parsed.
    - The count stays for photos that fail validation.
  - `CreatorListing` (frozen dataclass), with `videos: list[DiscoveredVideo]` and
    `photos: list[DiscoveredPhoto]`.
  - `ProfileDiscoverer.creator(platform: Platform, handle: str, limit: int) -> CreatorListing`.
    It is the same access flow as `list`, but keeps photos too. YouTube returns no photos.

- [ ] **Step 1: Write the failing tests.** In each platform's discovery test, use the recorded
  page fixture that already contains a photo post (the one counted in `drops.photo_posts`), and
  assert:

```python
assert [photo.post_id for photo in result.photos] == [PHOTO_ID]
assert result.photos[0].image_urls
```

  Also write `test_creator_listing_keeps_photos`, using the fake factories in the
  `ProfileDiscoverer` tests.
- [ ] **Step 2: Run them.** Run
  `make test T=tests/acquisition/test_discovery.py tests/acquisition/test_instagram_discovery.py tests/acquisition/test_x_discovery.py tests/attribution`.
  Expected: FAIL.
- [ ] **Step 3: Implement the parsing and `creator`.** Existing callers of `list` and `discover`
  are unchanged.
- [ ] **Step 4: Run them again.** Same command; expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(discovery): photo posts in profile listings"`

### Task 6: The creator relevance rules (pure)

**Files:**
- Create: `python/src/thoth_control_plane/footage/creator.py`
- Test: `python/tests/footage/test_creator.py`

**Interfaces:**
- Produces, with the constants `WEAK_BODY = 15`, `CLOSE_DAYS = 7`, `CLOSE_CAP = 3`,
  `CREATOR_LISTING = 24`, `MAX_PHOTOS = 3`:
  - `creator_query(handle: str) -> str`, which returns `f"creator:@{handle}"`;
  - `enriched_text(caption: str, hashtags: Sequence[str]) -> str`, the caption plus each hashtag
    split into words (camelCase, digits and underscores);
  - `body_length(caption: str) -> int`, the stripped length once `#tags` and `@mentions` are
    removed;
  - `verdict(score: float, caption: str, story_min: float) -> Literal["pass", "reject",
    "undecided"]`;
  - `closest(undecided: Sequence[T], published: Callable[[T], datetime | None], main:
    datetime | None) -> tuple[list[T], list[T]]`, which returns (kept, dropped).

- [ ] **Step 1: Write the failing tests**

```python
def test_hashtags_read_as_words():
    assert enriched_text("", ["BBMLangka", "banjir_bali2026"]) == "BBM Langka banjir bali 2026"

def test_weak_caption_is_undecided_not_rejected():
    assert verdict(0.10, "#fyp #viral @someone", 0.36) == "undecided"
    assert verdict(0.10, "Liburan ke pantai bersama keluarga", 0.36) == "reject"
    assert verdict(0.40, "", 0.36) == "pass"

def test_closest_keeps_three_within_seven_days_nearest_first():
    main = datetime(2026, 10, 10, tzinfo=UTC)
    posts = [main + timedelta(days=d) for d in (-8, -1, 2, 3, 6, 0.5)]
    kept, dropped = closest(posts, lambda p: p, main)
    assert kept == [main + timedelta(days=0.5), main - timedelta(days=1), main + timedelta(days=2)]
    assert main - timedelta(days=8) in dropped

def test_no_main_date_keeps_no_undecided():
    kept, dropped = closest([1, 2], lambda p: None, None)
    assert (kept, dropped) == ([], [1, 2])
```

- [ ] **Step 2: Run them.** Run `make test T=tests/footage/test_creator.py`. Expected: FAIL
  (module missing).
- [ ] **Step 3: Implement.** A post with no `published_at` is dropped by `closest`.
- [ ] **Step 4: Run them again.** Same command; expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): creator relevance rules"`

### Task 7: Footage store accepts creator videos and photos

**Files:**
- Create: `python/migrations/editor/0018_footage_creator.sql`,
  `python/migrations/editor/alembic/versions/0018_footage_creator.py` (revision `"0018"`, down
  `"0017"`, same shape as 0017)
- Modify: `python/src/thoth_control_plane/footage/models.py` (`NewCandidate` and
  `CandidateView` gain `media_kind: str = "video"`)
- Modify: `python/src/thoth_control_plane/infrastructure/footage_store.py` (write and read
  `media_kind`; `admitted(workflow, media_kind="video")`)
- Modify: the migration-count assertions in the editor migration tests (counts +1, like 0017)
- Test: `python/tests/footage/test_store.py` (runs on PostgreSQL through `scripts/dev/pytest-postgres.sh`)

**Interfaces:**
- Produces:
  - The SQL:
    ```sql
    ALTER TABLE footage_candidates DROP CONSTRAINT footage_candidates_source_check,
        ADD CONSTRAINT footage_candidates_source_check
            CHECK (source IN ('search', 'carousel', 'creator')),
        ADD COLUMN media_kind TEXT NOT NULL DEFAULT 'video'
            CHECK (media_kind IN ('video', 'image'));
    ```
    Confirm the constraint name with `\d footage_candidates` on a migrated database first.
  - `FootageState.admitted(workflow_id, media_kind="video")`, which returns admitted candidates
    of that kind only.

- [ ] **Step 1: Write the failing test** `test_creator_photo_candidates_round_trip`. Add one
  `source="creator", media_kind="image"` candidate, admit it, and assert that
  `admitted(wf, "image")` returns it while `admitted(wf)` does not.
- [ ] **Step 2: Run it.** Run `bash scripts/dev/pytest-postgres.sh <that test>`. Expected: FAIL
  (check constraint).
- [ ] **Step 3: Implement the migration and the store.**
- [ ] **Step 4: Run it again.** Same command; expected: PASS. Then run the migration tests.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): store creator videos and photos"`

### Task 8: The footage builder adds creator videos and photos

**Files:**
- Modify: `python/src/thoth_control_plane/footage/ports.py`:
  - `CreatorPort` with `async listing(platform, handle, limit) -> CreatorListing | None`
    (`None` means unavailable);
  - `PhotoFetcher` with `async fetch(url: str, target: Path) -> Path`.
- Modify: `python/src/thoth_control_plane/footage/service.py`. `FootagePorts` gains
  `creator: CreatorPort | None = None` and `photos: PhotoFetcher | None = None`. `_build` adds
  the creator step; add `_check_photos`.
- Modify: `python/src/thoth_control_plane/footage/models.py` (`FootageResult.photos: int = 0`)
- Create: `python/src/thoth_control_plane/footage/adapters/photos.py`
  (`HttpPhotoFetcher`: httpx with a 10 MB cap, Pillow verify, PNG or JPEG only)
- Modify: `python/src/thoth_control_plane/activities/footage.py` (wire
  `creator=ProfileDiscoverer(DEFAULT_FACTORIES, leases=leases)` behind a small adapter, and
  `photos=HttpPhotoFetcher()`)
- Test: `python/tests/footage/test_service.py`, `python/tests/footage/test_photos.py`

**Interfaces:**
- Consumes: `ProfileDiscoverer.creator` (Task 5), `footage/creator.py` (Task 6) and
  `media_kind` (Task 7).
- Produces: admitted creator video candidates (`source="creator"`,
  `query=creator_query(handle)`) and admitted image candidates. For both:
  - `visual` is the run's footage objects' visuals joined with "; ", cut to 300 characters;
  - `story_score` is set;
  - `owner_handle` is the main's.

**Behaviour:**
- **When:** after `_gate` for search hits, when `self._ports.creator` is set and the main
  platform is TikTok, Instagram, X or YouTube.
- **Listing:** list the creator once, with the main owner and `CREATOR_LISTING`.
- **Gating:** run every post through `text_gate`, which already excludes the main's URLs and id.
- **Scoring:** score `enriched_text(caption, hashtags)` against the story with the existing
  embedder. Then:
  - `pass`: pending with its score;
  - `reject`: rejected as `story`;
  - `undecided`: kept by `closest(...)`, pending with its score; the rest rejected as `story`.
- **Videos** join `_check_all` under their query. `select_batch`'s per-query cap of 2 gives the
  2-of-6 split.
- **Photos:**
  - Up to 3 admitted, checked in `_check_photos` after the clips.
  - Each one: fetch the first image to the scratch, take one frame, run the vision judge, then
    `admit` with `media_kind="image"`.
  - A photo's location is
    `reports/<wf>/footage/photo-<post_id>.<ext>`, published through `inputs.publish` like the
    clips.
- **Logging:** log one info line,
  `footage creator listed=%d passed=%d undecided=%d kept_close=%d admitted_videos=%d admitted_photos=%d`.
- **When search is unavailable:**
  - search failing completely no longer ends the run early when creator candidates exist;
  - the run status stays `unavailable` only when search failed and the creator yielded nothing.

- [ ] **Step 1: Write the failing tests** in `test_service.py` with the existing fakes plus a
  `FakeCreator`:
  - `test_creator_videos_take_at_most_two_slots`: 4 passing creator videos and 8 search hits.
    The admitted creator count is 2 and the total is 6.
  - `test_weak_caption_creator_video_reaches_the_vision_judge`: a `#fyp` caption posted 1 day
    from the main is judged; the judge's `yes` admits it.
  - `test_creator_listing_failure_keeps_search_footage`: the creator returns `None`. The search
    footage is admitted as before, with status `ok`.
  - `test_the_main_is_never_creator_footage`: the listing contains the main's own post. It is
    rejected as `main`.
  - `test_creator_photos_are_capped_at_three`: 5 passing photos give 3 admitted images.

  In `test_photos.py`:
  - `test_photo_fetch_refuses_non_images`;
  - `test_photo_fetch_caps_size`.
- [ ] **Step 2: Run them.** Run `make test T=tests/footage`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them again.** Same command; expected: PASS, with
  `test_calibration_golden.py` unchanged.
- [ ] **Step 5: Commit.** `git commit -m "feat(footage): creator videos and photos"`

### Task 9: Assembly carries the post card, profile page, creator footage and photos

**Files:**
- Modify: `python/src/thoth_control_plane/assembly/service.py`:
  - `_main_fields` sets `post_card` (when the main kind is not `card`) and `profile_page`;
  - `_footage_item` keeps `source`;
  - a new `_photos(workflow_id)` reads `admitted(wf, "image")`.
- Modify: `python/src/thoth_control_plane/assembly/comments.py` (`card_ref` carries `media_box`
  into `PostCardRef`; add `post_card_ref`)
- Test: `python/tests/assembly/test_service.py`

**Interfaces:**
- Consumes: Tasks 1, 7 and 8.
- Produces: Content Sets with `main.post_card`, `main.profile_page`, creator `footage` and
  `photos`.

- [ ] **Step 1: Write the failing tests.**
  - `test_video_main_carries_its_post_card_and_media_box`.
  - `test_card_main_has_no_separate_post_card`: `main.kind == "card"` gives
    `main.post_card is None`.
  - `test_creator_footage_and_photos_reach_the_content_set`.
  - `test_photos_missing_store_degrades_to_none`.
- [ ] **Step 2: Run them.** Run `make test T=tests/assembly`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them again.** Same command; expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat(assembly): style A materials in the Content Set"`

### Task 10: Studio places the new roles

**Files:**
- Modify: `python/src/thoth_control_plane/domain/studio_imports.py`:
  - `SourceRole` adds `post_card`, `profile_page`, `creator_footage`, `creator_photo`;
  - `ROLE_ORDER` becomes main, main_footage, slide, post_card, profile_page, creator_footage,
    creator_photo, footage, profile_card, comment_card, comment;
  - `OVERLAY_ROLES` adds `post_card`;
  - `SINGLE_ROLES` adds `post_card` and `profile_page`.
- Modify: `python/src/thoth_control_plane/domain/studio_layout.py`:
  - `post_card_slot(scene_seconds: float, reading: float) -> tuple[float, float]`, returning
    `(0.0, min(reading, scene_seconds))`;
  - `profile_slot(scene_seconds, *, not_before=0.0)`, which starts at
    `max(PROFILE_AT, not_before)`, clamped as today.
- Modify: `python/src/thoth_control_plane/assembly/studio.py`:
  - project `post_card` (reading = `reading_seconds(main.description)`);
  - project `profile_page` (title `@<owner>`);
  - project footage with `source == "creator"` as `creator_footage`, the rest as `footage`;
  - project photos as `creator_photo`.
- Modify: `python/src/thoth_control_plane/infrastructure/studio_import_repository.py`:
  - `_overlay` handles `post_card` through `post_card_slot` at `card_position`;
  - `profile_card` uses `not_before = post end + CARD_GAP` when a post card is in the
    inventory;
  - the beat's `not_before` follows the profile slot as before;
  - `_attached` gives `profile_page` and `creator_photo` scenes `SLIDE_SECONDS` and fit
    `contain`.
- Modify: `dashboard/src/features/studio/StudioImportGate.tsx` (`ROLE_LABELS`: "Post card",
  "Profile page", "Creator footage", "Creator photo")
- A material the main's platform should have but the Content Set lacks becomes visible in the
  gate, never only in a log:
  - post card, missing on X, Threads, Instagram or TikTok, unless the main kind is `card`;
  - profile page, missing on TikTok, Instagram, X or YouTube.

  The projection reports it through the existing `built.report(...)` as an unsupported field:
  `field="main.post_card"` or `"main.profile_page"`, with reason `"Not captured: post card"` or
  `"Not captured: profile page"`.
- Regenerate OpenAPI and the TypeScript types (export script).
- Test:
  - `python/tests/domain/test_studio_layout.py`;
  - `python/tests/assembly/test_studio_projection.py`;
  - `python/tests/infrastructure/test_workflow_studio_postgres.py` (Postgres; extend
    `seed_media`);
  - `dashboard/src/features/studio/StudioImportGate.test.tsx`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_profile_card_follows_the_post_card():
    post = post_card_slot(40.0, 5.2)
    assert post == (0.0, 5.2)
    assert profile_slot(40.0, not_before=sum(post) + CARD_GAP)[0] == pytest.approx(5.7)

def test_profile_card_keeps_three_seconds_without_a_post_card():
    assert profile_slot(40.0)[0] == 3.0
```

  In the projection tests:
  - `test_projection_orders_the_new_roles`: the scene ids are main `scene_001`, profile page
    `scene_002`, creator footage next, creator photos next, then search footage.
  - `test_an_old_content_set_places_as_before`: a 5c-1 Content Set fixture gives the same items
    as before.

  In the Postgres integration:
  - `test_post_card_then_profile_card_then_beat`;
  - `test_profile_page_and_photos_hold_three_seconds`.

  In the gate test, the four new labels render.

  Also add `test_a_missing_post_card_is_reported_in_the_gate` (projection): an X main without
  `post_card` yields the unsupported field `main.post_card` with reason
  "Not captured: post card". A YouTube main yields none.
- [ ] **Step 2: Run them.** Run `make test T=tests/domain tests/assembly`, the Postgres test and
  `bun test src/features/studio`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them again.** Same commands; expected: PASS. Then run the full Python suite,
  `bun test`, `bunx tsc --noEmit -p tsconfig.app.json` and `bun run build`.
- [ ] **Step 5: Commit.** `git commit -m "feat(studio): place style A materials"`

### Task 11: Stack smoke, docs, checkpoint

**Files:**
- Modify: `docker/test-renderer-offline.sh` (keep LF):
  - `workflow_opens_in_studio` seeds a post card, a profile page, one creator clip and one
    creator photo;
  - it asserts a `track_b_roll` post card at frame 0;
  - it asserts profile-page and creator scenes in the order the spec gives.
- Modify: `CHANGELOG.md` (entry with verification and **Next steps**), `docs/ROADMAP.md` (row 4),
  `docs/python-control-plane.md` (the footage and Content Set rows)
- Test: the stack smoke on images built from the branch.

- [ ] **Step 1: Extend the smoke assertions first.** Run it on the 5c-1 images (`thoth:5c1` and
  the matching renderer and web). Expected: `workflow_opens_in_studio=false`.
- [ ] **Step 2: Build the branch images.**
  `docker build -f Dockerfile -t thoth:5c2 .`, and likewise for renderer and web.
- [ ] **Step 3: Run the smoke again.** Run
  `make smoke-renderer IMAGE=thoth:5c2 RENDERER_IMAGE=thoth-renderer:5c2 WEB_IMAGE=thoth-web:5c2`.
  Expected: every verdict true.
- [ ] **Step 4: Write the docs.** Include the Next steps: the gates (push/PR, CI, merge, deploy,
  an optional live capture per platform) and roadmap item 6.
- [ ] **Step 5: Commit.** `git commit -m "docs: Stage 5c-2 style A materials"`

### Task 12: Live crop check per platform (operator gate, before deploy)

Runs only after the operator authorises it as its own gate. It is the proof that the new crops
work on real pages: the offline tests prove only the code paths and the recorded DOM.

**Files:**
- Create: `D:/thoth-tmp/research/5c2/live-check/` (outside the repository): the crops and a
  summary.
- Modify: `CHANGELOG.md` (the result).

- [ ] **Step 1: Run one acquisition per platform** (TikTok, Instagram, X, Threads, YouTube) on
  the `thoth:5c2` image, against the public posts from Task 0, through the normal acquisition
  activity with its access policy. Pace the runs at least 60 s apart.
- [ ] **Step 2: Collect evidence.** For each run, collect:
  - `post.png`, `profile-page.png` and the post card's `media_box`;
  - the `cards missing` warning line, if any.

  Draw the `media_box` onto a copy of `post.png`, so it can be checked by eye.
- [ ] **Step 3: Show the operator** the crops and the boxed copies. Expected:
  - each platform has the materials the spec gives it;
  - no `cards missing` line for them;
  - the box sits on the post's media.
- [ ] **Step 4: Fix any wrong selector.** Fix it against the recorded DOM (Task 0), add the
  failing assertion to `test_live_page_selectors.py` first, re-run that platform once, then
  commit `fix(acquisition): <platform> <material> selector`.
- [ ] **Step 5: Record the outcome** in the CHANGELOG entry and the checkpoint.
