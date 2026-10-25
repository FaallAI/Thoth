# What a proper Studio is for Thoth: research report

Date: 2026-10-25. Author: Claude (the operator asked for this research to be done directly).

**Inputs:**
- `docs/DESIGN.md`;
- the Creator Studio F3 specs (`docs/superpowers/specs/2026-09-25-creator-studio-f3-full-ui-ux-design.md` and its parents);
- `design/PRD.md` and `design/DESIGN.md`;
- the 5c-1 and 5c-2 specs;
- the workflow-to-Studio spec;
- the auto-video engine research (`docs/research/2026-10-18-auto-video-engine-python-research.md`);
- `dashboard/src/features/studio/*`;
- the F3 selected-direction mockup;
- Remotion docs through Context7;
- public web sources (§3).

## 1. Summary

**The problem:** Studio F3 is a sound **editor shell**, but its model is generic. Its approved mockup is a travel slideshow ("A Day in Kyoto": scenes with a heading, a body and a style). It was designed in September, before the Content Set existed.
- What Thoth edits now is a **news story built from real evidence**: the main video, the post card (with its `media_box`), the profile card and page, comment cards (page crops and X embeds), footage with provenance and checks, figures, and Jev-judged comments.
- Soon it adds narration, voice and an auto-made draft (roadmap item 6).

**Recommendation:** keep F3's contracts (one preview, honest revision-bound operations, the save-state vocabulary, the import inventory, the revision-bound render, review, keyboard parity) and replace its model.

| Mode | Purpose | Default when |
|---|---|---|
| **Story** (replaces Simple) | Beat-based and Content-Set-aware: a Materials tray, a beat strip (Hook · Main · Evidence · Reactions · Footage · Outro) and a context inspector | The draft came from Open in Studio |
| **Script** (new) | Edit the narration as text; voice and caption timing follow (the Descript pattern) | The draft came from auto-draft |
| **Timeline** (Advanced) | The precise multitrack editor: zoom, snap, thumbnails, waveforms, canvas handles (the Remotion Editor Starter pattern) | Opened on demand, desktop only |

Import, render, voice and AI proposals all use the run progress model of `docs/DESIGN.md` §7.

## 2. Jobs and paths

**Path A, now: from a run.**
1. Open in Studio: import, then the inventory.
2. Check the story order.
3. Choose which evidence shows (which comment cards, which footage, the post or profile card).
4. Write and adjust the hook and captions.
5. Review.
6. Render.
7. Download.

**Path B, after auto-draft:**
1. Open the auto-draft.
2. Watch it.
3. Fix it:
   - script lines, which re-voice the affected beat;
   - a wrong card or clip, which is swapped;
   - timing;
   - the hook.
4. Approve.
5. Render.

| Job | Frequency | Mode | Phone? |
|---|---|---|---|
| Watch the draft end to end | every time | any | yes |
| Swap or choose evidence (cards, clips) | very frequent | Story | yes (from a list) |
| Edit the hook or title text | very frequent | Story / Script | yes |
| Fix a narration line and re-voice | frequent (Path B) | Script | text only; re-voice waits for desktop |
| Reorder beats | frequent | Story | no |
| Trim the main or a clip | occasional | Story (in/out) / Timeline | no |
| Fine timing, keyframes, transforms | rare | Timeline | no |
| Review comments, approve | every time | Review | yes |
| Start the render; monitor it; download | every time | Render | monitor and download |

## 3. Benchmarks

Sources were read on 2026-10-25. Most are third-party reviews; treat the specifics as indicative.

| Tool | What it does well | What it does badly, or what to avoid | Take for Thoth |
|---|---|---|---|
| Descript | Text-based editing: delete or move transcript text and the media follows; an AI co-editor (Underlord) writes and edits from instructions; Regenerate Speech fixes spoken words | Lacks frame-perfect precision; not for complex VFX | **Script mode** for narration review; re-voicing per line |
| CapCut (desktop) | Fast auto captions (about 15–20 s for 10 min; 92–96 % on clear English); a huge template library; AutoCut | Features drifting behind a paywall; simplified timeline; licensing questions | Caption styles as presets; one-click captions; avoid template sprawl |
| Opus Clip | AI picks clips with a 0–100 virality score; auto captions, reframing, auto B-roll | "Not an editor": only endpoints and style; about 70 % of clips usable | Show *why* the AI chose something (Thoth already has story score, Jev probability, verdicts), and let the person override |
| Submagic | Captions in about 48 languages, keyword B-roll, auto zoom at emotional peaks, AI hook titles | AI-only flow with little structure | Hook-title suggestions and emphasis zooms belong in the style recipe (style A), not in manual work |
| Frame.io / VEED | Frame.io: the reference for timecoded comments, threads and annotations. VEED: on-video annotation | Frame.io seats cost more as teams grow | Review = timecoded comments pinned to the frame and the beat, approve or request changes per revision |
| Remotion Editor Starter | A zoomable timeline with drag and drop, multiple selection, thumbnails and waveforms; an interactive canvas (move, resize, inline text); captions as a first-class layer; uploads to S3; Lambda rendering | It is a template, not a product | **Timeline mode** reference, on the stack Thoth already renders with |

