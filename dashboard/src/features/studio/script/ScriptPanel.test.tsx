/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import type { NarrationState } from "@/api/control-plane";
import { render } from "@/test-render";

import { ScriptPanel } from "./ScriptPanel";

afterEach(cleanup);

const awaiting: NarrationState = {
  document_id: "edoc_1",
  workflow_id: "narration/edoc_1/1",
  status: "awaiting_approval",
  script: {
    beats: [
      { beat: "hook", text: "Kucing ini bikin heboh." },
      { beat: "main", text: "Kata Andi, ikan diambil." },
    ],
    sfx_cues: [{ sfx_id: "whoosh", beat: "main", moment: "comment_appear", word_index: null }],
  },
  estimate: { characters: 48, provider: "elevenlabs", voice_id: "plgK", usd: null },
  unsupported: { main: ["Andi"] },
  stale_beats: [],
  failure_code: null,
};

function client(overrides: Record<string, unknown> = {}) {
  return {
    startNarration: mock(async () => ({ ...awaiting, status: "transcribing", script: null }) as NarrationState),
    decideNarration: mock(async () => awaiting),
    editNarrationBeat: mock(async () => awaiting.script!),
    revoiceNarrationBeat: mock(async () => awaiting),
    cancelNarration: mock(async () => ({ ...awaiting, status: "cancelled" }) as NarrationState),
    restartNarration: mock(async () => ({ ...awaiting, status: "transcribing", script: null }) as NarrationState),
    ...overrides,
  };
}

