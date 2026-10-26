// Step sentences (run-progress spec §5, restyle R1).
import { expect, test } from "bun:test";

import { stepText } from "./steps";

test("a step reads as its sentence, with its params filled in", () => {
  expect(stepText("en", { code: "source.fetch_post", stage: "source", params: { platform: "tiktok" } })).toBe(
    "Fetching the post from TikTok",
  );
  expect(stepText("id", { code: "footage.keep_clips", stage: "footage", params: { count: 4 } })).toBe(
    "Klip disimpan: 4",
  );
  expect(
    stepText("en", { code: "assembly.judge_comments", stage: "assembly", total: 12, params: { count: 5 } }),
  ).toBe("Comments kept: 5 of 12");
});

test("each verdict has its own sentence", () => {
  const verdict = (value: string) =>
    stepText("en", { code: "attribution.verdict", stage: "attribution", params: { verdict: value } });
  expect(verdict("original")).toBe("This post is the original");
  expect(verdict("replaced")).toBe("Found the original elsewhere");
  expect(verdict("unresolved")).toBe("No original found");
});

test("an unknown code reads as its stage label, and an unknown stage as itself", () => {
  expect(stepText("en", { code: "footage.something_new", stage: "footage" })).toBe("Collect footage");
  expect(stepText("id", { code: "footage.something_new", stage: "footage" })).toBe("Kumpulkan footage");
  expect(stepText("en", { code: "render.encode", stage: "render" })).toBe("render");
  expect(stepText("en", { code: "attribution.verdict", stage: "attribution", params: { verdict: "odd" } })).toBe(
    "Find the original",
  );
});
