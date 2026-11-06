/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import { StudioImportRequestError, type NarrationState } from "@/api/control-plane";
import { render } from "@/test-render";

import { NarrationStatus, narrationAttention } from "./NarrationStatus";

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
    getNarration: mock(async () => completed),
    ...overrides,
  };
}

function mount(state: NarrationState | null, api = client()) {
  const onChange = mock((_state: NarrationState) => {});
  const onOpenScript = mock(() => {});
  render(
    <NarrationStatus client={api as never} projectId="p" documentId="edoc_1" state={state} variant="block" onChange={onChange} onOpenScript={onOpenScript} pollMs={1} />,
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

  fireEvent.click(screen.getByRole("button", { name: "Re-voice 3 changed beats" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Yes, re-voice 3 beats" }));
    await new Promise((resolve) => setTimeout(resolve, 20));
  });

  expect(revoiceNarrationBeat.mock.calls.map((call) => call[2])).toEqual(["main", "reactions"]);
  // Main's voicing state, then its completed read-back; Reactions is refused.
  expect(onChange).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("status").textContent).toContain("already running");
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

test("re-voicing changed beats first shows their characters and price, and spends nothing until confirmed", () => {
  // Every re-voice is a paid ElevenLabs call (operator, 2026-11-01): the cost shows before any voice.
  const api = client();
  mount({ ...completed, stale_beats: ["main", "footage"], estimate: { characters: 21, provider: "elevenlabs", voice_id: "plgK", usd: 0.42 } }, api);

  fireEvent.click(screen.getByRole("button", { name: "Re-voice 2 changed beats" }));
  // "Dua." and "Empat." are 10 of the script's 21 characters: 10/21 of $0.42 is $0.20.
  expect(screen.getByText("2 beats · 10 characters · about $0.20")).toBeDefined();
  expect(api.revoiceNarrationBeat).toHaveBeenCalledTimes(0);
  fireEvent.click(screen.getByRole("button", { name: "Not now" }));
  expect(screen.queryByRole("button", { name: "Yes, re-voice 2 beats" })).toBeNull();
  expect(api.revoiceNarrationBeat).toHaveBeenCalledTimes(0);
});

test("an unpriced re-voice says so before it is confirmed", () => {
  mount({ ...completed, stale_beats: ["main"] });

  fireEvent.click(screen.getByRole("button", { name: "Re-voice 1 changed beats" }));
  expect(screen.getByText("1 beats · 4 characters · No price set yet")).toBeDefined();
});

test("re-voicing changed beats waits for each beat to finish before the next", async () => {
  // The server takes one re-voice at a time: a re-voice moves the narration to voicing until it
  // is written, and refuses another meanwhile (side-agent note, 2026-11-01).
  const events: string[] = [];
  let reads = 0;
  const revoiceNarrationBeat = mock(async (_p: string, _d: string, beat: string) => {
    events.push(`revoice ${beat}`);
    return { ...completed, status: "voicing" } as NarrationState;
  });
  const getNarration = mock(async () => {
    reads += 1;
    events.push("read");
    // Each re-voice is still voicing on its first read and done on the second.
    return (reads % 2 === 1 ? { ...completed, status: "voicing" } : { ...completed, stale_beats: reads === 2 ? ["reactions"] : [] }) as NarrationState;
  });
  mount({ ...completed, stale_beats: ["main", "reactions"] }, client({ revoiceNarrationBeat, getNarration }));

  fireEvent.click(screen.getByRole("button", { name: "Re-voice 2 changed beats" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Yes, re-voice 2 beats" }));
    await new Promise((resolve) => setTimeout(resolve, 50));
  });

  expect(events).toEqual(["revoice main", "read", "read", "revoice reactions", "read", "read"]);
  expect(screen.queryByRole("status")).toBeNull();
});

test("re-voicing stops when a beat's re-voice fails", async () => {
  // A failed re-voice ends "completed" with a failure code (NarrationRevoiceWorkflow), never "failed".
  const revoiceNarrationBeat = mock(async () => ({ ...completed, status: "voicing" }) as NarrationState);
  const getNarration = mock(async () => ({ ...completed, stale_beats: ["main", "reactions"], failure_code: "revoice_failed" }) as NarrationState);
  mount({ ...completed, stale_beats: ["main", "reactions"] }, client({ revoiceNarrationBeat, getNarration }));

  fireEvent.click(screen.getByRole("button", { name: "Re-voice 2 changed beats" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Yes, re-voice 2 beats" }));
    await new Promise((resolve) => setTimeout(resolve, 20));
  });

  expect(revoiceNarrationBeat).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status").textContent).toContain("could not be voiced");
});

test("leaving Studio stops the re-voice: no more reads and no more paid beats", async () => {
  // Final review, Important 2: the wait loop outlived the component that started it.
  const revoiceNarrationBeat = mock(async () => ({ ...completed, status: "voicing" }) as NarrationState);
  const getNarration = mock(async () => ({ ...completed, status: "voicing" }) as NarrationState);
  const api = client({ revoiceNarrationBeat, getNarration });
  const { unmount } = render(
    <NarrationStatus client={api as never} projectId="p" documentId="edoc_1" state={{ ...completed, stale_beats: ["main", "reactions"] }} variant="block" onChange={() => {}} onOpenScript={() => {}} pollMs={1} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Re-voice 2 changed beats" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Yes, re-voice 2 beats" }));
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
  unmount();
  const reads = getNarration.mock.calls.length;
  await new Promise((resolve) => setTimeout(resolve, 30));

  expect(getNarration.mock.calls.length).toBeLessThanOrEqual(reads + 1);
  expect(revoiceNarrationBeat).toHaveBeenCalledTimes(1);
});

test("the script opens for a new or recreated narration, never for a re-voice", async () => {
  // Final review, minor 1: the Script panel reopened on every read during a bulk re-voice.
  const onStarted = mock(() => {});
  const api = client({ getNarration: mock(async () => ({ ...completed, stale_beats: [] }) as NarrationState) });
  const { rerender } = render(
    <NarrationStatus client={api as never} projectId="p" documentId="edoc_1" state={null} variant="block" onChange={() => {}} onOpenScript={() => {}} onStarted={onStarted} pollMs={1} />,
  );
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Create narration" })));
  expect(onStarted).toHaveBeenCalledTimes(1);

  rerender(
    <NarrationStatus client={api as never} projectId="p" documentId="edoc_1" state={{ ...completed, stale_beats: ["main"] }} variant="block" onChange={() => {}} onOpenScript={() => {}} onStarted={onStarted} pollMs={1} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Re-voice 1 changed beats" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Yes, re-voice 1 beats" }));
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(onStarted).toHaveBeenCalledTimes(1);
});

