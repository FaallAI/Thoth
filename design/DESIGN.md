---
version: alpha
name: Creator Studio F3
description: Restrained dark workstation for revision-bound vertical video editing.
colors:
  background: "#18191b"
  card: "#242628"
  studio-well: "#101113"
  studio-raised: "#2a2c2e"
  foreground: "#f5f3ee"
  muted-foreground: "#c5c6c7"
  primary: "#d49a79"
  primary-foreground: "#1b1918"
  ring: "#efb28e"
  accent: "#3b3532"
  border: "#47494a"
  studio-ai: "#af87ff"
  studio-playhead: "#82b1e8"
  status-succeeded: "#d7af5f"
  status-failed: "#ef4444"
  status-running: "#22d3ee"
  status-queued: "#8b8794"
  status-cancelled: "#6f6b78"
typography:
  body:
    fontFamily: "Geist Variable, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  control-label:
    fontFamily: "Geist Variable, sans-serif"
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.4
  section-label:
    fontFamily: "ui-monospace, monospace"
    fontSize: 11px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: 0.16em
  timecode:
    fontFamily: "ui-monospace, monospace"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: 4px
  md: 6px
  lg: 8px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  section: 20px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.control-label}"
    rounded: "{rounded.md}"
    height: 36px
  panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: 16px
  preview-well:
    backgroundColor: "{colors.studio-well}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: 16px
---

## Overview

Creator Studio is a dense but calm creative workstation. One vertical preview is the visual anchor; a scene sequence and contextual inspector support fast edits. Edit, Prompt, Review, and Render share the same visual language, while status and revision cues keep each job honest. The selected reference image sets hierarchy and tone, not a literal feature list.

## Colors

Warm charcoal surfaces and legible off-white text carry the workspace. Terracotta marks the primary action and selection. Violet identifies AI-touched content, soft blue identifies the timeline playhead, and inherited status tones identify outcomes. Every status tone appears with a word; color alone never conveys meaning. Keep failure text on a surface with verified 4.5:1 contrast.

## Typography

Use the shipped Geist Variable family for interface text. Use monospace only for section labels, timecodes, durations, and revision identifiers. Body and control labels are 14 px; secondary metadata is 12 px; no text is smaller than 11 px. Allow wrapping at 200% zoom.

## Layout

Use a 4/8 px rhythm: 16 px panel padding, 8 px control gaps, and 20 px section spacing. On full desktop, Edit places the preview above the horizontal scene strip and the inspector to the right. Advanced adds the existing asset region and multi-track timeline. Tablet and phone show one principal pane at a time. Compact screens retain 44 px minimum touch targets.

## Elevation & Depth

Separate workspace regions with 1 px hairlines. The preview and timeline recede into `studio-well`; popovers and dialogs rise one surface step to `studio-raised` and may use one soft shadow. Keep banners in document flow so they never cover a focused control.

## Shapes

Use 6 px radius for cards, controls, and buttons; 4 px for chips; 8 px for the preview well and import dialog. No decorative glow or gradient.

## Components

Use native buttons for jobs, scene selection, and reorder actions. The active job has a 2 px terracotta underline. Inputs are bordered and commit explicitly; disabled actions expose a reason. Show a 2 px `ring` focus indicator on every control. Use Lucide-style vector icons with visible text, or a clear accessible name for icon-only buttons. The 9:16 player is the only preview instance. Errors persist in inline text or in-flow banners with a recovery action.

## Do's and Don'ts

- Do show the saved revision and local save state before review or render.
- Do name unresolved, attached, and excluded import items, and keep exclusions visible.
- Do keep keyboard alternatives for pointer gestures and respect reduced motion.
- Don't copy illustrative Add Scene, Preview changes, avatar, or fabricated thumbnail controls from the reference image.
- Don't invent URL/path inputs, additional renderer surfaces, or controls with no persisted operation.
