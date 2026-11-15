# Footage library: context-searched footage per story (design)

Reference-faithful editing track, step 3. The brainstorm record is
`.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`. Items 1-10 and 46-53 decide this
design, and the spike output is at `D:/thoth-tmp/footage-spike/spike.out`.

## 1. Intent

A Thoth draft should carry several short pieces of footage that belong to the same story as the
main post, garnish ("imbuhan") so the video is not one long main clip. The operator's example is
draft `edoc_c570bd32…`, a TikTok about "Mutant" wanting to be on Denny Sumargo's podcast. It
"harusnya bisa menambahkan beberapa potongan footage youtube dari channel denny sumargo
https://youtu.be/Sy_S4TgvKbY karena satu context" (item 46).

A person finds such a video because they follow social media every day. Thoth runs once per
story, so it has to find the same thing from the main post's own context, in that one run (item
48). The operator ruled out continuous following of accounts: "kita belum ada resource cukup"
(item 50).

### Why the current footage stage misses it

Measured on the Mutant run `wf_4c7961fc…` (item 49): 70 candidates and 0 kept.

1. **The queries name objects, not the story.** The queries were "sneakers", "pedang excalibur urban
   sneaker society", "podcast studio urban sneaker society" and "dennys sumargo pidato urban sneaker
   society". The prompt in `footage/queries.py` asks for b-roll objects, and its person slot uses an
   official-speech template ("pidato"). "Mutant", "Saiful" and "Tretan Muslim" were never searched.
2. **Relevance is judged by caption similarity to the main caption** (cosine 0.36, `_story`). The
   same person goes by Mutant, Master Saiful, Saipul and Saeful, so relevant clips were rejected:
   - "SAIFUL BUKAN MUTAN #curhatbangdennysumargo";
   - "Detik-detik Pria Mengamuk di Depan Denny Sumargo".
3. **Long videos are rejected outright** (`gates.py`, more than 900 s gives `duration`). The 53-min
   podcast would be dropped even when found.
4. **Each run starts from zero.** Nothing found for a story is kept for the next run on it.
5. **yt-dlp returns some YouTube titles translated to English** in the worker.

### What the spike showed

Item 52: 4 posts, model cost USD 0.0042, read only.

- **A context card from the post's own text, with queries pairing people with the event, finds what
  the operator knew:**
  - "Mutant USS Denny Sumargo" on YouTube returns `Sy_S4TgvKbY` first, then 6 news recaps of 1-9 min;
  - for the Rocky Gerung post, it returns the creator's own YouTube channel and news recaps.
- **The card can be wrong.** For a post about Persib players in Melbourne it wrote "Indonesian
  national team players". The comments and the search results showed Persib.
- **The card does not know the newest alias.** "Saiful" was missing, but the first results' titles
  name it.
- **Long videos are usable.** The podcast's Indonesian auto-captions (1813 lines) arrive in under
  1 s. "mutan" is said 47 times from 02:45, and a 5 s 720p section downloads in 10 s (930 KB) in the
  stage1 worker.
- **`qwen/qwen3.7-flash` failed 4/4; `google/gemini-3.1-flash-lite` answered 4/4.**
- **`extractor_args youtube:lang=[id]` returns the original Indonesian titles.**

## 2. Goals

1. **A context card per run.** It names the people with every alias, the event, the place, the time
   and the meme or joke, and is built from material the run already has.
2. **Context queries** pair a person or alias with the event or the other person. They run on
   TikTok, YouTube and X with no platform priority, and a second round uses what the first round's
   results taught.
3. **Relevance comes from the card and the picture.** A candidate counts when its text names a
   card person, alias or event term, and its frames pass the existing vision check against the
   card's people. Caption similarity to the main caption no longer decides.
4. **Long videos count.** Their moments are found by auto-captions, and only short sections around
   those moments are downloaded.
5. **A library per workspace** keeps every clip it found, tagged by the card's people and date, so a
   later run on the same story reuses it with no new download. Copies of one clip are merged.
6. **Every style uses the clips** (item 51). They reach drafts through the existing footage path:
   - the content set's footage, then the Studio import's `footage` items;
   - Style B's planner picks them per phrase;
   - Style A shows them in its footage beat, as it shows footage today.
7. **A credit per clip:** "<Platform>/<channel or @handle>".

## 3. Non-goals and anti-goals

- **Non-goals:**
  - Following accounts or channels outside a run: no WebSub/RSS, no standing channel index (item
    50).
  - Special handling for small-creator stories that have little footage anywhere (item 53). They
    get what the search finds and otherwise fall back as today.
  - Restricting sources to news channels, or a legal approval step per source (item 47). Thoth is
    a tool, and the user is responsible for what they publish.
  - Reverse visual search (Google Lens through a paid API). The spike showed text search with
    people names is strong; it can be added later.
  - Paid SERP or ScrapeCreators providers. The native adapters already search all three
    platforms.
  - Picking long-video moments per narration phrase. Moments are picked at run time, from the card;
    the planner then picks among the downloaded sections.
