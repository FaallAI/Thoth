/**
 * Clip moves: keyframed scale and place, and how edits keep them in place (spec 2026-11-09, 3.1).
 *
 * Frames are timeline frames relative to the clip's start. The control plane's `clip_moves.py`
 * follows the same rules; `move_cases.json` holds the cases both run.
 */

export type Ease = "linear" | "ease_out" | "ease_in_out" | "hold";
export type Move = { frame: number; scale: number; x: number; y: number; ease: Ease };
export type MoveValue = { scale: number; x: number; y: number };

export function ease(kind: Ease, t: number): number {
  if (kind === "linear") return t;
  if (kind === "ease_out") return 1 - (1 - t) ** 2;
  if (kind === "ease_in_out") return t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
  return 0;
}

const valueOf = (move: Move): MoveValue => ({ scale: move.scale, x: move.x, y: move.y });

function segmentOf(moves: readonly Move[], frame: number): Move {
  const before = moves.filter((move) => move.frame <= frame);
  return before.at(-1) ?? moves[0]!;
}

/** Scale and place at a frame; no moves is the clip's own placement. */
export function moveAt(moves: readonly Move[] | undefined, frame: number): MoveValue {
  if (!moves || moves.length === 0) return { scale: 1, x: 0, y: 0 };
  const first = moves[0]!;
  const last = moves.at(-1)!;
  if (frame <= first.frame) return valueOf(first);
  if (frame >= last.frame) return valueOf(last);
  for (let index = 0; index + 1 < moves.length; index += 1) {
    const start = moves[index]!;
    const end = moves[index + 1]!;
    if (start.frame <= frame && frame < end.frame) {
      const t = ease(start.ease, (frame - start.frame) / (end.frame - start.frame));
      return {
        scale: start.scale + (end.scale - start.scale) * t,
        x: start.x + (end.x - start.x) * t,
        y: start.y + (end.y - start.y) * t,
      };
    }
  }
  return valueOf(last);
}

function keyframeAt(moves: readonly Move[], frame: number, easeOf: Ease, at = 0): Move {
  return { frame: at, ...moveAt(moves, frame), ease: easeOf };
}

/** The clip's start moved by `delta` frames; the picture at the new start stays as it was. */
export function shiftMoves(moves: readonly Move[], delta: number): Move[] {
  if (moves.length === 0) return [];
  const kept = moves.filter((move) => move.frame >= delta).map((move) => ({ ...move, frame: move.frame - delta }));
  const dropped = moves.filter((move) => move.frame < delta);
  if (dropped.length > 0 && (kept.length === 0 || kept[0]!.frame !== 0)) {
    kept.unshift(keyframeAt(moves, delta, dropped.at(-1)!.ease));
  }
  return kept;
}

/** Each part keeps its own keyframes; the cut holds the value it had there. */
export function splitMoves(moves: readonly Move[], at: number): [Move[], Move[]] {
  if (moves.length === 0) return [[], []];
  let left = moves.filter((move) => move.frame < at).map((move) => ({ ...move }));
  if (left.length === 0) left = [keyframeAt(moves, 0, moves[0]!.ease)];
  else if (left.length < moves.length && left.at(-1)!.frame !== at - 1) {
    left.push(keyframeAt(moves, at - 1, segmentOf(moves, at - 1).ease, at - 1));
  }
  return [left, shiftMoves(moves, at)];
}

/** A clip retimed from `old` to `next` frames: its moves stretch with it. */
export function stretchMoves(moves: readonly Move[], old: number, next: number): Move[] {
  if (moves.length === 0 || old <= 0 || old === next) return moves.map((move) => ({ ...move }));
  const stretched: Move[] = [];
  for (const move of moves) {
    const frame = Math.min(Math.floor((move.frame * next) / old), next - 1);
    if (stretched.length === 0 || frame > stretched.at(-1)!.frame) stretched.push({ ...move, frame });
  }
  return stretched;
}

/** Moves past a clip's end are dropped; its last frame holds the value it had there. */
export function fitMoveList(moves: readonly Move[], duration: number): Move[] {
  if (moves.length === 0 || moves.at(-1)!.frame < duration) return moves.map((move) => ({ ...move }));
  const kept = moves.filter((move) => move.frame < duration).map((move) => ({ ...move }));
  if (kept.length === 0 || kept.at(-1)!.frame !== duration - 1) {
    kept.push(keyframeAt(moves, duration - 1, segmentOf(moves, duration - 1).ease, duration - 1));
  }
  return kept;
}
