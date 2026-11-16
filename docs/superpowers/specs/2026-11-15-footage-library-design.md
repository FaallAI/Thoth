<!-- Approved by the operator on 2026-11-15 ("ya sesuai dan setuju"). -->
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

## 9. Revision after the first live look (2026-11-16)

The operator looked at draft `edoc_6979cd46` (run `wf_c345c5a04ebd9290781b2fdf`). The footage was
"sama semua" and repeated the main, and none of the podcast's discussion of the incident made it
in. The operator then asked for narration that also draws on what the podcast says, so that the
story widens past the main post. The direction was approved ("ya setuju", brainstorm items 59-63,
2026-11-15/16), and it all ships on this branch.

### 9.1 What went wrong

- **The card left the subject out of `people`.** Mutant/Saiful appeared only in the event text.
  Aldi Taher, named only in comments, was listed.
- **The podcast moments were passing name mentions** (12:50, 46:47). The incident is discussed with
  words such as "pedang" (4:51-6:47), "marah" (3:36-8:28), "kursi" (17:17) and "diundang" (19:52,
  30:38-32:52). The English card never holds these words, and the picker needs a name on the line.
- **The 3 TikTok news recaps are copies of one recording.** It is a second phone's recording of the
  incident, copied by 3 accounts with their own watermark, captions or header bar. dHash missed
  the copies because the overlays change every pixel. They are not the main's recording: they show
  the same moment from the other side of the booth.
- **Nothing a footage video says reaches the narration or the planner.** `build_script_request`
  sees only the main post, and the planner gives footage shots `said=""`.

### 9.2 Context card (amends 4.1)

- **Subject first.** `people[0]` is the person the post shows doing the thing, even when only a
  nickname or a description is known ("Mutant", "pria bawa pedang"). The round-2 refine adds the
  real names the titles use for that person ("Saiful", "Saipul", "Ipul").
- **Comment-only names.** A person named only in comments is not one of the card's people, unless
  the comments say that person is in the video.
- **New field `spoken`.** Up to 12 single lowercase Indonesian words that people would say aloud
  when discussing this event: objects, actions and feelings, such as "pedang", "marah", "kursi",
  "diundang".
  - The default is `[]`, and it uses the same validator as `queries`.
  - It is stored with the card, and older stored cards decode with `spoken=[]`.

### 9.3 Moments by discussion density (replaces the scoring in 4.4)

