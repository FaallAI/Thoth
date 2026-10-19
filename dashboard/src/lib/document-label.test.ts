/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import { documentLabel } from "./document-label";

test("the label is the first non-empty text heading", () => {
  const document = {
    clips: [{ kind: "video" }, { kind: "text", heading: " " }, { kind: "text", heading: " Kucing " }],
  } as never;
  expect(documentLabel(document)).toBe("Kucing");
});

test("a document without a heading is untitled and long headings are cut", () => {
  expect(documentLabel({ clips: [] } as never)).toBe("Untitled draft");
  expect(documentLabel({ clips: [{ kind: "text", heading: "x".repeat(300) }] } as never)).toHaveLength(120);
});
