# When a reaction counts as an original — research

Date: 2026-10-13. Parked by the operator on 2026-10-11 (Stage 4 spec, section 12) and picked up
after the Stage 5a calibration. The two commentary cases there trim their opening screenshot or
text cards because attribution left them `unresolved`.

## 1. The operator's rule

- A reaction that **raises a new viewpoint or a new issue** from another account's post, and
  **gets people talking**, is an original in its own context.
- A reaction that **only discusses** the post is a repost. Thoth must find the original so it can
  process the source itself.

Thoth's question differs from the platforms' question. A platform asks whether the uploader added
enough to deserve reach. Thoth asks which video is the best source to build on. The platform
policies still give tested vocabulary for the first half of the rule.

## 2. What the platforms and the courts use

| Source | Counts as original | Does not count |
|---|---|---|
| YouTube reused-content policy | "reaction videos where you comment on the original video", critical review, a storyline plus commentary; the test is whether "viewers can tell that there's a meaningful difference" | clips with "little or no narrative", copies "without any substantive modifications" |
| Meta (Facebook, July 2025) | creative editing, voiceover, or commentary that is significant; reaction videos that add "their unique take" | stitching clips together, adding a watermark, very short videos with little value |
| Instagram (April 2024) | content the account created "or enhance[d] in a material way" | reposts; serial reposters (10 or more in 30 days) leave recommendations, and the original replaces near-identical reposts |
| TikTok originality policy (Sept 2025) | creative edits, own creative layer, appearing in the content yourself | subtitles that only transcribe the original audio, another platform's watermark |
| *Hosseinzadeh v. Klein* (S.D.N.Y. 2017) | a reaction that intersperses clips with criticism is "quintessential criticism and comment" | the court excluded reactions "more akin to a group viewing session without commentary" |
| *Warhol v. Goldsmith* (U.S. 2023) | a use with a further purpose; commentary that targets the original | new meaning alone; a use that serves the same purpose as the original |

All six sources converge on the same line as the operator's first half. A reaction counts when
it *adds* something with its own purpose: critique, new information, a new angle. A reaction that
replays the source, or narrates it with nothing of its own, does not. None of them uses
popularity. The operator's second half ("gets people talking") is Thoth's own condition, and it
fits Thoth's purpose: a reaction that started a discussion is itself the story.

## 3. What the two calibration cases show

| Case | Opening | Subject | What attribution can find |
|---|---|---|---|
| instagram_deO6A2MSoAt | 6 s screenshot of an X **text** post by @bravyson.vconk ("90% mood gue seharian…") | a text post, which the operator thinks was taken down | no video exists to find |
| instagram_deHz54GT4ea | 3 s TikTok clip carrying the @manicsofficials watermark, then a live-chat screenshot | a TikTok video and a chat | the TikTok video, if the account still has it |

The first case exposes a gap in the rule's second half. When the subject is a text or image post,
there is no original *video* to process. The reaction is the only video, whatever its
contribution. "Find the original" applies only when the subject is itself a video.

## 4. Signals Thoth can measure

| Signal | Answers | Available today | Cost |
|---|---|---|---|
| Subject shape: screenshot of a post, picture-in-picture, green screen, stitch or duet, a clip with another account's watermark | is this a reaction at all, and is the subject a video | partly: Stage 4 frame OCR finds handles and watermarks; the cover vision call describes the scene | add one field to the existing vision prompt |
| Subject media type: video, or text/image post | whether "find the original" applies | no | same vision field |
| Own share: seconds and frame area showing the creator's own material, against the subject's | replay against commentary | partly: the 5a OCR samples tell where the screenshot sits | free from existing samples |
| What the creator says (speech transcript) | new information or a viewpoint, against narration only | **no**: the Python worker has no speech recognition | new capability (section 5) |
| Caption and on-screen text of the reaction against the subject's | new issue against restatement | yes: caption, OCR, and the subject's caption when acquired | one LLM call |
| Comments respond to the creator's take, not only to the subject | "gets people talking" about the reaction | yes: Stage 2 acquires the top comments | one LLM call over at most 12 comments |
| Engagement against the account's baseline: views or likes relative to the creator's median | whether the reaction travelled | partly: Stage 3 profile discovery lists the account's posts with counts | free |
| Other accounts repost or credit this reaction | the reaction became a source itself | no: needs cross-platform story search (Stage 8) | later |

