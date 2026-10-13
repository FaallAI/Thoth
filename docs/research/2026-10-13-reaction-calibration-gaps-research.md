# Reaction calibration gaps: Instagram listing depth, and a misread subject — research

Date: 2026-10-13. Both came out of the live reaction capture of the same day.

## 1. Instagram lists 3 videos per account

### What happens

A live probe of the reaction account @sadampermana.w with today's discovery, anonymous, gave:

| Grid posts read | Videos | Dropped as photo or carousel | Pages | Exhausted |
|---|---|---|---|---|
| 12 | 3 | 9 | 1 | no |

The limit is Thoth's, not Instagram's:

- Stage 3 Instagram profile discovery reads one anonymous page: the 12-post grid. It keeps only
  video posts and never follows the next page.
- The signed-in page has a different structure, so the same parser returns `no_data` (Stage 3
  note). The thin-listing lease rule therefore gains nothing on Instagram.

A fresh reaction is usually one of those few videos. Once it is left out of its own baseline,
fewer than 3 remain, the ratio is unknown, and the reaction stays a repost. That is what
happened to DeWlWJmyKxP.

### How others list an account's reels

- **The signed-in reels endpoint.** Libraries and services (instagrapi, Apify actors,
  SociaVault, ScrapeCreators) list a user's reels through Instagram's signed-in API. Each item
  carries its shortcode, `play_count`, `like_count`, comment count, and `taken_at`. The list is
  paginated with `max_id` and `more_available`.
- **Anonymous access** is throttled to about 1–2 requests per 30 seconds (Instaloader reports
  401 "please wait"), so anonymous pagination does not scale.

### Options

1. **Signed-in reels listing** (recommended). Discovery leases an Instagram account with its
   proxy and pages the user's reels until it has 30. It gets real play counts, not only likes.
   This follows the operator's rule: where signed out is weaker, use the login with its proxy.
   It is Stage 3 discovery work and needs Instagram accounts imported.
2. **Use the whole grid** (photos and carousels too) as a like baseline. It works today, but
   reels and photos get different reach, so it mixes two populations.
3. **Paginate the anonymous grid.** It is throttled and depends on internal query ids that
   change.

Until option 1 exists, an Instagram reaction whose account posts few videos gets an unknown
baseline, so it is treated as a repost. That is the safe direction: Thoth then looks for the
original.

## 2. A video subject read as an image

### What happens

DeOUJ60SHeI reacts to an Instagram video (DeMU05JpXCY), but the vision call labelled its
subject `image`. The rule "a reaction to a text or image post is an original" then skipped
everything else: the contribution and discussion checks, engagement, and the search for the
original. The verdict was right by chance. A real repost misread the same way would pass as an
original, and Stage 5a would keep its opening.

### Signals that can check the vision label locally

| Signal | Text or image subject | Video subject | Cost |
|---|---|---|---|
| Motion inside the subject's shots: frame difference or SSIM between the 1 fps frames labelled `subject` | near zero over several seconds | changes | free; frames are already sampled |
| Another speaker heard while the subject is on screen (diarization turns that overlap the `subject` shots, from a speaker other than the creator) | none: an image is silent | often present | needs the speech step, which runs for video subjects anyway |
| On-screen player UI (play button, progress bar, Reels icon) | absent | often present | already part of the vision reading |

Static-frame detection by frame difference or SSIM is standard for screencasts (GUIWatcher). VLMs
are strong at UI elements in a single frame, but a single frame cannot show motion, which is
exactly what tells a still image from a paused video.

### Options

1. **Confirm the shortcut with motion and speech** (recommended). A text or image subject is an
   original only when:
   - its subject shots are static, by frame difference against a calibrated threshold; and
   - no other speaker is heard during them.

   Otherwise it takes the video path: the contribution and discussion checks, engagement, and
   the search for the original. The speech step then runs for these posts too.
2. **Always run the contribution judge**, even for text and image subjects. The operator's
   rule (text or image → original) would then need a condition added.
3. **Keep the shortcut and monitor it**: log the label and look at it after deployment.

## Sources

- [instagrapi](https://github.com/omaidf/instagrapi)
- [ScrapeCreators: scraping Instagram reels](https://scrapecreators.com/tutorials/how-to-scrape-instagram-reels-with-python)
- [Apify: Instagram profile reels by cookies](https://apify.com/shareze001/instagram-profile-reels-by-cookies)
- [SociaVault: Instagram view counts in 2026](https://sociavault.com/blog/instagram-view-counts-missing-search-2026)
- [Scraping Instagram in 2026 (anonymous throttling)](https://apiserpent.com/blog/scrape-instagram-for-free)
- [GUIWatcher: static frames by SSIM](https://arxiv.org/html/2502.04202v1)
- [VLM frame retrieval accuracy on UI elements](https://arxiv.org/html/2508.04895v1)
