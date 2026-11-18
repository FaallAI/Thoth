# Preview proxies for the Studio Player

Date: 2026-11-18. Status: approved in direction by the operator ("ya setuju", items 90-91 of `.superpowers/sdd/2026-11-12-footage-library/brainstorm-notes.md`).

## 1. Problem

On draft edoc_afd07b23 (revision 17), Studio playback stutters, but the rendered video is fine.

Every video source is stored as it was downloaded, and many have long keyframe gaps:
- the main: 8.3 s;
- footage: 4.2 s at 60 fps, 10.4 s at 22.6 fps, and 7.0 s in HEVC.

At Style B's rhythm a cut lasts about 2 s. To show a cut's first frame, the Player decodes from the keyframe before it:
- 23 of 32 cuts need more than 1 s of decoding;
- 14 need more than 3 s, at most 7.7 s.

The Player premounts a video only 1 s ahead, so it pauses to buffer. The render waits for every frame, so it never shows this.

## 2. Goal

The Player decodes at most about 1 s at any cut. Two things must not change:
- **the render:** it keeps the original files, so the video is unchanged;
- **ingest:** a run, an import and a footage download take no longer.

## 3. Design

**The proxy.** A video asset gets one preview proxy:
- H.264 (`libx264 -preset veryfast -crf 23`), `yuv420p`, 30 fps;
- a keyframe every second: `-g 30 -keyint_min 30 -sc_threshold 0`;
- the long side capped at 960 px, never upscaled, even sides;
- AAC audio at 128 kbps, because the main's sound plays in the preview;
- `+faststart`.

It keeps the source's duration and timestamps from 0, so a clip's `source_from_frame` points at the same moment.

**Where it lives.** The proxy is kept at `previews/<project_id>/<asset_id>.v1.mp4` in the media store, beside the asset, like a glance (`glance/...`, Tier 3b).
- There is no new column and no migration: the location is derived from the ids.
- An asset's bytes never change, so a proxy is kept for good. A failed build is never kept.

**When it is built.** When Studio asks for a video asset's preview capability, and the proxy does not exist yet.
- The build runs in the API process, in the background. The capability answers at once.
- At most 1 build runs at a time per process, and an asset already being built is not started again.
- This is the glance's pattern: built on first need, then kept.
- A draft opened for the first time plays its originals until its proxies are ready; the next open of the draft uses them.
- Old assets get their proxies when their draft is next opened. There is no separate backfill job. The originals are never touched.

**How it is served.**
- When the proxy exists, the capability's `preview_url` is `.../editor-assets/<asset>/preview/proxy`; otherwise it is `.../preview` as today.
  - The capability cookie's path, `.../preview`, covers both, so there is no new capability.
  - The URL is fixed per capability, so a Player never mixes byte ranges of two files.
- The `/preview/proxy` route is checked like `/preview`. It serves the proxy as `video/mp4` with ranges, and serves the original when the proxy is missing.
- `safePreviewSource` accepts the optional `/proxy` suffix and nothing else.

**Premount.** While playing, a video premounts 2 s ahead instead of 1 s, as Remotion Studio's own default.

## 4. Degrades without failing

The capability, the preview and the render behave as today in each of these cases:
- no ffmpeg;
- a failed build (logged as a warning, and not retried in that process);
- the media store down;
- an image or audio asset (never proxied).

## 5. Cost

- **Storage:** about 14 MB per minute of source, in `previews/`. Measured on edoc_afd07b23's six sources: 13.4 MB for the 58 s main, and 27 MB in all.
- **CPU:** background API CPU. Measured in the worker: 4.8 s for the 58 s main, and 0.6-2.2 s for each footage clip.
- **Billing:** a proxy is billed to nobody, like a glance (operator, 2026-11-09).
- **Orphans:** the upload sweep does not list `previews/`, and a deleted asset's proxy stays behind, as a glance does.

## 6. Evaluation

**Offline:**
- a proxy built from a test video with a 5 s keyframe gap has a keyframe at least every 1.05 s, the same duration within 0.1 s, H.264, a long side of at most 960 px, and audio;
- issuing a capability for a video without a proxy schedules exactly one build and answers `/preview`;
- with a proxy, it answers `/preview/proxy`;
- an image never schedules a build;
- `/preview/proxy` needs the same cookie and serves the proxy, or the original when the proxy is missing;
- `safePreviewSource` accepts `/preview/proxy` and refuses any other suffix;
- a failed build keeps nothing and does not break the capability.

**Live (operator gate):** open edoc_afd07b23 once so its proxies build, reopen it, and play. It plays without the pauses at cuts.