The transcript is the single most decisive signal for "new viewpoint or new issue". Commentary is
mostly spoken; the two cases above carry almost no text after their opening (empty OCR from
11 s on). Without speech, a judgement leans on the caption, which is often a hook.

## 5. Options

1. **Shape first, no new judgement** (smallest). Add `reaction_shape` and `subject_media`
   to the Stage 4 vision call. A reaction whose subject is a text or image post becomes
   `original` with the reaction evidence cited, since no source video exists. A reaction whose
   subject is a video stays on today's path and attribution looks for that video. This settles
   deO6A2MSoAt-type cases and leaves the operator's contribution test unanswered.
2. **Shape plus a contribution judge without speech.** Option 1, plus one structured LLM
   decision from the caption, the on-screen text, the comments, and the engagement ratio:
   `adds_new_issue`, `new_viewpoint`, `discussion_about_creator`. Cheap, but weak when the
   commentary is spoken only.
3. **Shape plus a contribution judge with a transcript** (recommended). Option 2, fed by a
   transcript of the reaction's audio. Two ways to transcribe:
   - local `faster-whisper` (CPU, `small` int8) in the worker: same choice as the local
     RapidOCR, no per-call cost, larger image, about 10–20 s for a one-minute video;
   - an audio-capable model over OpenRouter: no image growth, a per-call cost, the audio
     leaves the host.
   The transcript is reusable later: Stage 5b footage and narration both want it.

Under every option the outcome stays inside today's `SourceAttribution`. A reaction judged
original gets verdict `original` with new evidence origin `reaction`, so no new verdict value is
needed. A reaction judged a repost goes on to find its subject. When that subject is gone (taken
down, private), the verdict stays `unresolved` and the reaction is the main, as today.

## 6. A consequence for Stage 5a

Stage 5a trims only a main that may be a repost (`unresolved` or `none`). A reaction judged
`original` keeps its opening screenshot or clip, because that opening is the subject of the
commentary. The operator confirmed the trims of both cases on 2026-10-13 while they were
`unresolved`. If the operator wants an original reaction's opening cut too, that is a separate
rule for 5a.

## 7. Questions for the operator

1. Option 1, 2, or 3, and for option 3 local or provider transcription?
2. A reaction to a text or image post, with no video to find: original (option 1's rule)?
3. "Gets people talking": is it enough that the comments discuss the creator's take, or must
   the reaction also beat the account's usual engagement?
4. An original reaction keeps its opening (section 6): yes?
5. Golden cases: about six reactions, three of each kind, with the expected answer. deO6A2MSoAt
   and deHz54GT4ea can be two of them once questions 2 and 3 are answered.

## Sources

- [YouTube channel monetization policies: reused content](https://support.google.com/youtube/answer/1311392)
- [Meta: Combating unoriginal content (creators blog, July 2025)](https://creators.facebook.com/blog/combating-unoriginal-content)
- [Instagram prioritizes original content (Gigazine, May 2024)](https://www.gigazine.net/gsc_news/en/20240502-instagram-updated-algorithm-prioritizes-original-content)
- [PetaPixel: Instagram's new algorithm rewards original creators](https://petapixel.com/2024/04/30/instagrams-new-algorithm-punishes-copycats-rewards-original-creators)
- [TikTok Creator Academy: originality policy](https://www.tiktok.com/creator-academy/article/tiktok-originality-policy), summarized with citations at [contentiq.media](https://contentiq.media/rules/tiktok)
- [Hosseinzadeh v. Klein, U.S. Copyright Office fair use summary](https://www.copyright.gov/fair-use/summaries/hosseinzadeh-klein-sdny2017.pdf)
- [Eric Goldman: "Reaction" video protected by fair use](https://blog.ericgoldman.org/archives/2017/08/reaction-video-protected-by-fair-use-hosseinzadeh-v-klein.htm)
- [Andy Warhol Foundation v. Goldsmith (Cornell LII)](https://www.law.cornell.edu/supremecourt/text/21-869)
- [Video picture-in-picture detection using spatio-temporal slicing](https://research.buaa.edu.cn/en/publications/video-picture-in-picture-detection-using-spatio-temporal-slicing/)