test("a re-voice reports each beat's start and end, not every read in between", async () => {
  // Final review, minor 2: Studio's own poller owns the reads in between.
  let reads = 0;
  const getNarration = mock(async () => (++reads < 3 ? { ...completed, status: "voicing" } : { ...completed, stale_beats: [] }) as NarrationState);
  const { onChange } = mount({ ...completed, stale_beats: ["main"] }, client({ revoiceNarrationBeat: mock(async () => ({ ...completed, status: "voicing" }) as NarrationState), getNarration }));

  fireEvent.click(screen.getByRole("button", { name: "Re-voice 1 changed beats" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Yes, re-voice 1 beats" }));
    await new Promise((resolve) => setTimeout(resolve, 30));
  });

  expect(reads).toBe(3);
  expect(onChange.mock.calls.map(([state]) => state.status)).toEqual(["voicing", "completed"]);
});

test("the menu dot means a re-voice waits in the menu: completed, stale, and below 1440", () => {
  // Final review, minor 3.
  const stale = { ...completed, stale_beats: ["main"] } as NarrationState;
  expect(narrationAttention(stale, "compact_desktop")).toBe(true);
  expect(narrationAttention(stale, "full_desktop")).toBe(false);
  expect(narrationAttention({ ...stale, status: "voicing" }, "compact_desktop")).toBe(false);
  expect(narrationAttention(completed, "compact_desktop")).toBe(false);
  expect(narrationAttention(null, "phone")).toBe(false);
});

test("in the header a stopped narration is one chip, its reason and Create behind it", () => {
  // Final review, minor 4: three stacked lines overflowed the 56 px header at 1440.
  render(
    <NarrationStatus client={client() as never} projectId="p" documentId="edoc_1" state={{ ...completed, status: "failed", failure_code: "voice_rejected" }} variant="chip" onChange={() => {}} onOpenScript={() => {}} />,
  );
  expect(screen.getByText("Narration stopped")).toBeDefined();
  expect(screen.getByRole("button", { name: "Create narration" }).closest("details")).not.toBeNull();
  cleanup();

  render(<NarrationStatus client={client() as never} projectId="p" documentId="edoc_1" state={null} variant="chip" onChange={() => {}} onOpenScript={() => {}} />);
  expect(screen.getByRole("button", { name: "Create narration" }).closest("details")).toBeNull();
});

test("one button opens and closes the script, also while a narration runs", () => {
  // e2e audit 2026-11-02: the menu had both "Script" and "Open script".
  const onOpenScript = mock(() => {});
  const onCloseScript = mock(() => {});
  const show = (state: NarrationState, scriptOpen: boolean) =>
    render(<NarrationStatus client={client() as never} projectId="p" documentId="edoc_1" state={state} variant="block" onChange={() => {}} onOpenScript={onOpenScript} onCloseScript={onCloseScript} scriptOpen={scriptOpen} />);

  show({ ...completed, status: "voicing" }, false);
  fireEvent.click(screen.getByRole("button", { name: "Open script" }));
  expect(onOpenScript).toHaveBeenCalledTimes(1);
  cleanup();

  show(completed, true);
  expect(screen.queryByRole("button", { name: "Open script" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Close script" }));
  expect(onCloseScript).toHaveBeenCalledTimes(1);
});

test("Open script closes the chip's menu, which would cover the canvas controls", () => {
  // e2e 2026-11-02: the menu stayed open over Safe zone with the script panel beside it.
  const { container } = render(
    <NarrationStatus client={client() as never} projectId="p" documentId="edoc_1" state={completed} variant="chip" onChange={() => {}} onOpenScript={() => {}} />,
  );
  const menu = container.querySelector("details")!;
  menu.open = true;

  fireEvent.click(screen.getByRole("button", { name: "Open script" }));

  expect(menu.open).toBe(false);
});

const refusedWith = async (code: string) => {
  const api = client();
  api.startNarration = mock(async () => {
    throw new StudioImportRequestError(409, code);
  }) as never;
  mount(null, api);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Create narration" }));
  });
  return screen.getByRole("status").textContent ?? "";
};

test("a refusal says what to do in words, never its raw code", async () => {
  const text = await refusedWith("narration_not_available");
  expect(text).toContain("made from a finished run");
  expect(text).not.toContain("narration_not_available");
});

test("a missing model points to Presets", async () => {
  const text = await refusedWith("prompt_not_configured");
  expect(text).toContain("Presets");
  expect(text).not.toContain("prompt_not_configured");
});

test("a refusal nobody named still shows no code", async () => {
  const text = await refusedWith("something_new");
  expect(text).not.toContain("something_new");
  expect(text.length).toBeGreaterThan(0);
});
