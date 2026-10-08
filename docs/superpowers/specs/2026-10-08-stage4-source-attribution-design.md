# Stage 4: Source Attribution in Python — Design

Status: written spec approved by the operator on 2026-10-08.

Amendment (operator, 2026-10-08, during implementation): Jev is reached through OpenRouter's
Decisions API only (`https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13`),
with `THOTH_OPENROUTER_API_KEY` in place of `THOTH_TYPESAFE_API_KEY`. The request and answer
shapes are unchanged.

- Roadmap: Stage 4, "Move Source Intelligence", in `docs/python-scout-migration-roadmap.md`.
- Inputs to this design:
  - `docs/research/2026-10-08-stage4-source-intelligence-ideas.md` (flow map S1 to S8,
    efficiency ideas 1 to 9);
  - `docs/research/2026-10-08-stage4-source-intelligence-research.md` (Jev, Agno, tools);
  - `docs/decisions/2026-08-28-source-investigator-sdk.md` (Agno selected);
  - `docs/adr/0001-direct-full-python-migration.md` (golden fixtures, offline parity, no live
    traffic until the final acceptance).

## 1. Goal

When the workflow runs with intent `identify_original`, Thoth answers: is this post the
original, and if not, which post is? The answer is a typed `SourceAttribution` with cited
evidence. When the original is found, Thoth acquires it with the Stage 3 acquirers, so the
workflow ends holding both the repost report and the original's report.

This replaces the source-attribution half of Scout's `trace_source.ts` (flow parts S1 to S6)
with a Python module behind one interface, cheaper than Scout per repost and correct on the
reference pair that Scout fails today.

Success criteria:

1. On the reference pair (`@detikjatim` repost, `@vincentius.christ76` original, recorded in
   `docs/superpowers/specs/2026-08-26-source-video-identification-design.md`), the replayed
   fixture yields verdict `replaced` with the original's URL and confidence `high`.
2. Every golden fixture (section 9) replays offline and matches its expected attribution.
3. Model calls per repost: at most one vision call for the input, one Jev call for the
   decisions, and one vision call per finalist, with at most 3 finalists.
4. With no model keys configured, attribution still runs on deterministic credit rules and
   never fails the workflow.

## 2. Scope

In scope:

- S1 evidence, S2 credit resolution, S3 repost decision, S4 credited-account discovery, S5
  candidate evaluation, and S6 selection.
- Acquiring the selected original through the existing acquisition runner, including source
  accounts.
- Wiring into the `identify_original` branch of `SourceInvestigationWorkflow`.

Moved to other stages (operator decision, 2026-10-08):

- S4b story search (keyword search across platforms, and keyword generation) moves to Stage 8
  (discovery). Until then a suspected repost with no usable credit keeps the input and reports
  `unresolved`.
- S8d final OCR for the renderer (`trim_start`, mute, blur regions) moves to Stage 5
  (content assembly), its consumer.

Not needed in Python: S7 and S8a to S8c. Acquisition already materializes media and crops
real profile cards, so there is no CDN URL handling and no separate profile crop.

Out of scope for this stage, recorded as follow-ups: a per-post cache of OCR, vision, and
hash results (idea 7); the TikTok "original sound" shortcut (idea 6); `produce_video` using
attribution (Stage 7 chains it).

## 3. Decisions (operator, 2026-10-08)

1. Scope as in section 2.
2. The repost decision comes first (idea 4). When the evidence credits another account, the
   source is searched even if the input would be acceptable as a main. This departs from
   Scout on purpose (section 10).
3. Providers:
   - vision: Agno over Novita's OpenAI-compatible endpoint, with the existing
     `THOTH_NOVITA_API_KEY`;
   - typed text decisions: TypeSafe Jev, with a new `THOTH_TYPESAFE_API_KEY`;
   - Gemini embeddings and the Supabase `platform_logos` table are not used.
4. Visual matching uses `imagehash` perceptual hashes over center-cropped frames, matched as a
   bag of frame hashes in the manner of vPDQ; text OCR uses RapidOCR.
