# Studio full-width timeline

Approved by the operator on 2026-11-09 on the mock-up
https://claude.ai/artifact/DvjVu7AnrB4zSaYbxnZZo2 (private to the operator).

## Why

At 1440x900 the Timeline mode gives the timeline about 910 px of width, because Assets and the
Inspector take the full height on both sides. The video is about 150 px wide, and about 95 px under
the tracks is empty. Nothing can be resized, and a drag selects the text around it. The operator
wants the arrangement of a desktop editor such as CapCut: the timeline along the whole bottom.

## What changes

These apply to the Timeline mode of the Edit job at 1024 px and wider, unless a line says otherwise.

1. **Two rows.** Assets, the preview and the Inspector share the top row. The timeline spans the
   whole width of the bottom row. Collapsing Assets or the Inspector at compact desktop widths keeps
   working.
2. **A divider between the rows.**
   - Dragging it changes the timeline's height, and the preview takes the rest.
   - It is a focusable `role="separator"`. Arrow Up and Down move it 16 px, 64 px with Shift. Home goes
     to the smallest height and End to the largest.
   - A double-click returns to the default height.
   - The height is remembered per browser. It is not part of the document and is not sent to the server.
   - Limits: timeline at least 150 px, top row at least 240 px. A remembered height that no longer fits
     the window is shown at what fits and comes back when the window grows.
   - Default height: 392 px, which shows the seven standard tracks without scrolling.
3. **The preview fills its cell** and keeps the canvas's shape.
4. **Player controls leave the video frame** and sit in a bar under the preview: time on the left, play
   in the middle, then ratio and size, mute and fullscreen on the right. In fullscreen the Player's own
   controls come back, because the bar is not on screen there.
5. **The issues status moves into the timeline toolbar.** It shows "No issues" or the warning count
   with its button. The list opens above the toolbar.
6. **Text cannot be selected anywhere in the Studio editor,** in every mode and job, including phones.
   Inputs, text areas and editable text stay selectable.

## What stays

- Phones and tablets (below 1024 px) keep the panes, the Player's own controls and the issues bar under
  the lanes.
- The Story mode and the Review and Render jobs keep their layouts.
- Amended by the operator on 2026-11-09: the player bar of item 4 is also under the video in the Story mode and the Review job, at 1024 px and wider. Render has no preview, and a version 1 draft keeps the Player's own controls while editing.
- No document field, API or migration.

## Calls made while planning (not asked of the operator)

- Mute stays, in the bar. The mock-up left it out, and removing it would take a working control away.
- Clicking the video still plays and pauses. Turning the Player's controls off would otherwise end that.
- The default height is 392 px rather than the mock-up's 384 px, so all seven tracks fit.
