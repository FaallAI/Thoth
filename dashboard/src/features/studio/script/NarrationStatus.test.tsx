/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import { StudioImportRequestError, type NarrationState } from "@/api/control-plane";
import { render } from "@/test-render";

import { NarrationStatus } from "./NarrationStatus";

afterEach(cleanup);

const completed: NarrationState = {
  document_id: "edoc_1",
  workflow_id: "narration/edoc_1/1",
  status: "completed",
  script: {
    beats: [
      { beat: "hook", text: "Satu." },
      { beat: "main", text: "Dua." },
      { beat: "reactions", text: "Tiga." },
      { beat: "footage", text: "Empat." },
    ],
    sfx_cues: [],
  },
  estimate: null,
  unsupported: {},
  stale_beats: [],
  failure_code: null,
};

function client(overrides: Record<string, unknown> = {}) {
  return {
    startNarration: mock(async () => ({ ...completed, status: "transcribing", script: null }) as NarrationState),
    revoiceNarrationBeat: mock(async () => completed),
    restartNarration: mock(async () => ({ ...completed, status: "transcribing", script: null }) as NarrationState),
    ...overrides,
  };
}

function mount(state: NarrationState | null, api = client()) {
  const onChange = mock((_state: NarrationState) => {});
  const onOpenScript = mock(() => {});
  render(
    <NarrationStatus client={api as never} projectId="p" documentId="edoc_1" state={state} variant="block" onChange={onChange} onOpenScript={onOpenScript} />,
  );
  return { api, onChange, onOpenScript };
}

test("a draft without narration offers Create narration", async () => {
  const { api, onChange } = mount(null);

  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Create narration" })));
  expect(api.startNarration).toHaveBeenCalledWith("p", "edoc_1");
  expect(onChange).toHaveBeenCalledTimes(1);
});

test("a failed narration offers Create narration again", () => {
  mount({ ...completed, status: "failed", failure_code: "voice_rejected" });

  expect(screen.getByText("Narration stopped (voice_rejected). You can create it again.")).toBeDefined();
  expect((screen.getByRole("button", { name: "Create narration" }) as HTMLButtonElement).disabled).toBe(false);
});

test("a completed narration reads Narrated · 4 beats and offers re-voice only for stale beats", () => {
  mount(completed);
  expect(screen.getByText("Narrated · 4 beats")).toBeDefined();
  expect(screen.queryByRole("button", { name: /Re-voice/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "Create narration" })).toBeNull();
  cleanup();

  mount({ ...completed, stale_beats: ["main", "reactions"] });
  expect(screen.getByText("2 need re-voice")).toBeDefined();
  expect(screen.getByRole("button", { name: "Re-voice 2 changed beats" })).toBeDefined();
});

test("re-voicing changed beats calls each stale beat in order and stops at the first error", async () => {
  const revoiceNarrationBeat = mock(async (_p: string, _d: string, beat: string) => {
    if (beat === "reactions") throw new StudioImportRequestError(409, "narration_in_progress");
    return { ...completed, status: "voicing" } as NarrationState;
  });
  const api = client({ revoiceNarrationBeat });
  const { onChange } = mount({ ...completed, stale_beats: ["main", "reactions", "footage"] }, api);

  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Re-voice 3 changed beats" })));

  expect(revoiceNarrationBeat.mock.calls.map((call) => call[2])).toEqual(["main", "reactions"]);
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status").textContent).toContain("narration_in_progress");
});

test("Recreate narration asks first", async () => {
  const { api } = mount(completed);

  fireEvent.click(screen.getByRole("button", { name: "Recreate narration…" }));
  expect(api.restartNarration).toHaveBeenCalledTimes(0);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Yes, write a new script" })));
  expect(api.restartNarration).toHaveBeenCalledWith("p", "edoc_1");
});

test("a script awaiting approval opens the script", () => {
  const { onOpenScript } = mount({ ...completed, status: "awaiting_approval" });

  fireEvent.click(screen.getByRole("button", { name: "Script ready to approve" }));
  expect(onOpenScript).toHaveBeenCalledTimes(1);
});
