# Meaningful comments and X embed reply cards: design

Date: 2026-10-24. Status: approved by the operator, with D1 and D2 amended the same day after measurement.

## Why

On the operator's X run `wf_77c03f27…`, only 3 of 14 replies got a card. A live probe proved the cause (`D:/thoth-tmp/research/x-reply-cards/`):
- a signed-out X post page shows a few top replies, then the "See all the replies / Continue to X" gate;
- scrolling loads nothing more.

X's embed widget renders any reply signed out:
- the URL is `platform.twitter.com/embed/Tweet.html?id=<reply>&theme=dark&hideThread=true`;
- live check 2026-10-24: status 200, dark theme, no parent post, reply text and media kept.

## Operator rulings (2026-10-24)

1. A few comment cards are acceptable, but every comment used must be relevant to the post and meaningful, never filler.
2. The official embed is the fallback for replies without a page card.
3. Using the X account with its proxy for the card page was approved, then parked. The cost research (`D:/thoth-tmp/research/x-cards-cost/report.md`) found that embeds already card every reply for free. It is not part of this design.
4. **Amendment.** A model, not a word count, decides what is meaningful:
   - D1 becomes a loose noise filter;
   - D2 uses TypeSafe Jev.

## Design

### D1. Noise filter (deterministic, free, every platform)

**Rule:** `acquisition/substance.py` `is_substantive(text)`. After removing @mentions, links, emoji, punctuation, laughter (`wkwk`, `haha`, `awokawok`, …) and stock filler (`first`, `mantap`, `up`, …), a comment passes when it has at least **1 word and 4 letters** left.

**Measurement** (`D:/thoth-tmp/research/comment-filter/`, 236 stored comments):
- the first draft's floor of 3 words and 12 letters dropped 15%, among them the most-liked short reactions ("dibayar itu", "curiga suaminya", "Negara aneh");
- the loose filter drops 8%, all pure noise.

**Where it is used:**
- `merge_comments` (every platform) drops failing comments before ranking;
- the X acquirer chooses embed candidates from comments that pass (D3);
- it stands in alone when Jev cannot answer.

### D2. Relevance judge: TypeSafe Jev (at assembly, every platform)

**What:** one call through OpenRouter's Decisions API (`typesafe/jev-1.13`), the adapter attribution already uses, with the same OpenRouter key.
- The state is the post text, the attribution headline, and at most **50** candidates in likes order.
- Each comment gets its own `noul` question ("relevant to the post's topic, and says something?") with `true`/`false` criteria.
- Comments with a yes-probability of at least **0.5** are kept, in likes order, capped at the Content Set's 12.

**Degrades:**
- No key, a failed call (one retry), or a short answer makes the noise filter alone decide, with a warning (`comment judge unavailable`).
- The workflow never fails on it. Attribution does fail without Jev, because there Jev is required.

**Metering:** a `provider_call` with the reported input and output tokens.

**Live check 2026-10-24** (operator go):
- one call, 50 questions, accepted;
- 7,629 input tokens, about **$0.0003** (output is free);
- on the stored TikTok run `wf_ac2a5948…`:
  - 49 of 50 kept;
  - the lowest was an off-topic meme (0.12);
  - the highest were on-topic remarks (0.97 to 0.98).

### D3. X embed fallback for reply cards

**When:** after the post and profile page visits in `XHeadlessBrowser`, for comments that pass D1 and got no page card, most liked first, up to **`MAX_EMBED_CARDS = 6`** per run.

**How each embed is captured:**
- The browser opens `https://platform.twitter.com/embed/Tweet.html?id=<id>&theme=dark&hideThread=true&dnt=true&lang=en` in the same anonymous session.
- It waits for the `article`.
- It keeps the crop only when the article links to `/status/<id>` or shows the reply's text prefix (`EMBED_MATCH_JS`). A wrong card is never kept.
- The card is stored like a page comment card (`comment-<id>.png`). The Content Set schema is unchanged.

**Pacing and failure:**
- Embed visits are 5 s apart. Their host is not `x.com`, so the 30 s gap between X pages does not apply.
- Failures land in `Cards.problems`. The source step never fails on an embed.

**Logging:** `x embed cards tried=<n> kept=<n>`.

### Not in scope

- The account and proxy route for the card page (parked; see ruling 3).
- `blocked_domains` for the card session, proposed by the cost research. It needs a visual check first.
- `produce_video` running assembly, which has its own research (`D:/thoth-tmp/research/produce-video-chain/`). Until it lands, D1 and D2 run only where assembly runs (`identify_original`). Dashboard runs (`produce_video`) get only the D3 embed selection. The operator asked that this be verified when that fix lands.

## Tests (offline)

- **D1:** short meaningful comments pass; emoji, mentions, links, laughter and filler fail.
- **D2:**
  - the threshold keeps the likes order;
  - at most 50 texts are sent;
  - none, an error, or a short answer falls back to D1 with a warning;
  - the Jev request has one `noul` question per comment over one state, with criteria;
  - a failure is retried once, then answers none.
- **D3:**
  - only uncarded candidates are visited, capped, with the gap between visits;
  - the URL is dark with `hideThread`;
  - a mismatch gives no card;
  - a failed visit is only a problem;
  - the acquirer passes the candidates.

## Verification

- `bash scripts/dev/pytest-wsl.sh` (full suite) and `make lint`.
- **Operator live gate after deploy:** one anonymous X acquisition on `https://x.com/namelesid/status/2113895024895070537`. Expect the page cards plus up to 6 embed cards.
