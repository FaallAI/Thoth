import type { Ease, Move } from "@thoth/remotion-composition";

/** The camera moves Studio offers as one click each (spec 2026-11-09, 3.7). */
export type MovePresetKind = "punch_in" | "push_in" | "pan_across" | "scroll_down" | "pull_out";

export const MOVE_PRESETS: MovePresetKind[] = ["punch_in", "push_in", "pan_across", "scroll_down", "pull_out"];

/** The presets that need no playhead, so Story can offer them per beat. */
export const BEAT_MOVE_PRESETS: MovePresetKind[] = ["push_in", "pan_across", "scroll_down", "pull_out"];

const key = (frame: number, scale: number, ease: Ease, x = 0, y = 0): Move => ({ frame, scale, x, y, ease });

/**
 * A preset's keyframes for a clip `duration` frames long, at `fps`. Every preset replaces the clip's
 * moves except Punch in, which joins them at `at` (the playhead, relative to the clip).
 */
export function movePreset(
  kind: MovePresetKind,
  duration: number,
  fps: number,
  at = 0,
  existing: readonly Move[] = [],
): Move[] {
  const last = Math.max(0, duration - 1);
  switch (kind) {
    case "push_in":
      return [key(0, 1, "linear"), key(last, 1.12, "linear")];
    case "pan_across":
      return [key(0, 1.15, "linear", 0.06), key(last, 1.15, "linear", -0.06)];
    case "scroll_down":
      return [key(0, 1.6, "ease_in_out", 0, 0.3), key(last, 1.6, "ease_in_out", 0, -0.3)];
    case "pull_out":
      return [key(0, 1.2, "ease_out"), key(last, 1, "ease_out")];
    case "punch_in": {
      // About a quarter second from the word to 135%, then held: Style A's punchline push.
      const playhead = Math.min(Math.max(0, Math.round(at)), last);
      const start = Math.max(0, playhead - 1);
      const end = Math.min(playhead + Math.round(0.27 * fps), last);
      const added = end > start ? [key(start, 1, "ease_out"), key(end, 1.35, "hold")] : [key(start, 1.35, "hold")];
      const frames = new Set(added.map((move) => move.frame));
      return [...existing.filter((move) => !frames.has(move.frame)), ...added].sort((a, b) => a.frame - b.frame);
    }
  }
}
