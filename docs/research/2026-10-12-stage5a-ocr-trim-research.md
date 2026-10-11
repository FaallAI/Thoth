# Stage 5a: intro trim and subtitle detection on real videos — research

Date: 2026-10-12. Asked by the operator before any calibration verdict is confirmed: the intro
trim exists for a main that is a repost (original not found) with an added headline, and must
cut only until the headline is gone. Evidence comes from the seven calibration captures of plan
Task 10 (RapidOCR boxes, production sampling and recovery) and a throwaway spike in
`D:/thoth-tmp/bu/s5/trim_spike.py`.

## 1. The trim lands in the middle of a sampling gap

The classifier (a faithful port of Scout's `classifyOcrFrames`) samples 0.5, 1, 2, 3, 4, 5 s and
then spreads the remaining samples to the end. A headline still present at 5 s and absent at
the next sample gets `trim_start` = the midpoint. Where the headline really ends was measured
two ways: OCR bisection to 0.25 s, and an OCR-free comparison of the headline's region (Canny
edge correlation against the region at the last sample where it was present, 10 frames per
second).

| Case | Present at | Absent at | Trim today | OCR bisection | Region diff | Real content lost |
|---|---|---|---|---|---|---|
| tiktok_detikjatim | 5.0 | 19.15 | 12.07 | 6.55–6.77 (6 OCR calls, 5.7 s) | 6.5 (0.9 s) | about 5.5 s |
| tiktok_officialinews | 5.0 | 16.39 | 10.70 | 9.45–9.63 (6 OCR calls, 6.8 s) | 9.6 (1.3 s) | about 1.1 s |

The midpoint can err either way by half the gap: it cuts real footage (both cases here) or
leaves the headline visible. The gap grows with the video length (12 samples).

Both measurements agree within 0.1 s. The region diff needs no model call: one ffmpeg process
decodes only the gap, and the edge correlation drops from above 0.8 to about 0.2 when the
overlay disappears. Edge-based overlay tracking is standard practice for broadcast text
(see sources).

## 2. Scene text read as subtitles

| Case | Verdict today | What the boxes are |
|---|---|---|
| instagram_deLTY7YtLl4 (an original: a stage event) | subtitle, blur over the lower third for the whole video, audio muted | stage banners "NEW WORLD RECORD", "5-HOUR PLANK", a shirt "JEAN WILDE", a sign "OFFICIAL ATTEMPT" |
| tiktok_kabinetketiduran (an original, operator-confirmed) | subtitle, 3 blur regions, audio muted | a scrolling LED wall "invest in tomorrow", "Danantara Indonesia", cut at the frame edge |

The classifier calls a box a caption when another frame holds different text in the same band.
Scene text satisfies that whenever the camera moves. Muting an original's audio is the most
damaging outcome of the whole stage. Scout's DeepSeek-OCR blocks probably had the same
weakness; its goldens never held such a video.

Signals that separate burned-in speech captions from scene text, from the captures and the
literature (positional stability and temporal frequency across frames):

- captions are horizontally centred and keep one band; scene text drifts with the camera;
- captions change text in most consecutive samples; signage repeats the same few strings;
- captions are never cut by the frame edge; scrolling or panned text often is (`x0 = 0.00`,
  `x1 = 1.00`);
- captions follow speech; a transcript match would be decisive but the worker has no speech
  recognition today.

## 3. An overlay that never leaves

instagram_deRDs6DCX07 carries its headline band for all 39 s. No trim can remove it; the
classifier blurs the band and mutes the audio as if it were speech captions. The blur is what
the operator wants (hide the added headline); the mute is not (there is no speech caption).
When attribution found the original (as it did here), the main is the original and the repost's
band never reaches the render.

## 4. Text cards that open commentary

instagram_deO6A2MSoAt opens on a screenshot of the X post it discusses, instagram_deHz54GT4ea
on two text cards; both get a cover trim (8.4 s and 10.4 s, again midpoints of a gap). Whether
the screenshot is a headline to remove or the subject of the commentary is the same open
question as the parked reaction-as-original research.

## 5. Options

1. **Refine the trim boundary** (recommended). After the classifier finds a headline with a
   present sample and an absent sample, decode only that gap at 10 frames per second, compare
   the headline region, and cut at the first frame where it is gone (optionally one OCR call to
   confirm). About 1 s per video, no model call. A deliberate departure from Scout: the
   classifier verdict stays Scout's; only `trim_start` is refined afterwards.
2. **Apply the trim only where it is meant to apply.** The operator's intent is a repost main
   whose original was not found. Options: trim only when `main.source == "input"` and the
   verdict is not `original`, or keep trimming news accounts' own intro cards too.
3. **Stop muting on persistent overlays.** A box that holds the same text in every sample is an
   overlay to blur, not a speech caption: blur it, keep the audio.
4. **Guard against scene text** before blur and mute: require centred captions, text changes in
   most samples, and no edge-cut boxes; or confirm a subtitle verdict with one vision call
   (the OpenRouter model attribution already uses) on three frames. Both need the calibration
   goldens to prove they do not lose real captions (detikjatim, officialinews).

## Sources

- [Overlay Text Extraction From TV News Broadcast](https://arxiv.org/pdf/1604.00470)
- [Video OCR for Video Indexing](https://arxiv.org/pdf/1109.6862)
- [Systems and methods for detection of burnt-in text in a video (US 9471990)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9471990)
- [Frame level and video level text detection in video (US 10867204)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10867204)
- [Detection and replacement of burned-in subtitles (US 11216684)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11216684)
- [OpenCV forum: static text detection in video](https://forum.opencv.org/t/static-text-detection-in-video/959)
- [VideOCR](https://github.com/timminator/VideOCR)