test("the approval shows the script read-only with the estimate and the unsupported words", async () => {
  const api = client();
  render(<ScriptPanel client={api as never} projectId="p" documentId="edoc_1" state={awaiting} onChange={() => {}} />);

  expect(screen.queryByRole("textbox", { name: /Hook/ })).toBeNull();
  expect(screen.getByText("48 characters · elevenlabs · voice plgK")).toBeTruthy();
  expect(screen.getByText("Unpriced")).toBeTruthy();
  expect(screen.getByTitle("Not found in the evidence").textContent).toBe("Andi");
  expect(screen.getByText(/whoosh/)).toBeTruthy();

  fireEvent.change(screen.getByLabelText("Note for the next script (optional)"), { target: { value: "Hook kurang tajam" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Reject" })));
  expect(api.decideNarration).toHaveBeenCalledWith("p", "edoc_1", { decision: "reject", note: "Hook kurang tajam" });
});

test("approving sends one decision", async () => {
  const api = client();
  render(<ScriptPanel client={api as never} projectId="p" documentId="edoc_1" state={awaiting} onChange={() => {}} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Approve and voice" })));
  expect(api.decideNarration).toHaveBeenCalledWith("p", "edoc_1", { decision: "approve", note: null });
});

test("a completed script is editable and a stale beat can be re-voiced", async () => {
  const api = client();
  const completed: NarrationState = { ...awaiting, status: "completed", stale_beats: ["main"] };
  render(<ScriptPanel client={api as never} projectId="p" documentId="edoc_1" state={completed} onChange={() => {}} />);

  expect(screen.getByText("1 beats out of date")).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "Hook" }), { target: { value: "Baru" } });
  await act(async () => fireEvent.click(screen.getAllByRole("button", { name: "Save line" })[0]!));
  expect(api.editNarrationBeat).toHaveBeenCalledWith("p", "edoc_1", "hook", "Baru");
  fireEvent.click(screen.getByRole("button", { name: "Re-voice" }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Yes, re-voice 1 beats" })));
  expect(api.revoiceNarrationBeat).toHaveBeenCalledWith("p", "edoc_1", "main");
});

test("re-voicing one beat shows its characters and price first, and spends nothing until confirmed", () => {
  // Every re-voice is a paid ElevenLabs call (operator, 2026-11-01): the cost shows before any voice.
  const api = client();
  const priced: NarrationState = {
    ...awaiting,
    status: "completed",
    stale_beats: ["main"],
    estimate: { characters: 48, provider: "elevenlabs", voice_id: "plgK", usd: 0.48 },
  };
  render(<ScriptPanel client={api as never} projectId="p" documentId="edoc_1" state={priced} onChange={() => {}} />);

  fireEvent.click(screen.getByRole("button", { name: "Re-voice" }));
  // "Kata Andi, ikan diambil." is 24 of the script's 48 characters: half of $0.48.
  expect(screen.getByText("1 beats · 24 characters · about $0.24")).toBeDefined();
  expect(api.revoiceNarrationBeat).toHaveBeenCalledTimes(0);
  fireEvent.click(screen.getByRole("button", { name: "Not now" }));
  expect(screen.queryByRole("button", { name: "Yes, re-voice 1 beats" })).toBeNull();
  expect(api.revoiceNarrationBeat).toHaveBeenCalledTimes(0);
});

test("a running narration shows its step and the Indonesian strings exist", () => {
  render(<ScriptPanel client={client() as never} projectId="p" documentId="edoc_1" state={{ ...awaiting, status: "voicing" }} onChange={() => {}} />, { locale: "id" });
  expect(screen.getByText("Membuat suara tiap beat")).toBeTruthy();
});

test("useNarration polls while the narration runs and reports when it completes", async () => {
  const { renderHook, waitFor } = await import("@testing-library/react");
  const { useNarration } = await import("./useNarration");
  const states: NarrationState[] = [
    { ...awaiting, status: "writing" },
    { ...awaiting, status: "completed" },
  ];
  const getNarration = mock(async () => states.shift() ?? { ...awaiting, status: "completed" });
  const onCompleted = mock(() => {});
  const { result } = renderHook(() =>
    useNarration({ getNarration } as never, "p", "edoc_1", true, onCompleted, 5),
  );
  await waitFor(() => expect(result.current[0]?.status).toBe("completed"));
  expect(onCompleted).toHaveBeenCalledTimes(1);
});


test("a running or waiting narration can be cancelled", async () => {
  const api = client();
  const onChange = mock((_state: NarrationState) => {});
  render(<ScriptPanel client={api as never} projectId="p" documentId="edoc_1" state={awaiting} onChange={onChange} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Cancel narration" })));
  expect(api.cancelNarration).toHaveBeenCalledWith("p", "edoc_1");
  expect(onChange.mock.calls[0]![0].status).toBe("cancelled");
});

test("adopting the narrated revision drops the edits queued during the lock", async () => {
  const { adoptNarratedRevision } = await import("./useNarration");
  const actions: unknown[] = [];
  const latest = { revision: 7 } as never;
  adoptNarratedRevision((action) => actions.push(action), latest);
  expect(actions).toEqual([{ type: "save_conflicted", latest }, { type: "reload_latest" }]);
});

test("polling keeps going after a failed read", async () => {
  const { renderHook, waitFor } = await import("@testing-library/react");
  const { useNarration } = await import("./useNarration");
  let calls = 0;
  const getNarration = mock(async () => {
    calls += 1;
    if (calls === 1) return { ...awaiting, status: "writing" } as NarrationState;
    if (calls === 2) throw new Error("503");
    return { ...awaiting, status: "completed" } as NarrationState;
  });
  const { result } = renderHook(() => useNarration({ getNarration } as never, "p", "edoc_1", true, () => {}, 5));
  await waitFor(() => expect(result.current[0]?.status).toBe("completed"));
});


test("a finished narration is recreated only after a confirmation", async () => {
  const api = client();
  const onChange = mock((_state: NarrationState) => {});
  render(<ScriptPanel client={api as never} projectId="p" documentId="edoc_1" state={{ ...awaiting, status: "completed" }} onChange={onChange} />);

  fireEvent.click(screen.getByRole("button", { name: "Recreate narration" }));
  expect(api.restartNarration).not.toHaveBeenCalled();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Yes, write a new script" })));
  expect(api.restartNarration).toHaveBeenCalledWith("p", "edoc_1");
  expect(onChange.mock.calls[0]![0].status).toBe("transcribing");
});