- **Anti-goals (a failure even if it works):**
  - Footage that is merely about the same topic word ("sneakers") rather than the same story or
    people.
  - Slower or more fragile runs: the footage stage must never fail a run, as today.
  - A clip shown twice in one draft, or the same clip from two platforms counted as two.
  - A news channel's repost used when its original source could be found (item 54).

## 4. Design

### 4.1 Context card

- **When:** in the footage stage, before any search, once per run. It is stored on `footage_runs`
  (new JSON column `context`, default null), so a retry reuses it.
- **Input** (all already on hand):
  - the main caption and hashtags, owner handle and publish time;
  - the run's `figures`, when they are made before the footage stage (otherwise the card goes
    without them);
  - the top 25 comments by likes;
  - the transcript where stored;
  - the on-screen text the OCR already reads, when the builder can pass it cheaply.
- **Output, validated:**
  - `people`: name, aliases, role, accounts;
  - `event`, `place`, `when`, `meme_or_joke`;
  - `queries`: up to 6.

  Unknown or null fields become empty, as `FootageQueryAnswer` does today.
- **Model:** a new setting `THOTH_FOOTAGE_CARD_MODEL`, default `google/gemini-3.1-flash-lite`. If it
  fails, the existing `THOTH_FOOTAGE_QUERY_MODEL` is tried once. *(My call: the spike's qwen failed
  every time; gemini-lite answered every time.)*
- **Prompt:** the spike prompt (§ spike.py) is the starting point. Its rules:
  - aliases include nicknames, real names, spellings and the labels commenters use;
  - each query pairs a person with the event or the other person;
  - no hashtags and no generic objects;
  - "?" marks anything the model is unsure of.
- **Degrades:**
  - with no key or no answer, the run falls back to the current object queries (`footage_objects`)
    and the current story gate;
  - with `THOTH_FOOTAGE_CONTEXT_ENABLED=false`, the whole new path is skipped and today's stage runs
    unchanged.

### 4.2 Context search, two rounds

- **Round 1:** the card's first 4 queries on TikTok, YouTube and X, through the existing
  `PlatformSearch` and the search cache (`footage_searches`). YouTube is searched with
  `lang=id`.
- **Date window:** results outside the window are dropped. The window runs from 30 days before the
  main post's publish time to the run's start. *(My call: the podcast came 2 days after the main
  post, and older recaps of the same saga still count.)*
- **Round 2:** the card model gets one more call, with the card and the top 15 round-1 titles and
  channels. It returns the card updated with new aliases and corrections, plus up to 3 new
  queries, which are then searched the same way.
  - The point is to learn "Saiful" from "Master Saiful Ngamuk di Depan Denny Sumargo", or "Persib"
    from "Melbourne Victory vs Persib".
  - It is skipped when round 1 already yields the quota of passing candidates.

### 4.3 Gates

Gates run cheap before expensive, and every decision is stored as today.

1. **Kept unchanged:** `main`, `aggregator`, `spam`, `reaction_text`.
2. **Duration:** `MIN_SECONDS` stays. The 900 s cap no longer rejects a video that has
   auto-captions in the main post's language, which becomes a long-video candidate (4.4). Without
   captions, the cap stays.
3. **Context gate**, replacing the caption-cosine story gate on this path:
   - a candidate passes when its title, caption, channel or handle names a card person or alias,
     after accent folding and lowercasing (`norm`), or two event terms;
   - a candidate naming none is rejected `story`;
   - the old cosine score is still stored for comparison.
4. **Vision check (existing `FootageJudge`):** `visual` comes from the card. With a card person it
   is "<name> in person …" with `person=True`, else the event's look.
5. **OCR, duplicate hash and the quota** (`MAX_FOOTAGE = 6`) stay as today. *(My call; see the
   source-over-repost rule in 4.5.)*