5. The output is a typed `SourceAttribution`. Golden fixtures record every external answer
   once and replay offline. The live capture for fixtures is its own operator gate.

Dependency facts checked on 2026-10-08 (PyPI): `agno` 3.1.1 (the repository allows
`>=3,<4`, locked at 3.0.1), `imagehash` 4.3.2 (BSD-2-Clause), `rapidocr` 3.9.2
(Apache-2.0), `onnxruntime` 1.30.0 (MIT), `opencv-python-headless` 5.0.0.93 (Apache-2.0).
`httpx` is already a runtime dependency, so Jev is called over HTTP without its SDK.

## 4. Architecture

One new package, `thoth_control_plane.attribution`, owns the flow. It depends on ports, never
on a provider directly:

```
attribution/
  models.py        SourceAttribution and evidence types (public, typed)
  evidence.py      S1: assemble Evidence from the repost report and its media
  credit.py        S1e text rules, handle extraction, S2 credit choice
  candidates.py    S4: credited-account discovery, S5 metadata filter
  matching.py      frame sampling, center-crop hashing, bag-of-hashes match
  service.py       S3 to S6 orchestration: the SourceAttributor
  ports.py         VisionReader, DecisionModel, TextReader (OCR), FrameSource, Discoverer,
                   Acquirer
  adapters/
    agno_vision.py     VisionReader over Agno + Novita
    jev.py             DecisionModel over the TypeSafe HTTP API
    rapidocr_text.py   TextReader over RapidOCR
    ffmpeg_frames.py   FrameSource over ffmpeg
```

The public entry point:

```python
attribution = await SourceAttributor(ports).identify(repost_report, artifact_root)
```

`repost_report` is the Stage 3 `SourceReport` v3. The roadmap writes the interface as
`identify(content_set)`; the Python Content Set arrives in Stage 5, so this stage takes the
acquisition report, which carries the same main-post facts.

### Temporal integration

- A new activity `attribute_source` runs `SourceAttributor.identify` and, when the verdict is
  `replaced`, acquires the original through the same acquisition runner as
  `inspect_source_candidates` (`account_runner` plus `registry.acquirer_for`), so source
  accounts apply.
- The original's artifacts are written under a key distinct from the repost's, so the two
  acquisitions in one workflow never collide.
- The activity heartbeats, has a 15-minute start-to-close timeout, and at most 2 attempts.
  It is idempotent per workflow: a retry overwrites its own artifacts atomically.
