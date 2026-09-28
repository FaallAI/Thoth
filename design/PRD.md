# Creator Studio F3 UI/UX Product Requirements

**Status:** Draft for operator design review  
**Date:** 2026-09-28  
**Scope:** Creator Studio F3 and its Content Set entry point for the first `vertical_text_story` path

## Product outcome

A creator can open a Content Set in Studio, understand what was imported and what still needs attention, edit a vertical video in the browser, and render an exact saved revision. The experience uses one coherent workspace for Edit, Prompt, Review, and Render. It makes the difference between a local draft, a saved revision, a reviewed revision, and a render job explicit.

This PRD is a design brief, not authorization to implement product code, promote render parity, deploy, or replace the legacy render path. The selected dark visual direction is approved; the detailed F3 visual specification is marked proposed in its source document. Treat this PRD and the prototype as reviewable design work until the operator accepts them.

## Source hierarchy

1. `AGENTS.md` and `.superpowers/sdd/2026-09-25-creator-studio-f3-first-mode-migration/progress.md` for repository boundaries and current delivery evidence.
2. `docs/superpowers/specs/2026-09-24-creator-studio-f3-ux-first-migration-design.md` for the F3 product behavior and non-goals.
3. `docs/superpowers/specs/2026-09-25-creator-studio-f3-full-ui-ux-design.md` for proposed visual, interaction, and accessibility details.
4. `docs/superpowers/specs/2026-09-24-creator-studio-responsive-review-design.md` for responsive capabilities; `docs/superpowers/specs/2026-09-11-ui-first-creator-studio-design.md` for the parent Studio model.
5. `docs/superpowers/plans/2026-09-24-creator-studio-f3-workspace-ux.md` and `docs/superpowers/plans/2026-09-25-creator-studio-f3-first-mode-migration.md` for delivery seams, not additional product scope.
6. `docs/superpowers/specs/2026-09-24-creator-studio-f3-selected-direction.png` for hierarchy and tone. Its sample media, avatar, brand decoration, Add Scene, and Preview changes controls are illustrative, not requirements.

If the prototype, a plan, and a product specification disagree, preserve the behavior contract and flag the discrepancy for operator review. Do not invent an operation to make a mockup look complete.

## Users and jobs

| User | Primary job | Required confidence |
| --- | --- | --- |
| Guided creator | Shape a vertical story using scenes and plain-language controls | Which scene is selected, what will appear, what is saved, and what blocks rendering |
| Advanced editor | Refine clips on the same document through a multi-track timeline | Simple and Advanced do not fork or flatten work |
| Reviewer | Comment on and decide an exact saved revision | The reviewed picture and revision are unambiguous |
| Returning creator | Resume or create a draft from an existing Content Set | Opening never silently overwrites prior work or starts a different renderer |

## Scope and navigation

- The Content Set surface presents separate **Open in Studio** and **Send render** actions. The latter retains its legacy meaning.
- Studio has four freely reachable destinations: **Edit**, **Prompt**, **Review**, **Render**. They are jobs, not a forced wizard. Navigation preserves selection, local edits, and unsent text.
- Edit has **Simple** and **Advanced** views over the same canonical EditDocument. Exactly one preview instance presents the local draft in Edit and the saved revision in Review.
- The first import/migration path is `vertical_text_story`. Other legacy modes remain on their existing path.
- The dark Studio treatment is scoped to Studio. Discovery, other dashboard pages, application-wide branding, deployment controls, and a second renderer/editor model are out of scope.

## Core journey

1. From a Content Set, choose **Open in Studio**. Inspect the source without writing a draft. Choose an existing draft to resume or explicitly create a new draft.
2. Review the complete ordered source inventory. Each item has a role, safe name, disposition, and an action where appropriate. Unsupported content and unavailable media are named. Attach a project-ready asset or explicitly exclude an item; exclusions remain visible. Continue editing even with unresolved items.
3. In **Edit / Simple**, select and reorder scenes with buttons, edit the first text clip of a media-first scene, and adjust supported media, duration in seconds, captions, audio, style, and ownership controls. Every visible edit commits through a real persisted operation. The preview reflects the local draft.
4. Optionally switch to **Advanced** for the existing timeline, or visit **Prompt** to compare an AI proposal before selectively applying it. Neither action silently replaces local or locked work.
5. In **Review**, see and comment on the saved revision, then optionally approve or request changes. Review approval does not render or publish.
6. In **Render**, see the exact saved revision, readiness checklist, actionable blocking reasons, and recent jobs. Start Studio Render only when the server accepts that revision and all prerequisites. Monitor status and download an available result.

## Functional requirements

