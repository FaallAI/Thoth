# Stage 5c-2: Style A Materials from the Social Platforms

**Date:** 2026-10-22
**Status:** Agreed in conversation 2026-10-22; awaits operator review of this document.
**Roadmap:** item 4, Stage 5c, second half. 5c-1 (Studio: cards, slides, subtitle blur) was
deployed 2026-10-22 (PR #39, `thoth@cd52dcf6`).
**Builds on:** `2026-10-21-stage5c1-studio-cards-design.md`, the footage spec (2026-10-14), and
the source-account and profile-discovery work.

## 1. Intent

Editing styles will become templates. The operator chose the first one: **style A**, the story
explainer seen on IsseiNugroho's Shorts. The video tells a viral story with its evidence on
screen: the original post, the creator's page and other videos, photos, and comments.

Style A has two layers:

1. **The materials**, taken from the platforms.
2. **The recipe** that assembles them: hook title, narration, subtitles, camera motion on cards,
   arrows and highlight boxes, blur-fill framing.

**5c-2 delivers the materials.** They go into the Content Set and Studio places them
automatically, as 5c-1 does. **Roadmap item 6** builds the recipe as the first preset (its
"Profiles rebuilt as Python presets" slice), because the recipe needs narration, and narration
arrives in item 6.

The operator wants every material to show in the video. Photo slides are optional: they appear
only when they exist and fit the story. More materials may be added later, so each material is a
separate, optional part of the Content Set.

## 2. Evidence

**Reference videos.** Twelve Shorts were studied at 1 frame per second on 2026-10-22: seven from
IsseiNugroho, four from Venimee and one from Wibu Penggoreng. Notes are kept outside the
repository at `D:/thoth-tmp/research/5c2/notes.md`. In style A:

- the post card is shown large, with the post's own video playing inside it;
- the creator's profile page (header and video grid) is shown, followed by a collage of the
  creator's other videos;
- comment screenshots close the video.

**Stored Content Sets.** Measured on the 23 in the deployed stack (2026-10-22, read-only):

| Measure | Value |
|---|---|
| Input platform | TikTok 13, Instagram 6, X 4 |
| Main kind | `video` in all 23; no carousel and no text-only post yet |
| `main.card` | null in all 23 |
| Footage | 107 clips, all `source = search` (X 52, TikTok 49, YouTube 6); none from the creator |

**Why the post card is missing.** X and Instagram crop a post card only when the post has no
video (`want_post = not any(item.kind == "video" ...)` in `x_service.py`, and the same rule for
Instagram). TikTok and YouTube never crop one.

## 3. Goals

**G1. Post card for every main.** Each main gets a real crop of its post as it appears on the
platform:

| Platform | What is cropped |
|---|---|
| X, Threads, Instagram | The post element, now also when the post has a video |
| TikTok | The video page's author header and caption |
| YouTube | Nothing: a Short page has no post card worth showing |

The card also records **`media_box`**: where the post's photo or video sits inside the card, as
fractions of the card. Item 6 uses it to play the video inside the card.

**G2. Creator profile page.** A crop of the main creator's profile page, header plus the first
rows of the post grid, for TikTok, Instagram, X and YouTube. This is in addition to the existing
header-only profile card. Threads has no profile discovery, so it is skipped.

**G3. Creator footage.** The creator's other recent videos become footage candidates with
`source = "creator"`.

- **Discovery:** they come from the existing profile discovery for TikTok, Instagram, X and
  YouTube.
- **Gates:** every candidate passes the same gates as search footage: the text gate, the story
  gate (topic relevance by embedding, the same `story_min`), the clip download, OCR, the vision
  judge and the duplicate hash. The operator chose topic relevance over recency.

**G3a. Relevance when the caption says little.** The story gate reads only the caption, and an
empty caption scores 0. A creator's own listing is not filtered by a search query, so weak
captions are likelier there than in search results.

What the stored search candidates show (2026-10-22, read-only, 1,722 candidates):

- TikTok: 30 of 697 captions are empty or tags only (under 15 characters once `#tags` and
  `@mentions` are removed). They score 0.27 on average, against 0.54 for captions with text.
  They make up 21 of TikTok's 124 story rejections.
- The vision judge rejects 178 of the 301 clips it saw (object absent 105, commentary 87). It is
  the strictest topic check in the pipeline, and it looks at the frames.

The literature on short-video topic recognition combines the title with on-screen text, the
speech transcript and the frames. A user's title is a weak caption: usually related to the video,
but not always present.

The creator path therefore runs a three-step relevance check, cheapest first:

1. **Enriched text** (free, all 24 listed posts). Score the caption plus its hashtags split into
   words (`#BBMLangka` reads as "BBM Langka"), with the existing embedder and `story_min`.
   - At or above `story_min`: a candidate, as in search.
   - Below it, with a real caption (15 characters or more of body text): rejected. The creator
     wrote about something else, and that text is reliable.
   - Below it, with a weak caption: **undecided**, not rejected.
2. **Closeness in time** (free). Keep at most 3 undecided posts, published within 7 days of the
   main and nearest first. A follow-up or "part 2" is posted close to the story. The rest are
   rejected as `story`.
3. **The frames.** The kept undecided posts go through the normal clip download, OCR and vision
   judge, which decides `shows_object` against the main's visual objects as for every candidate.
   A weak-caption video showing the story's subject passes; one that does not show it is
   rejected.

This adds at most 3 clip downloads and 3 vision calls per workflow. Speech transcription is not
added: the vision judge already makes the topic decision on the frames. Add a transcript only if
logged results show relevant talking clips being lost.

Every workflow logs how many creator posts were scored, undecided, kept by closeness and
admitted. The operator can then tune the 7-day window and the cap of 3.

Creator photos use the same three steps, with the photo itself as the only frame.

**G4. Creator photos (optional).** Photo and carousel posts from the same profile listing go
through the text and story gates. Those that pass become photos, each a single still image.

- **Optional:** none found, or none relevant, is a normal outcome, not a failure.
- **The main's own carousel:** its images already become slides (5c-1); that is unchanged.

**G5. Studio places them**, through the 5c-1 import path:

- **Post card:** an overlay on `track_b_roll` from 0 s, for `reading_seconds(post text)`,
  clamped by the 5c-1 rules, at the 5c-1 card position. The profile card then starts at
  `max(PROFILE_AT, post card end + CARD_GAP)`. The reaction beat already starts after the
  profile card.
- **Creator footage:** placed like search footage, each in its own scene after the main.
- **Creator photos:** each in its own scene for `SLIDE_SECONDS`, fit `contain`.
- **Profile page:** its own scene right after the main, held for `SLIDE_SECONDS`, fit `contain`.
  This follows style A's order: the story, then who the creator is, then the creator's other
  videos. The creator footage scenes follow it, then search footage. The operator ruled on
  2026-10-22 that it is placed in this stage, not kept for item 6.

## 4. Non-goals

- **Memes.** They belong to style B. The 2026-10-22 research found no source that is free,
  current and safe to render:
  - the Tenor API was shut down on 2026-06-30;
  - GIPHY forbids storing its media;
  - KLIPY's licence is unverified.

  An own meme bank comes with style B.
- **News and evidence cards** from the web: Stage 6 (enrichment), which already searches the web
  for context.
- **The style A recipe** (hook, narration, motion, arrows, blur-fill): roadmap item 6.
- **Instagram attribution failures** (6 of 23 unresolved): an attribution question, not 5c-2.
- **Reply posts** as cards: comments already carry the replies' cards.

## 5. Anti-goals

- **A synthetic card.** Every card is a real crop or absent, as for every card so far.
- **A creator clip off the story.** It must pass the same story gate as search footage; the
  operator ruled topic relevance over recency.
- **A failed workflow when a material is missing.** Each material degrades to absent and is
  logged (`warn`). The Content Set stays valid.
- **New live requests in tests.** Every test runs offline on recorded fixtures (operator rule
  until the final acceptance). No Instagram private API.

## 6. Constraints

- **Content Set.** Schema stays version 1. New fields are optional with defaults, so all 23
  stored sets still validate:
  - `Main.post_card: MediaRef | None`, with `media_box`;
  - `Main.profile_page: MediaRef | None`;
  - `Footage.source` gains `"creator"`;
  - `ContentSet.photos: list[Photo]`.

  The existing `Main.card` keeps its meaning (the card of a text-only post).
- **Card storage.** Cards are PNGs in the media store under the workflow's report prefix, like
  `cards/profile.png`.
- **Accounts.** A profile or post page that is weaker signed out leases a source account with its
  proxy, under the existing `fallback` policy.
- **Footage limits.** `MAX_FOOTAGE` stays 6.
  - Creator clips take at most 2 of the 6; search fills the rest.
  - When the creator yields none, search may use all 6.
- **Photos.** At most 3 per Content Set.
- **Gate roles.** New roles appear in the Studio import gate with labels: `post_card`,
  `profile_page`, `creator_footage`, `creator_photo`.

## 7. Operator rulings (2026-10-22)

1. **Style A** is the first template. 5c-2 gathers its materials; item 6 builds the recipe.
2. **Memes** wait for style B; **news cards** wait for Stage 6.
3. **Creator videos** must fit the topic, not merely be recent. Weak captions use the three-step
   check in G3a.
4. **The profile page** is placed in this stage (G5), not kept for item 6.
5. **Extensibility:** more materials may come later, so each one stays a separate, optional
   part of the Content Set.

## 8. Calls made by the designer (for the operator to check)

- **Post-card timing:** the post card opens the video (0 s), and the profile card moves after it.
  This follows style A's order: subject first, then who posted it.
- **Footage split:** creator clips are capped at 2 of 6, so search footage still shows the wider
  story.
- **Photos:** at most 3, each held for `SLIDE_SECONDS` (3 s).
- **TikTok post card:** the author header and caption crop.
- **YouTube:** no post card.
- **Video inside the card:** `media_box` is recorded now, but the card is placed as a still in
  5c-2. Playing the video inside the card is a composition feature for item 6.
- **Same thresholds:** creator footage and photos use the existing `story_min` (0.36), with no
  new threshold.
- **Profile listing depth:** the creator's 24 most recent posts are listed once per workflow,
  through the same cached-search store as search footage.
- **Which post gets the card:** the post card is always the card of the main post, whether the
  main came from the input or from attribution (`source = original`).
- **A text-only main:** when `main.kind == "card"`, the card already is the main, so no separate
  post-card overlay is placed.
- **Query field:** creator clips fill `Footage.query` with `creator:@<handle>`, because the field
  is required and every other source fills it.
- **The `Photo` model:** `source: "creator"`, `url`, `platform`, `owner_handle`, `caption`,
  `image: MediaRef` (image type), `story_score`; at most 3, URLs unique and never the main's.

## 9. Left to the builder

- Selectors for the TikTok caption crop and for the profile page, header plus grid rows, on each
  platform. Choose them from recorded fixtures.
- How many grid rows the profile page shows: enough to read as a grid, within the existing card
  size limits.
- Extending profile discovery to return photo and carousel posts, with their image URLs.
- How the media box is measured inside the post crop: the bounding box of the post's media
  element relative to the cropped element.

## 10. Verification

- **Offline unit and integration tests:**
  - each new crop, against recorded page fixtures;
  - the `media_box` arithmetic;
  - creator candidates through every gate;
  - the 2-of-6 split;
  - optional photos;
  - old Content Sets still validating.
- **PostgreSQL integration:** placement of the post card, the profile card after it, creator
  footage and photos in Studio.
- **Stack smoke:** `workflow_opens_in_studio` extended with a post card and one creator clip.
- **Real-page checks:** wait for the final live acceptance (Stage 9). The operator may authorise
  one live capture per platform earlier as a separate gate.

## 11. Operator gates

Push, merge, deploy and any live capture are separate gates, each reported as it is taken.

## 12. Follow-ups

- **Roadmap item 6:** the style A preset (hook title, narration, subtitles, camera motion on
  cards, the video playing inside the post card via `media_box`, arrows and highlights,
  blur-fill).
- **Style B:** an own meme bank in the media store, with templates from Imgflip's trending list
  and memegen, plus uploads, matched to context by image-text embeddings.
- **Stage 6:** news and evidence cards.
