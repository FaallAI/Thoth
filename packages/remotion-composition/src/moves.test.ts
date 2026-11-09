/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import cases from "./move_cases.json";
import { fitMoveList, moveAt, shiftMoves, splitMoves, stretchMoves, type Move } from "./moves";

type Case = { name: string; op: string; moves: Move[]; args: Record<string, number>; expect: unknown };

function expectMoves(actual: Move[], expected: Move[]) {
  expect(actual.map((move) => ({ ...move, scale: Number(move.scale.toFixed(9)), x: Number(move.x.toFixed(9)), y: Number(move.y.toFixed(9)) }))).toEqual(
    expected.map((move) => ({ ...move, scale: Number(move.scale.toFixed(9)), x: Number(move.x.toFixed(9)), y: Number(move.y.toFixed(9)) })),
  );
}

for (const entry of (cases as unknown as { cases: Case[] }).cases) {
  test(`shared move case: ${entry.name}`, () => {
    const { moves, args } = entry;
    if (entry.op === "at") {
      const value = moveAt(moves, args.frame!);
      const [scale, x, y] = entry.expect as number[];
      expect(value.scale).toBeCloseTo(scale!, 9);
      expect(value.x).toBeCloseTo(x!, 9);
      expect(value.y).toBeCloseTo(y!, 9);
    } else if (entry.op === "shift") {
      expectMoves(shiftMoves(moves, args.delta!), entry.expect as Move[]);
    } else if (entry.op === "split") {
      const [left, right] = splitMoves(moves, args.at!);
      const [expectedLeft, expectedRight] = entry.expect as Move[][];
      expectMoves(left, expectedLeft!);
      expectMoves(right, expectedRight!);
    } else if (entry.op === "stretch") {
      expectMoves(stretchMoves(moves, args.old!, args.new!), entry.expect as Move[]);
    } else if (entry.op === "fit") {
      expectMoves(fitMoveList(moves, args.duration!), entry.expect as Move[]);
    } else {
      throw new Error(`unknown case op ${entry.op}`);
    }
  });
}