6. **The creator listing** (the main creator's own posts) stays, but its posts go through the same
   context gate. On the Mutant run, all 29 posts of `@jnrksn` were unrelated travel posts.

### 4.4 Long videos

- **Captions:** a long-video candidate's Indonesian auto-captions (json3) are fetched without
  downloading media.
- **Moments:**
  - caption lines that name a card person or alias are scored, and lines naming two card terms
    score higher;
  - up to 3 moments are kept per video, at least 60 s apart, and the first 30 s (channel intro) is
    skipped.
- **Download:** each moment is a section from its line's start minus 1 s, 8 s long, at 720p or
  less, through the existing `YtDlpClipDownloader` window, which already takes `(start, end)`.
- **Afterwards:** each section is its own candidate (the URL plus `#t=<start>`), checked by OCR and
  vision like a short clip, with `clip_start` set to the moment.
- **No captions:** the video stays rejected `duration`.

### 4.5 Originals before reposts

The operator: "jika bisa berita relevannya langsung dari source video nya, bukan dari reposting"
(item 54). A news channel's recap of the CURHAT BANG podcast is a repost. The podcast itself is the
source.

1. **Own accounts first.** A candidate from an account or channel the card lists for one of its
   people (for example Denny Sumargo, then `@curhatbang`/"CURHAT BANG Denny Sumargo") is an
   original. It is tried before other candidates within the quota.
2. **Reposts are recognised by their credit.** A candidate whose title, caption or OCR text credits
   another account is a repost of that account. The credit is read with the existing
   `attribution/credit.py` (`text_handles`, `text_rule_credit`, `frame_handles`), plus the common
   "Sumber:", "via" and "YouTube/<channel>" forms.
3. **A repost is traced.** The credited account is searched with the card's queries, through the
   existing `CreatorPort.listing_of` or a channel search. A match within the date window takes the
   repost's place, and the repost is rejected `repost` (a new `RejectReason`).
4. **Kept copies are matched by picture.** A repost whose frames match (`is_duplicate`) a clip
   already kept from an original is rejected `repost` too.
5. **The fallback.** A repost whose original cannot be found may still be used, but only if it
   passes OCR as today. Burned-in subtitles and big overlays stay rejected. *(My reading of "jika
   bisa".)*

The library (4.6) keeps the original's credit when copies are merged.

### 4.6 The library

- **Table `footage_library`** (editor migration 0033), per workspace. One row per kept clip:
  - workspace;
  - source URL and platform;
  - credit text and owner or channel;
  - published time;
  - section start and end;
  - media location, checksum and dhash;
  - people tags (normalised names and aliases from the card);
  - event text;
  - first run;
  - created time.

  Every new field has a default.
- **Writing:** a clip kept by a run is written there. A clip whose dhash matches an existing row
  (`is_duplicate`) is merged, keeping the earliest-published copy as the source and its credit.
- **Reading:** a new run, after its card is made, looks up rows whose people tags meet the card's
  people within the date window. Those clips join the run as already-checked candidates, with no
  search and no download, and count towards the quota first.
- **Workspace scope:** a workspace only ever sees its own rows.

### 4.7 Into the draft

- **Draft path:** kept clips (new, or from the library) go out exactly as footage does today: the
  content set's `footage`, the Studio import's `footage` items, then the project's assets.
  - **Style B:** the planner already gathers `role == "footage"` items and their handles (stage 1).
  - **Style A:** its footage beat shows them, as it shows footage today.
- **Credit:** "YouTube/<channel>" for YouTube, "@<handle>" for TikTok and X.

### 4.8 Cost and time

| Item | Cost | Time |
|---|---|---|
| Context card | about USD 0.001 per call, 1-2 calls per run | — |
| Searches | free (existing adapters) | — |
| Caption fetches | free | under 1 s each |
| Sections | about 1 MB and 10 s each | — |

- **Stage deadline:** the run's existing footage deadline still applies.
- **Section cap:** at most 3 long videos x 3 sections per run.

## 5. Evaluation

Offline first, then one live look.

- **Fixtures:** the spike's 4 posts, as recorded material: input, card answers, search results and
  the podcast's captions. They test:
  - the card parsing;
  - the context gate;
  - the moment picker (on the podcast, "mutan" from 02:45);
  - the library merge.
- **Replay of the Mutant run's stored candidates:** under the context gate, "SAIFUL BUKAN MUTAN",
  "Momen Saeful temui Denny Sumargo di USS" and "Detik-detik Pria Mengamuk di Depan Denny Sumargo"
  pass, and "sneakers" posts do not.
- **Live, as its own gate with the operator's yes:** one new run on the Mutant post. Its footage is
  shown to the operator, who judges each clip blind as fits or does not fit. The target is agreed
  from that look, as in planner stage 1.

## 6. The research report's validation tests

The tests are in `reports/Indeks footage video lintas platform.md`.

| Test | Status |
|---|---|
| 2 (WebSub freshness), 4 (broadcaster latency), 6 (quota/callback) | Dropped with the non-goal of item 50 |
| 1 (SERP cross-platform) and 7 (ScrapeCreators) | Not needed; no paid providers here |
| 3 (recall) | Replaced by section 5 |
| 5 (download ability) | Shown for YouTube sections in the spike; TikTok and X downloads already work in the run |
| Context-card test on three earlier random posts | Done (item 52) |

## 7. Left to the builder

- The exact module split. For example `footage/context.py` for the card and context gate, and
  `footage/moments.py` for caption moments.
- Prompt wording within the rules above.
- The caption-line scoring weights.
- How round 2 is merged into the card.
- Whether the library lookup lives in the footage store or its own repository.

## 8. Decided after review

- **Burned-in subtitles** (item 54): the original source comes before a repost (4.5). A repost
  with burned-in subtitles or a big overlay stays rejected, as today.
