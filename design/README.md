# Creator Studio F3 — UI/UX Interactive Design Prototype

This directory contains a self-contained, standalone interactive UI prototype designed to inspect, evaluate, and demonstrate the complete **Creator Studio F3 UI/UX Design System** with realistic dummy data.

---

## Referenced Specifications and Plans

This design prototype is built directly against:
1. **Product Requirements Document:** [`design/PRD.md`](PRD.md)
2. **Design System & Tokens:** [`design/DESIGN.md`](DESIGN.md)
3. **Full UI/UX Specification:** [`docs/superpowers/specs/2026-09-25-creator-studio-f3-full-ui-ux-design.md`](../docs/superpowers/specs/2026-09-25-creator-studio-f3-full-ui-ux-design.md)
4. **UX-First Migration Spec:** [`docs/superpowers/specs/2026-09-24-creator-studio-f3-ux-first-migration-design.md`](../docs/superpowers/specs/2026-09-24-creator-studio-f3-ux-first-migration-design.md)
5. **Responsive & Review Spec:** [`docs/superpowers/specs/2026-09-24-creator-studio-responsive-review-design.md`](../docs/superpowers/specs/2026-09-24-creator-studio-responsive-review-design.md)
6. **Parent Studio Spec:** [`docs/superpowers/specs/2026-09-11-ui-first-creator-studio-design.md`](../docs/superpowers/specs/2026-09-11-ui-first-creator-studio-design.md)
7. **Approved Visual Direction Mockup:** [`docs/superpowers/specs/2026-09-24-creator-studio-f3-selected-direction.png`](../docs/superpowers/specs/2026-09-24-creator-studio-f3-selected-direction.png)
8. **Implementation Plans:**
   - [`docs/superpowers/plans/2026-09-25-creator-studio-f3-first-mode-migration.md`](../docs/superpowers/plans/2026-09-25-creator-studio-f3-first-mode-migration.md)
   - [`docs/superpowers/plans/2026-09-24-creator-studio-f3-workspace-ux.md`](../docs/superpowers/plans/2026-09-24-creator-studio-f3-workspace-ux.md)

---

## How to Run

### Method 1: Python CLI Server (Recommended)

Run the Python server script directly from the repository root:
```bash
python design/serve.py
```
- Automatically selects an available port (default: 3000).
- Starts a local HTTP server serving `design/` with proper MIME types.
- Opens your default web browser at `http://localhost:3000/`.
- Optional flags:
  ```bash
  python design/serve.py --port 8080 --no-open
  ```

### Method 2: Windows Batch Launcher

Double-click `run.bat` inside the `design/` directory or run from CMD:
```cmd
design\run.bat
```

### Method 3: Direct Browser File (Zero Server Required)

Double-click `design/index.html` directly in your file explorer, or open `file:///c:/Users/mfr/Documents/MyTools/CLIPPER/design/index.html` in Microsoft Edge, Google Chrome, Mozilla Firefox, or Apple Safari.
- The prototype includes an embedded inline fallback fixture dataset so that local file CORS restrictions never block prototype initialization.

---

## Screen & State Mapping Matrix (PRD UI-01 through UI-12)