**Where Thoth differs from all of them:** every visual can be real evidence, captured from the platform with its provenance. Studio must make evidence easy to choose and impossible to fake.
- Cards are never redrawn.
- Text-only comments can be quoted in narration or captions, but never turned into a card.

**Sources:**
- Descript: https://www.descript.com/video-editing, https://tooliverse.ai/tools/descript, https://yespress.io/products/descript.md, https://www.aixploria.com/en/descript/
- CapCut: https://atomisystems.com/screencasting/capcut-pc-review-2026-is-free-video-editing-really-worth-your-time/, https://diyai.io/ai-tools/video-generation/reviews/capcut-review/, https://www.miracamp.com/learn/capcut/the-ultimate-guide-to-autocut
- Opus Clip: https://marcandrews.com/opus-clip-review-2026-ai-video-shorts-tool-tested/, https://www.nemovideo.com/pt-BR/blog/opus-clip-review-2026, https://www.capterra.com/p/10006559/Opus-Clip/
- Submagic: https://www.toolsforhumans.ai/ai-tools/submagic, https://ucstrategies.com/news/submagic-review-2026-pricing-features-is-it-worth-it-for-creators/
- Review tools: https://www.rfp.wiki/vendors/frame-io/veed, https://www.capterra.com/p/148214/Frame-io/, https://www.playbook.com/blog/best-frame-io-alternatives-for-video-teams-2026/
- Remotion (Context7, `/websites/remotion_dev`): https://www.remotion.dev/docs/buy-a-video-editor, https://www.remotion.dev/docs/editor-starter/captioning, https://www.remotion.dev/docs/building-a-timeline, https://www.remotion.dev/docs/player/player

## 4. Mode model

**Story** is the default for imported drafts. Its regions:

| Region | Contents |
|---|---|
| Left: **Materials** | Main · Cards (Post, Profile, Profile page, Comments) · Footage · Photos · Figures · Comments (judged) · Uploads. Every item shows its provenance: platform, owner, captured time, page or embed, why it was chosen |
| Centre | The 9:16 preview with a safe-zone overlay toggle (TikTok, Reels and Shorts margins from the 5c-1 spec) |
| Bottom: **beat strip** | Hook · Main · Evidence · Reactions · Footage · Outro. Each beat holds its materials as chips, its duration and its issues. Beats are reordered, and materials dragged in, or added with "Add to beat" for keyboard use |
| Right: **Inspector** | Context for the selected beat or element: timing, position preset (inside the safe zone), motion (pan, zoom), emphasis (highlight box, arrow), and for media, the in/out points |

**Script** (Path B; also usable on Path A once there is narration):
- **Layout:** the narration is paragraphs, one per beat, beside the preview.
- **Editing:** editing a line marks its beat "Voice out of date". "Re-voice" regenerates only that beat, with the progress of §7.
- **Captions:** they follow the voice's word timings and can be corrected inline. Figures can be inserted as name mentions.

**Timeline** (Advanced, desktop only):
- **Tracks:** the v2 document tracks (`main_video`, `b_roll`, `overlay`, `caption`, `narration`, `music`, `sfx`), with thumbnails on video lanes and waveforms on audio lanes.
- **Editing:** zoom and snap; canvas handles on the preview to move and resize overlays.
- **Issues:** the issues panel stays under it.

**Destinations** stay Edit · Review · Render, as in F3. The **Prompt** job (Prompt Lab) leaves the per-document navigation: it edits project-level prompts and policies, which belong with the auto-draft presets on a project page ("Presets & prompts").

## 5. Thoth objects: what is evidence and what is editable

| Object | Evidence (never editable) | Editable |
|---|---|---|
| Main video | Source, owner, attribution verdict ("Original" / "Repost of @…"), OCR outcome | In/out (OCR trim shown with its reason), subtitle blur and mute switch (5c-1), volume |
| Post card | Pixels, `media_box`, captured time | Placement, timing, motion; "Play the video inside the card" (uses `media_box`) |
| Profile card / page | Pixels | Placement, timing, pan |
| Comment card | Pixels, page or embed, author, likes | Which ones show, order, timing, emphasis |
| Text-only comment | Text, author, likes, Jev relevance | Quote it in narration or a caption only. A card is never drawn |
| Footage clip | Platform, owner, query, story score, `shows_object`, OCR | In point, length, placement, mute |
| Figure | Name, type, role | Name label (typography) timing; mention in the script |
| Credit and attribution | Verdict and handle | Credit line placement in the outro (on by default) |