| ID | Requirement | Design acceptance |
| --- | --- | --- |
| UI-01 | Separate Studio entry from legacy Send render | Both choices are visible and labeled distinctly; entering Studio never triggers legacy render or silently creates a draft. |
| UI-02 | Resume/create choice | Existing drafts show saved revision, date, and unresolved count. Inspect is read-only. Close/Esc has no side effect. A new draft requires an explicit Create action. |
| UI-03 | Honest source inventory | Preserve ordered source roles and identify every unsupported or unresolved creative input. Show Attached, Excluded, or Unresolved with text and tone. Never fabricate a media thumbnail or silently drop an item. |
| UI-04 | Safe media resolution | Attach uses an explicit upload or project-ready asset choice; exclude is reversible within the open gate. The UI never asks for a raw URL or host file path. Continue in Studio remains available while Render stays blocked by unresolved items. |
| UI-05 | Scene editing | Show selection, role, ownership, human-readable duration, and media truth. Move earlier/later buttons provide a keyboard-usable reorder path; drag is optional enhancement. No Add Scene control appears without a backed operation. |
| UI-06 | Simple inspector | Heading, body, media, duration, captions, audio, style, and ownership appear only where supported and available at that viewport. Changes commit explicitly, retain input on failure, and show field-level reasons. |
| UI-07 | One document and preview | Simple/Advanced share one EditDocument. A single mounted preview shows the local Edit draft or the saved Review revision, with a clear revision cue. Hide or reposition it across jobs without creating another independent interpretation. |
| UI-08 | Prompt Lab | Visually distinguish locked policy from editable prompts. Compare an Improve/Translate proposal before Apply; never silently overwrite a draft, locked layer, or user edit. |
| UI-09 | Revision-bound review | Comments and decisions identify their saved revision and timecode where relevant. Historical comments look historical. Unsaved/offline/conflicted mutations show a persistent reason. |
| UI-10 | Render readiness and jobs | Checklist names the affected item and routes to resolution. UI and server enforce saved revision, resolved import, ready owned assets, and renderer capability. Job rows show safe status/reason and relevant Download/Details/Retry actions. |
| UI-11 | State recovery | Offline, unsaved, saving, failed save, conflict, stale revision, failed import/upload, blocked render, and failed job each have distinct text and an explicit recovery path. No automatic retry or transient-only error. |
| UI-12 | Honest controls | Every interactive control in the prototype either demonstrates a real product operation or is clearly marked as a prototype state switch outside the product canvas. Do not imply unsupported operations are shipping. |

## Responsive capability

| Surface | Desktop ≥1440 | Compact desktop 1024–1439 | Tablet 768–1023 | Phone <768 |
| --- | --- | --- | --- | --- |
| Edit | Preview, scene strip, inspector; Simple/Advanced | Same, collapsible side regions | Simple only; Scenes/Preview/Controls one pane at a time | Preview and Heading/Body light edit |
| Prompt | Full Prompt Lab | Full Prompt Lab | Full Prompt Lab | Saved text editing only |
| Review | Preview, comments, decisions | Same | Responsive review | Read/comment; no decision controls |
| Render | Readiness, start, jobs | Same | Start and monitor | Read-only monitoring and Download |
| Import gate | Dialog | Dialog | Dialog | Full-screen sheet with stacked rows |

At 200% text zoom, the active control remains reachable and no horizontal page overflow appears. Compact controls have at least 44 px targets. Advanced actions on narrow screens explain the desktop-width requirement.

## Visual and interaction contract

- Use `design/DESIGN.md` as the machine-readable visual token source and the proposed full UI/UX specification for detailed component behavior. The selected reference image establishes a restrained dark workstation with a prominent 9:16 preview, compact scene sequence, contextual inspector, and one warm accent.
- Keep status words beside color markers. Use calm, dense 4/8 spacing, Geist typography, monospace only for timecodes/durations/revision IDs, visible 2 px focus, and in-flow failure banners. Avoid decorative gradients, glows, avatars, fabricated media, and emoji icons.
- At desktop width, the Edit scene strip belongs below the preview and the inspector sits beside it. Prompt, Review, and Render use the full available workspace for their jobs.
- Keyboard navigation follows visual order. Native buttons support selection and reordering. Dialog focus is trapped and returns to the entry trigger; Esc closes without changing data. Reduced-motion preference suppresses nonessential animation.

## Design validation and acceptance

The prototype is ready for operator review when it demonstrates:

1. A coherent end-to-end journey from the two Content Set choices through draft choice, import inventory, Edit, Prompt, Review, and Render, using realistic non-live fixture data.
2. Explicit saved/local/reviewed revision differences, including at least one unresolved import and one recoverable failure state.
3. Desktop 1440, compact 1120/1024, tablet 820, and phone 375 px views plus 200% zoom, without horizontal overflow or hidden active controls.
4. Keyboard-only traversal of every visible product action, focus return from overlays, textual status, contrast at least WCAG AA for text, and reduced-motion behavior.
5. A design-to-requirement map in the prototype README identifying the screen/state that demonstrates each UI-01 through UI-12 requirement and naming any item that remains conceptual.

Prototype interactions can simulate persistence with local fixture state. They must label simulated behavior in the README; they must not make live provider, secret, asset-upload, render, deployment, or evidence-mutating calls.

## Open review decisions

- Approve or revise the proposed F3 full UI/UX specification before treating its exact pixels and copy as a production contract.
- Confirm the final copy for the Content Set entry choice and any intentionally unsupported imported fields after reviewing the live fixture inventory.
- Confirm whether the prototype's visual treatment of Advanced and phone is sufficient for implementation handoff; product capability remains bounded by the matrix above.
