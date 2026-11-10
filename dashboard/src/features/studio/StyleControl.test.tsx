/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import type { AppliedStyleResult, EditDocumentV2 } from "@/api/control-plane";
import { render } from "@/test-render";

import { StyleControl } from "./StyleControl";
import { upgradedTextDocument } from "./timeline-test-fixtures";

afterEach(cleanup);

const STYLES = [
  { template_id: "style_a", name: "Style A", revision: 1 },
  { template_id: "style_b", name: "Style B", revision: 1 },
];

function mount(
  document: EditDocumentV2 = upgradedTextDocument(),
  { disabled = false, refused = null as string | null } = {},
) {
  const applied: unknown[] = [];
  const client = {
    listStyles: mock(async () => STYLES),
    applyStyle: mock(async (_p: string, _d: string, request: { template_id: string; base_revision: number }) => {
      applied.push(request);
      return {
        document: { ...document, revision: document.revision + 1, style: { template_id: request.template_id, revision: 1 } },
        previous_revision: document.revision,
        narration: null,
        narration_refused: refused,
      } as AppliedStyleResult;
    }),
  };
  const onApplied = mock((_result: AppliedStyleResult) => {});
  render(<StyleControl client={client} projectId="project_001" documentId="edoc_1" document={document} disabled={disabled} onApplied={onApplied} />);
  return { client, applied, onApplied };
}

test("the control lists the styles and shows the current one", async () => {
  mount({ ...upgradedTextDocument(), style: { template_id: "style_b", revision: 1 } });
  const select = (await screen.findByLabelText("Style")) as HTMLSelectElement;
  expect(await screen.findByRole("option", { name: "Style B" })).toBeDefined();
  expect(select.value).toBe("style_b");
});

test("choosing a style asks first and Cancel sends nothing", async () => {
  const { applied } = mount();
  fireEvent.change(await screen.findByLabelText("Style"), { target: { value: "style_a" } });
  expect(screen.getByText("Apply Style A?")).toBeDefined();
  expect(screen.getByText(/replaces every edit you made by hand/)).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(applied).toEqual([]);
  expect(screen.queryByText("Apply Style A?")).toBeNull();
});

test("Apply sends applyStyle with the base revision and adopts the result", async () => {
  const document = upgradedTextDocument();
  const { applied, onApplied } = mount(document);
  fireEvent.change(await screen.findByLabelText("Style"), { target: { value: "style_a" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply style" }));
  await screen.findByLabelText("Style");
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(applied).toEqual([{ template_id: "style_a", base_revision: document.revision }]);
  expect(onApplied.mock.calls.length).toBe(1);
});

test("a narration refusal is shown in words", async () => {
  mount(upgradedTextDocument(), { refused: "prompt_not_configured" });
  fireEvent.change(await screen.findByLabelText("Style"), { target: { value: "style_b" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply style" }));
  expect(await screen.findByText(/The style is applied\. The narration cannot start: Choose a model/)).toBeDefined();
});

test("the control is disabled while a narration runs", async () => {
  mount(upgradedTextDocument(), { disabled: true });
  expect(((await screen.findByLabelText("Style")) as HTMLSelectElement).disabled).toBe(true);
});

// Final review (2026-11-10).
test("the style list is read once, not on every render", async () => {
  const listStyles = mock(async () => STYLES);
  const applyStyle = mock(async () => {
    throw new Error("unused");
  });
  const view = (key: number) => (
    <StyleControl
      key="one"
      client={{ listStyles, applyStyle }}
      projectId="project_001"
      documentId="edoc_1"
      document={{ ...upgradedTextDocument(), revision: key }}
      disabled={false}
      onApplied={() => {}}
    />
  );
  const { rerender } = render(view(1));
  await screen.findByRole("option", { name: "Style A" });
  rerender(view(2));
  rerender(view(3));
  expect(listStyles.mock.calls.length).toBe(1);
});

test("the confirmation takes focus, says what it asks, and Escape cancels", async () => {
  const { applied } = mount();
  fireEvent.change(await screen.findByLabelText("Style"), { target: { value: "style_a" } });
  const dialog = screen.getByRole("alertdialog");
  expect(globalThis.document.activeElement).toBe(screen.getByRole("button", { name: "Apply style" }));
  const described = dialog.getAttribute("aria-describedby") ?? "";
  expect(described.split(" ").filter(Boolean).length).toBe(2);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(applied).toEqual([]);
});

test("a beat a re-voice only stretched, because of hand edits, is named", async () => {
  // Operator, 2026-11-10: a hand-edited beat is not re-cut by the style, and says so.
  mount({ ...upgradedTextDocument(), style: { template_id: "style_b", revision: 1, voiced: true, kept: ["main", "reactions"] } } as EditDocumentV2);
  expect(await screen.findByText(/Main, Reactions/)).toBeTruthy();
});

test("no note while the style re-cut every changed beat", async () => {
  mount({ ...upgradedTextDocument(), style: { template_id: "style_b", revision: 1, voiced: true } } as EditDocumentV2);
  await screen.findByRole("option", { name: "Style B" });
  expect(screen.queryByText(/kept your edits/)).toBeNull();
});

test("a note floats over the studio until it is dismissed", async () => {
  // e2e on stage1, 2026-11-10: the header is one row, so notes open in a panel that can be closed.
  mount({ ...upgradedTextDocument(), style: { template_id: "style_b", revision: 1, voiced: true, kept: ["main"] } } as EditDocumentV2);
  await screen.findByText(/Main kept your edits/);
  fireEvent.click(screen.getByRole("button", { name: "Got it" }));
  expect(screen.queryByText(/Main kept your edits/)).toBeNull();
});