| PRD Section | Requirement Name | Prototype Screen / Element | Interactive Controls & State Capabilities |
| :--- | :--- | :--- | :--- |
| **UI-01** | Content Set Surface Choice | Surface 1 (`#surfaceContentSet`) | • Dual action decision cards with contrasting visual hierarchy.<br>• **"Open in Creator Studio"**: Opens draft inspection/choice in Creator Studio without auto-creating a draft on inspect.<br>• **"Send render (Legacy)"**: Dispatches unattended CLI render without opening Studio or touching drafts.<br>• Summary table of source inventory and recorded unsupported metadata. |
| **UI-02** | Resume vs Create Draft | Studio Import Gate Stage 1 (`#gateStage1`) | • Radio selection cards for existing drafts (Revision 3 latest/recommended, Revision 1).<br>• Explicit "Resume selected draft" action.<br>• Explicit "Create new draft" action with generated client idempotency key.<br>• Simulated offline notice. |
| **UI-03** | Comprehensive Source Inventory | Studio Import Gate Stage 2 (`#gateStage2`) | • Complete ordered table of all source items (1 main footage, 3 footage, 1 poster frame, 6 text scenes).<br>• Clear disposition badges: `Unresolved` (red dot), `Attached` (gold dot), `Excluded` (muted dot).<br>• Unsupported source fields block note (`crop focal rect`, `2 comments`). |
| **UI-04** | Source Media Resolution | Stage 2 Actions & Modals | • Attach popover with `Upload file...` (simulated progressive upload) and `Choose ready asset...`.<br>• Ready Asset Picker modal (`#readyAssetModalBackdrop`) listing verified project media assets.<br>• `Exclude` action and reversible `Undo exclude`.<br>• Dynamic unresolved item counter updating render readiness. |
| **UI-05** | Simple Mode Studio | Simple Layout (`#editSimpleLayout`) | • 1:1 match with approved visual direction mockup (`2026-09-24-creator-studio-f3-selected-direction.png`).<br>• Single visual preview stage recessed in `--studio-well`.<br>• 160px SceneBoard cards with reorder buttons `[↑]` `[↓]`.<br>• Inspector dock with honest bounds: Heading (300 chars), Body (2000 chars), duration, audio volume/mute, style slot, and ownership. |
| **UI-06** | Advanced Multi-Track Timeline | Advanced Layout (`#editAdvancedLayout`) | • 14rem project asset library dock.<br>• 4 synchronized timeline tracks: Video, Text, Captions, Audio bed.<br>• Playhead, second ruler ticks, and "0 blocking issues" indicator.<br>• Non-blocking switch between Simple and Advanced modes preserving identical draft state. |
| **UI-07** | Unified Video Stage & Playhead | Canvas Art & Player (`#stageVideoFrame`) | • Procedural atmospheric canvas art representing Kyoto pagoda and particle depth.<br>• Scrubber track with real-time timecode readout (`00:00.00 / 00:22.00`).<br>• Synchronized dynamic caption cues overlaying the player.<br>• Spacebar / `k` shortcut play/pause. |
| **UI-08** | Prompt Lab & AI Proposals | Prompt Tab (`#pane-prompt`) | • Read-only system policy and brand guardrail banner on `--studio-well`.<br>• Editable prompt field.<br>• Simulated Gemini 1.5 Pro synthesis with proposal diff view.<br>• Non-destructive "Apply proposal to draft" updating Scene 1 heading/body and triggering autosave. |
| **UI-09** | Revision-Bound Review | Review Tab (`#pane-review`) | • "Reviewing saved revision 3" chip overlay.<br>• Timecode-linked review comments feed.<br>• Interactive timecode jump (`00:02.15 ↗`).<br>• Authoritative decisions: "Approve Revision 3" vs "Request changes". |
| **UI-10** | Render Panel & Readiness Gate | Render Tab (`#pane-render`) | • Server-verified readiness checklist: Text complete, Timeline valid, Import resolved, Saved revision clean.<br>• Disabled "Start Studio Render" button when import has unresolved items, showing honest blocking reason.<br>• Recent render jobs history with status dots, timestamps, and download actions. |
| **UI-11** | State Recovery & Diagnostics | Header & Error Modals | • Full Save State Simulator in top toolbar: `Saved` (gold dot), `Unsaved changes` (hollow dot), `Saving` (pulsing dot), `Failed to save` (red dot + alert banner with retry), `Conflict` (terracotta dot + banner with reload/keep), `Offline` (muted dot + banner).<br>• Safe Diagnostics Modal (`#jobDetailsModalBackdrop`) for failed Job #11 showing `renderer_unavailable` and safe reason without internal stack traces.<br>• Safe retry action re-staging the render job. |
| **UI-12** | Accessibility & Responsiveness | Top Toolbar & CSS Breakpoints | • Desktop (1440px+), Compact Desktop (1120px), Tablet (820px with `CompactStudioNav`), Mobile Phone (375px monitor/text-only mode).<br>• WCAG 1.4.10 Reflow: 200% Zoom reflow toggle (`#zoomToggleBtn`) maintaining zero horizontal scroll.<br>• Minimum 44px touch targets on compact/tablet viewports.<br>• Visible 2px focus ring (`--ring`: `#efb28e`) across interactive controls.<br>• Text status labels accompanying every color dot indicator.<br>• WCAG AAA primary text contrast (13.9:1 against background). |