- **Window scoring.** A 60 s window slides over the caption lines, past the 30 s intro. It scores:
  - 2 per line naming the subject (people[0]'s name or aliases);
  - 1 per line naming another card person;
  - 1 per distinct `spoken` word or event term in the window.
- **Qualifying.** A window qualifies with a score of at least 4 that includes at least 2 distinct
  `spoken` or event words. A name alone never makes a moment.
- **Moments.** Up to 3 non-overlapping windows are kept per video, best first. Each window's moment
  is the start of its best line, and the section stays 8 s from the moment minus 1 s.
- **No section.** A long video with no qualifying window gives no section. This drops the off-story
  Rockaroma Tretan Muslim video, which names a card person but never the incident.
- **`said`.** Each section keeps its window's caption lines as `said`, in source-video seconds and
  at most 1,500 characters. The 8 s clip is the picture; `said` is what is being discussed around
  it.

### 9.4 One copy of a recording (amends 4.3 step 5 and 4.5)

- **Recording match.** On top of dHash, a candidate is matched by ORB keypoints against the main
  and every admitted clip:
  - frames at 1 fps, 480 px wide, 1,000 features;
  - ratio test 0.75, RANSAC with at least 25 inliers per frame.

  A candidate whose frames match one other clip on at least 30% of its frames is a copy of that
  clip. A copy of the main is rejected `duplicate`, as today.
- **Same-video sections.** Sections of one long video are not compared to each other. They share a
  set and a camera, and that is expected, not a copy (the spike matched them 8/9).
- **Choosing among copies of a footage recording.** The operator ruled (item 63): the original
  first, otherwise the copy with the least added material.
  1. **An original wins.** An own-account clip or a traced original (4.5) is kept over any
     reposted copy, as today.
  2. **Otherwise the cleanest copy wins.** Clutter is the share of the frame covered by text boxes
     from the existing OCR text reader (`TextReader.read`), summed over the clip's 3 vision frames.
     Watermarks, burned captions and header bars all count. The lower share wins, and on a tie the
     earlier-published copy wins.
  3. **The loser is rejected `duplicate`.** If the loser was already admitted, it is un-admitted.
     The reason is reused, so no CHECK change is needed.
  4. **The trace still runs first.** A copy whose caption or OCR credits an account is traced as
     in 4.5. When no credit names the recorder, as with these 3 recaps, the cleanest copy is the
     best the run can do, and the operator sees which one it was.
- **Spike evidence** (item 62):
  - the recaps matched each other on 20/20, 16/20 and 12/20 frames;
  - they matched the main and the podcast on 0 frames;
  - the cost is a few seconds of CPU per run, and there is no paid call.
- **Another angle of the main's moment.** One such clip is kept, as the operator agreed. It is used
  only under phrases about that moment (9.6).

### 9.5 Narration draws on footage speech

- **Content Set.** `Footage` gains `said: list[TranscriptSegment] = []` in source-video seconds.
  Its existing `clip_start` places the clip within the lines. Library clips carry `said` too.
- **Migration.** Editor migration 0034 adds `said JSONB NOT NULL DEFAULT '[]'` to
  `footage_candidates` and `footage_library`. 0033 is already applied on stage1, so it stays
  unchanged.
- **Studio.** `said` and `clip_start` travel in the footage item's provenance (`why`).
  `StudioMaterial` gains both, with a default.
- **Script facts.** `ScriptFacts` gains `footage_talk`: one entry per footage item, holding a label
  ("YouTube/CURHAT BANG Denny Sumargo", or "@handle") and the joined `said` text.
  `build_script_request` adds: "What people say in other videos (auto-captions, may be misheard):
  - from <label>: <text>".
- **Source rules.** `SOURCE_RULES` gains one sentence: footage speech is what people said in
  another video. The narration names who said it and where ("di podcast Denny Sumargo, Saiful
  mengaku ..."), and never presents it as the main video's speech or as fact.
- **Evidence.** `footage_talk` counts as evidence for `unsupported_tokens` and the headline check.
- **Unchanged.** The main stays the hook (the beat guide is unchanged), and the length stays the
  preset's: the story gets wider, not longer.

### 9.6 The planner places it

- **Footage `said`.** Footage shots get `said` from the item's `said` lines that fall inside the
  shot's span in the source (`clip_start` + shot time). The sources block becomes "WHAT EACH VIDEO
  SAYS DURING EACH SHOT".
- **Soundbites.** `soundbite()` stays main-only, because only the main's audio plays.
- **Two prompt rules are added:**
  - a phrase retelling what someone said in a footage video takes that video's shots, best where
    it is said;
  - a footage clip showing the same scene as the main from another angle is used only for phrases
    about that moment.

### 9.7 Evaluation

- **Offline, test-first:**
  - the card parses `spoken` and drops odd types;
  - the density picker on `podcast_captions.json3` picks a window inside 3:36-8:28, and nothing at
    a bare name mention;
  - ORB matches a synthetic textured frame against a cropped, overlaid copy, and not against a
    different texture;
  - sections of one URL are not compared;
  - among two copies, the one with less text area is kept, and an admitted loser is un-admitted;
  - an original beats a cleaner copy;
  - `said` flows from the candidate to the Content Set, the materials, the narration request and
    the planner sources;
  - migration 0034 has a Postgres test.
- **Live, each its own operator gate:**
  - one new footage run on the Mutant post: the operator judges the clips;
  - one narration write on that draft (a paid call, with its cost shown first): the operator reads
    whether the podcast talk is used and attributed.

### 9.8 Left to the builder

- Where the ORB features of admitted clips are kept during a run.
- The exact prompt wording.
- How an admitted copy is un-admitted in the store.

### 9.9 Copy test amended after the same-set spike (2026-11-16, item 64)

This replaces the "at least 30% of its frames" test in 9.4. Matching frames alone cannot tell a
copy from another moment filmed on the same set: two podcast moments matched on 9 of 9 frames. A
copy is the same moment, so its frames line up in time.

- **Features:** the existing `attribution/adapters/visual.py` `OrbMatcher` (3000 features, ratio
  0.75, RANSAC) on 480 px frames.
- **Stage 1, cheap trigger:**
  - the candidate's 3 vision frames are compared against the main (one frame every 2 s, prepared
    once per run) and against each admitted clip;
  - nothing with 25 or more inliers means no copy.
- **Stage 2, only when triggered:** both clips are compared at 1 fps over a full inlier matrix. It
  is a copy only when all three hold:
  - at least 3 candidate frames have a best match of 25 or more inliers;
  - at least 60% of those best matches sit on one time offset (within 1 s);
  - the median, over those frames, of best inliers / that row's median inliers is at least 3.
- **Spike values:**

  | Pair | Offset | Peak |
  |---|---|---|
  | Copies | 17-20 of 19-20 on one offset | 11-28x |
  | Same set, other moment | 3 of 9 | 1.2x |
  | Unrelated | 0 matched | — |

- **Known limit:** a copy of a fixed-camera moment (a recap re-cutting a podcast moment) may not line
  up, and is then kept. A credited repost is still traced (4.5).

### 9.10 Sections have their own quota (2026-11-16, item 66)

- **Live run `wf_a91d3f0f`:** a section inherited its parent's query. That query's 2 slots (F6) went to search clips, so the discussion was never screened.
- **The rule now:** long-video sections are screened and counted under a queue of their own (`SECTIONS`, up to 2). The stored query stays the parent's, and the total stays 6.
- **Captions:** a caption track that answers 429 is fetched once more, after 8 s.

## 10. Related events over the same incident (2026-11-16, items 66-69)

### 10.1 Why

On run `wf_c7efa4c2` the operator saw footage "di kejadian yang sama dengan main video". They want "kejadian yang berbeda tapi masih satu context atau berkorelasi dengan context cerita main video". This corrects how item 59 was read: "sama dengan main" meant the same incident, not the same recording. One other angle of the incident is still fine (item 60). The problem is that only 5 or 6 slots exist, and same-incident clips are mostly reposts or heavily edited posts (item 68).

**What run `wf_c7efa4c2` shows.** 4 of the 5 admitted clips showed the USS incident:
- 3 came back from the library;
- 1 was a news video titled about Aldi Taher, but its frames show the USS incident.

Every stage selects the incident:
- **The card** looks for "the same story", and its queries pair a person with the event.
- **The vision `visual`** is "<person> in person, at <event>".
- **The library** gives the incident clips back.
- **The story gate** rejects related clips, for two reasons:
  - the 30-day window drops older episodes ("Mutant diajarin acting Jefri Nichol", 2024; "Medical Check-Up Mutant", 2026-06);
  - the card never learned the real name or the hashtag forms, so "Saipul akhirnya bertemu gurunya" (@dennysumargoreal) and "#mutan #tretanmuslim" posts named nobody on the card.

### 10.2 Goals and anti-goals

- **Goal:** most footage shows the card's people in *other* events, earlier or later, that relate to the story. Examples: their show episodes, a clarification, an apology, a reply, the podcast meeting.
- **Same incident:** at most 1 clip per run, and only a clean original (10.6).
- **Anti-goal:** unrelated content that merely shares a name, such as a different person called Saiful.
- **Anti-goal:** news recaps and reposts of the incident.

### 10.3 Relation

Every admitted video clip carries `relation`:
- `same_event`: it shows the main's incident;
- `related`: the card's people or their story, in another event;
- `unknown`: stored before this section.

### 10.4 Card

- **CARD_PROMPT** asks for the story's context, not only the incident. It gains:
  - `related`: up to 6 other events the people are known for or that followed, each `{"event": str, "query": str}`;
  - aliases that include real names, common spellings, and the hashtag form of each name (no spaces, lowercase).
- **`queries`** keeps at most 2 searches about the incident (for originals and tracing). The related queries are searched like the others.
- **REFINE_PROMPT** may add related events the titles show. It keeps adding the real names the titles use.
- **Round two always runs once.** Until now it was skipped when round one already had 6 passing clips. It was skipped in both Mutant runs (`refined` false), and that is why the card never learned "Saiful". Round one's story rejects are reopened after it, as before.

### 10.5 Gates

- **Name matching.**
  - A card name also matches its hashtag form (the name without spaces), so `#tretanmuslim` names Tretan Muslim.
  - A name word followed by the suffix "nya" also matches ("mutannya").
  - Spelling variants come from the card's aliases (10.4).
- **Time window.** A candidate that names a card person may be up to 2 years older than the main post. One that matches only by event words keeps the 30-day window.
- **Vision judge.**
  - **Visual.** For a person query, it is "<person> in person". For a related query, it is that event's text.
  - **New field `same_event` (yes/no):** do the frames show the main's scene, "<card.event>, at <card.place>"? This answers the relation (10.3), in the same single call.
- **Long-video sections.** A section is a person talking, so it is not rejected `commentary`. Its visual is "<people[0]> in person".

### 10.6 Quota

- **Totals.** `MAX_FOOTAGE` goes from 6 to 8 (item 69). `PER_QUERY` stays 2, and `SECTIONS` keeps its own queue.
- **Same-event clips.** At most 1 per run. It must be an original (creator, trace or own account; the 9.4 rule) with a text share of at most 0.15. Any other same-event clip is rejected with the new reason `same_event`.
- **Two clean originals.** The 9.4 order picks the cleaner one, and the other is rejected `same_event`.

### 10.7 Library

- **New column.** `footage_library` gains `relation TEXT NOT NULL DEFAULT 'unknown'`, through editor migration 0035. `footage_candidates` gains the same column.
- **On reuse:**
  - a `related` clip is reused as before;
  - a `same_event` or `unknown` clip is reused only as the run's one same-event clip, under the 10.6 rule. Since a library clip has no original status (a deferred minor), in practice it is not reused.

### 10.8 TikTok download failures

- Each `media_failed` logs its cause class at warning (for example `ClipError(resolver TimeoutError)`), with no URL.
- The "footage finished" line counts the failures by cause.
- The cause of run `wf_c7efa4c2`'s 21 failures is judged on the next run's logs. Any fix is its own decision.

### 10.9 Unchanged

The following stay as they are:
- the copy check (9.4/9.9);
- `said`;
- the footage talk in the narration;
- the planner rules. Rule 11, "a second angle only for phrases about that moment", governs the one same-event clip.

### 10.10 Evaluation

- **Offline:** tests for each rule above, using the Mutant fixtures.
- **Live** (operator gate): a new Mutant run. Expected:
  - at least 5 of the up to 8 clips are `related`;
  - at most 1 is `same_event`;
  - no recap of the incident.
- **The operator judges the clips.**

### 10.11 Left to the builder

- prompt wording;
- where `relation` is set in code;
- how the hashtag form is built from a name;
- the migration's shape, which follows 0034.
