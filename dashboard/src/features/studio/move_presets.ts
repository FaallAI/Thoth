import { moveAt, type Ease, type Move } from "@thoth/remotion-composition";

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
      // About a quarter second from the word to 35% closer, then held to the end: Style A's punchline
      // push. It starts from where the moves already are, so nothing jumps; moves after it give way.
      const playhead = Math.min(Math.max(0, Math.round(at)), last);
      const start = Math.max(0, playhead - 1);
      const end = Math.min(playhead + Math.round(0.27 * fps), last);
      const base = moveAt(existing, start);
      const punched = key(end, base.scale * 1.35, "hold", base.x, base.y);
      const added = end > start ? [key(start, base.scale, "ease_out", base.x, base.y), punched] : [punched];
      return [...existing.filter((move) => move.frame < start), ...added];
    }
  }
}