---

## Interactive Prototype Controls & Shortcuts

The prototype includes built-in meta-controls in the top bar to inspect any state without needing a backend:
- **Surface Switcher:** Toggle between `Content Set (UI-01)` and `Studio Workspace`.
- **Breakpoint Simulator:** One-click simulation of `Desktop (1440+)`, `Compact (1120px)`, `Tablet (820px)`, and `Phone (375px)`.
- **Zoom 200% Simulator:** Tests 200% text reflow without horizontal scrolling per WCAG 2.1 AA (1.4.10).
- **Save State Simulator:** Test `Saved`, `Unsaved changes`, `Saving`, `Failed to save` (with retry banner), `Conflict` (with server reload/keep banners), and `Offline`.
- **Import Readiness Simulator:** Toggle between `2 Unresolved (Blocked)` and `All Resolved (Ready)` to observe render readiness gating.
- **Compare Mockup Drawer:** Slide-out side-by-side drawer comparing the live interactive prototype directly against `docs/superpowers/specs/2026-09-24-creator-studio-f3-selected-direction.png`.
- **Keyboard Navigation:**
  - `Space` or `k`: Play / Pause video.
  - `←` / `→` Arrow keys: Cycle through the 7 Matt Pocock prototype variants.
  - `Esc`: Close modals and drawers.

---

## Simulated Behaviors and Open Design Decisions

### Simulated Behaviors
1. **Network & Backend Calls:** Draft autosave, project asset queries, Gemini AI prompt proposal synthesis, and render job execution are simulated with realistic delays (500–1200ms) and local state transitions. No external network requests are made.
2. **Video Playback Engine:** Video media rendering uses HTML5 layered Canvas drawing to create high-fidelity Kyoto scenery and pagodas, synchronizing with the timecode scrubber and active scene captions.
3. **Draft Idempotency:** The "Create new draft" action generates an explicit client-side idempotency key (`idemp-<random>`) to prevent duplicate drafts upon rapid retries.

### Open Design Decisions for Downstream Product Implementation
1. **Mobile Phone Scope (§3.5):** The prototype enforces a text-only inspector and monitor-only render view on 375px phone viewports. Product teams should evaluate whether full timeline trimming should be unlocked for larger mobile devices (e.g. 430px iPhone Pro Max).
2. **Audio Waveform Visualization (§5.6):** The advanced timeline currently displays a stylized solid audio bed bar. Production implementation may generate true pre-computed peak audio waveforms from backend FFmpeg passes.
3. **Conflict Merge Resolution (§4.2):** The prototype demonstrates two conflict branches: "Reload Latest" (server wins) and "Keep Local Changes" (client overwrites with next revision number). Three-way scene-by-scene field merge remains a potential future enhancement.

---

## Verification Evidence

All layout breakpoints, accessibility touch targets, and visual reflow metrics are verified using automated headless Microsoft Edge CDP tests (`design/verify_prototype.js`):
- **Desktop (1440x900):** `scrollWidth === 1440`, `hasHorizontalOverflow: false`.
- **Compact Desktop (1120x800):** `scrollWidth === 1120`, `hasHorizontalOverflow: false`.
- **Tablet (820x1180):** `scrollWidth === 820`, `hasHorizontalOverflow: false`, `CompactStudioNav` tabbed switching active.
- **Mobile Phone (375x812):** `scrollWidth === 375`, `hasHorizontalOverflow: false`, monitor-only render mode active.
- **200% Zoom Reflow:** `hasHorizontalOverflow: false`, single-column responsive reflow compliant with WCAG 1.4.10.
- **Design Tokens Lint:** Verified with `@google/design.md` (`0 errors`).