- `SourceInvestigationWorkflow`, intent `identify_original`, Python activity path: after a
  successful acquisition it runs `attribute_source` and appends the attribution artifact (and
  the original's report when there is one) before completing. The legacy Scout path and
  `produce_video` are unchanged.
- An attribution failure never fails the workflow: the activity returns verdict `unresolved`
  with a reason code, and the repost acquisition stands.

## 5. Flow

### S1 Evidence

From the repost report and its materialized video:

1. Text: the post text (caption) and owner handle from the report.
2. Frames: ffmpeg samples the video at 1 frame per second (`matching.py` keeps these frames
   for S5) and keeps the first 3 seconds for the credit scan.
3. OCR (RapidOCR) of the first-seconds frames: text boxes, from which `credit.py` extracts
   `@handles` (reply mentions excluded, as Scout's `source_credit.ts` does) and bare
   handle-shaped tokens near a watermark position.
4. One vision call (idea 5) on the cover frame plus 2 early frames, with a Pydantic output:
   the on-screen headline, a scene description, and a prose description of any platform icon.
5. Text rules (S1e, kept from Scout): `📸 @user` (and the camera variants) means Instagram;
   `tt/user` means TikTok.

`Evidence` keeps every item with its origin (`caption`, `frame_text`, `cover_vision`,
`text_rule`), so the attribution can cite it.

### S2 and S3 Decisions, one Jev call

All decisions share one Jev state (the evidence as JSON) and run as parallel questions in one
call:

- `is_repost` (`noul`): does the evidence show this post reposts another account's video?
- `credited_handle` (`choice`): which of the handles found in S1, or `none`, is the source
  credit? The options are only handles present in the evidence, so the answer can never be
  invented.
- `credited_platform` (`choice`): `tiktok`, `instagram`, `x`, `youtube`, `threads`, or
  `unknown`, given the logo prose, the text rules, and the handle's context.

Rules applied in code, not by the model:

- A text rule (S1e) overrides `credited_platform`.
- A credited handle equal to the repost's own owner is ignored.
- Without a credited handle: when `is_repost` is below its threshold, the verdict is
  `original`; otherwise `unresolved` (story search is Stage 8).
- Probability thresholds are calibrated on the golden fixtures and recorded in the plan.

Without a Jev key: a handle from a text rule, or a single `@handle` found in the frame text
with no competing handle, is taken as the credit; otherwise the verdict is `unresolved`, or
`original` when no handle and no repost sign exists.

### S4 Candidates

- The credited account's videos come from the Stage 3 profile discovery for the credited
  platform (TikTok profile, Instagram profile, X profile, YouTube channel), at most 30.
- Threads has no profile discovery yet; a Threads credit yields `unresolved` with reason
  `discovery_unsupported`.

### S5 Evaluation, cheapest first (ideas 2, 1, 3)

1. Metadata filter (free): the curated-aggregator list rejects the account (shared with
   Scout's `aggregators.ts` data); the plausibility window keeps only videos published at most
   14 days before the repost and at least 90% of its duration, when both values are known.
   Unknown values pass.
2. Ordering (free): the surviving candidates are ordered by publish time closest before the
   repost, then by views. Discovery returns no cover image today, so the cover-hash ordering
   of idea 1 is a follow-up (section 12); a cover would only ever order, never reject, because
   the original's cover may lie outside the repost's cut.
3. Frame match, in that order, at most 3 finalists, stopping early (idea 3): each finalist is
   acquired through the acquisition runner, sampled at 1 frame per second, and hashed.
   `match_share` is the fraction of the repost's quality frames that have a candidate frame
   within the hash distance threshold. A finalist from the credited account with `match_share`
   at or above the match threshold ends the search.
4. Finalist checks: one vision call classifies the finalist as `footage`, `commentary`, or
   `unknown` (commentary is rejected), and RapidOCR on its sampled frames rejects continuous
   burned-in speech captions (a reaction upload).

Hashes use the center crop of each frame (the outer bands, where credit bars and headlines
sit, are excluded); the crop ratio, distance threshold, and match threshold are calibrated on
the golden fixtures.

### S6 Selection

- Tiers stay as in Scout: the credited account (0), another account (1), the repost's own
  account or an aggregator (2).
- Within a tier, the highest `match_share` wins.
- A credited finalist with a match is `replaced`, confidence `high`.
- A credited finalist without a match but within the plausibility window is `replaced`,
  confidence `low`.
- Nothing usable gives `unresolved`; the input stands.

Bounded parallelism (idea 8): finalist acquisitions run at most 2 at a time inside the
activity.

## 6. Output contract

```python
class AttributionEvidence(StrictModel):
    kind: Literal["caption", "frame_text", "cover_vision", "text_rule", "visual_match"]
    detail: str                    # bounded safe text: a handle, a headline, a match share
    confidence: float | None = None

class AttributedPost(StrictModel):
    platform: Literal["tiktok", "threads", "instagram", "x", "youtube"]
    canonical_url: HttpUrl
    owner_handle: str

class SourceAttribution(StrictModel):
    schema_version: Literal[1] = 1
    workflow_id: OpaqueId
    input: AttributedPost
    verdict: Literal["original", "replaced", "unresolved"]
    source: AttributedPost | None   # set only when verdict is "replaced"
    confidence: Literal["high", "low"]
    reason: str | None = None       # a code, e.g. "no_credit", "discovery_unsupported"
    evidence: list[AttributionEvidence]
    candidates: dict[str, int]      # counts by outcome, e.g. {"filtered_window": 22, "matched": 1}
```

The artifact never holds a CDN URL, a cookie, a proxy, a model prompt, or raw model output.
New fields use defaults, so later versions stay readable.

## 7. Configuration and degradation

| Variable | Used by | Missing means |
|---|---|---|
| `THOTH_NOVITA_API_KEY` | vision | no cover vision, no finalist classification; logo prose absent |
| `THOTH_SOURCE_VISION_MODEL` | vision | default `qwen/qwen3-vl-30b-a3b-instruct` |
| `THOTH_TYPESAFE_API_KEY` | Jev | deterministic credit rules only (section 5) |

- Both keys are worker secrets in the Stage 1 provider file. Its preflight today accepts
  exactly `THOTH_NOVITA_API_KEY` and `THOTH_SUBTITLE_OCR_MODEL`; it gains an optional
  `THOTH_TYPESAFE_API_KEY`, still rejecting any other variable.
- RapidOCR, imagehash, and opencv join the `acquisition` extra (worker only). ffmpeg is already
  in the image.
- Every port failure (timeout, provider error, unreadable frame) degrades that evidence or
  that candidate, logs a `warn!`-level message with enums only, and never raises out of
  `identify`.

## 8. Security and history hygiene

- Temporal history carries only IDs, verdicts, counts, and reason codes.
- Prompts, model outputs, OCR text, and frames stay inside the activity; only bounded,
  sanitized evidence details reach the artifact.
- Provider keys never reach logs, events, or artifacts; the existing secret-leak test pattern
  (`tests/acquisition/accounts/test_secret_leaks.py`) extends to the attribution artifact and
  events.

## 9. Testing

- Unit tests per module with synthetic inputs: handle extraction, text rules, the metadata
  filter, center-crop hashing on generated frames, `match_share`, tier selection, and the
  no-key path.
- Port fakes drive `SourceAttributor` end to end offline.
- Golden fixtures, recorded once in a live capture that the operator authorizes separately;
  each records every port answer (discovery listings, OCR boxes, vision answers, Jev answers,
  frame hashes) plus a few real frames for the hashing and OCR adapters:
  1. TikTok repost with a burned-in watermark credit: the reference pair.
  2. Instagram repost credited with `📸 @user` in its caption.
  3. An original post with no credit: verdict `original`.
  4. A repost credited to an account whose source video is missing: `unresolved`.
  5. A credited account whose nearest candidate is a commentary upload: rejected, then
     `unresolved` or a lower-tier match.
- Parity (ADR 0001): each fixture's expected attribution is compared with Scout's decision on
  the same post; every difference is a departure listed in section 10 or a test failure.
- No live request in the suite; the conftest guard stays.

## 10. Departures from Scout

1. The repost decision comes first; a credit to another account triggers the search even
   when the input is acceptable (Scout keeps it).
2. Visual frame matching replaces text-embedding similarity; the reference pair, which Scout
   ends in `MainCandidateNotFoundError`, resolves.
3. No story search and no keywords; an uncredited repost is `unresolved` until Stage 8.
4. The credit is a constrained choice among handles found in the evidence, not generated
   text.
5. The platform logo is read by vision prose plus a Jev choice, not an embedding lookup in
   Supabase.
6. S7 and S8 are gone or moved (section 2).

## 11. Operator gates

- Live capture for the golden fixtures: its own authorization; it needs the Novita and
  TypeSafe keys and, where a platform needs a session, source accounts.
- `THOTH_TYPESAFE_API_KEY` issuance and its addition to the provider file.
- Push, merge, and deploy each need their own authorization. The live smoke joins the final
  acceptance (ADR 0001).

## 12. Follow-ups

- Stage 8: story search across platforms, with keyword generation.
- Stage 5: final OCR for the renderer (S8d).
- Per-post cache of OCR, vision, and hash results (idea 7).
- TikTok "original sound" shortcut (idea 6).
- Cover-hash ordering of candidates (idea 1, first pass): discovery gains an optional,
  never-serialized cover reference where its listing already carries one.
- Threads profile discovery, so a Threads credit can resolve.
- Upgrade the `agno` lock from 3.0.1 within `>=3,<4` when the plan first uses it.