## 6. Long-running work in Studio (`DESIGN.md` §7)

| Process | Stages, then steps | Where it shows |
|---|---|---|
| Import (Open in Studio) | Copy media (n of m) · Probe · Place materials · Draft ready | An overlay on Run done, then the inventory gate; the run tray |
| Render | Queue (position) · Prepare assets · Render frames (n of total, fps) · Encode · Upload · Ready; the ETA comes from frame rate | The Render destination, the run tray, toasts, notifications |
| Re-voice (Script) | Synthesize (beat n of m) · Align words · Update captions | Inline on the beat and in the header save area |
| AI proposal | Thinking · Proposal ready | Inline at the selection, purple accent |
| Auto-draft (later) | Transcript · Script · Voice · Draft | Inside the run (stages after assembly) |

## 7. Review and versions

- **Revisions:** they stay the saved unit (F3).
- **Review:**
  - comments pinned to a frame and a beat, with threads;
  - "Approve for render" or "Request changes" for one revision;
  - a revision list showing what changed (from the operation log: "Swapped comment card", "Re-voiced beat 3");
  - side-by-side compare of two revisions comes later.
- **Readiness** (Render) adds publish checks:
  - safe zones respected;
  - the duration within the platform limit;
  - captions present;
  - the credit line present;
  - no unresolved import item.

## 8. Information architecture and screens

**Routes:**
- `/studio`: the document list (thumbnail, title, source run, state Draft / In review / Approved / Rendering / Rendered, revision, updated, owner), with filters, "New from a run" and "Blank".
- `/studio/:project/:doc`: the editor.

**Editor top bar (Studio variant):**
- back to the list or the run;
- the document title;
- the attribution badge;
- the mode switch (Story · Script · Timeline);
- the destinations (Edit · Review · Render);
- undo and redo;
- the save state (F3 vocabulary, with the new tokens);
- the Assist toggle;
- "Request review" or "Approve".

**Screens:**
1. Documents list.
2. Import progress and inventory.
3. Story mode, including materials drag, a missing material, an issue and a conflict.
4. Script mode.
5. Timeline mode.
6. Review.
7. Render: readiness, progress and outputs.

**Narrow (phone):**
- watch;
- Review (comment, approve);
- render monitor and download;
- light edits: hook text, caption text, swap a card or clip from a list.

No timeline and no reordering on a phone.

## 9. F3 migration

| F3 piece | Decision | Why |
|---|---|---|
| One preview, honest revision-bound operations, save-state words, keyboard parity, error summaries | Keep | Sound contracts |
| Simple mode (scene: heading, body, media, style) | Change into Story mode (beats and materials) | Generic slideshow model; Thoth's materials are evidence |
| SceneBoard (role glyph, no thumbnail) | Change: real thumbnails of real materials | Materials are real crops and clips, so thumbnails are honest |
| Asset library | Change into the Materials tray (Content Set groups plus an Uploads tab) | Provenance-first |
| Advanced timeline | Keep and extend (thumbnails, waveforms, canvas handles) | Remotion Editor Starter pattern |
| Prompt job (Prompt Lab) | Move to project-level "Presets & prompts" | It edits project policy, not one document |
| Review panel | Keep; add frame-and-beat pins and a revision change list | Frame.io pattern |
| RenderPanel | Keep the checklist; add the progress model and publish checks | `DESIGN.md` §7 |
| Import gate | Keep the inventory; add the import progress before it | Long copy step |
| F3 tokens | Migrate to the canonical scheme (`docs/DESIGN.md` §5.1); keep `purple` (AI) and `playhead` | Operator ruling 2026-10-25 |

## 10. Decisions (operator approved all five on 2026-10-25; see `docs/DESIGN.md` §13)

1. **Modes:** the names and defaults Story / Script / Timeline (Story for imports, Script for auto-drafts)?
2. **Prompt Lab:** move it out of the Studio navigation into project-level "Presets & prompts"?
3. **Phone scope:** add "swap a card or clip from a list" and hook or caption text edits to the F3 phone scope (watch, comment, approve, monitor)?
4. **Text-only comments:** quoted in narration or captions only, never drawn as a card (confirming the "never synthetic" rule)?
5. **Publishing straight to platforms:** out of scope for now (render and download only)?
