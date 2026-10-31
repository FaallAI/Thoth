/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import { StudioImportRequestError, type StoredNarrationPreset } from "@/api/control-plane";
import { render } from "@/test-render";

import { NarrationPresetForm, SfxLibrary } from "./NarrationPresetForm";

afterEach(cleanup);

const stored: StoredNarrationPreset = {
  revision: 2,
  preset: {
    language: "id", target_seconds: 45, words_per_second: 3, voice_provider: "elevenlabs",
    voice_id: "plgKUYgnlZ1DCNh54DwJ", voice_model: "eleven_multilingual_v2",
    duck_volume: 0.12, leak_volume: 0.45, lead_in_seconds: 1.6, max_sfx_cues: 3,
  },
};

test("the preset form loads, edits and saves with its revision", async () => {
  const save = mock(async (_p: string, preset: unknown, revision: number) => ({ revision: revision + 1, preset }) as StoredNarrationPreset);
  const client = { getNarrationPreset: mock(async () => stored), saveNarrationPreset: save };
  await act(async () => { render(<NarrationPresetForm client={client as never} projectId="p" />); });

  fireEvent.change(screen.getByLabelText("Target length (seconds)"), { target: { value: "30" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save preset" })));

  expect(save).toHaveBeenCalledTimes(1);
  expect(save.mock.calls[0]![2]).toBe(2);
  expect((save.mock.calls[0]![1] as { target_seconds: number }).target_seconds).toBe(30);
  expect(screen.getByRole("status").textContent).toBe("Preset saved");
});

test("a preset saved elsewhere first is reported as a conflict", async () => {
  const client = {
    getNarrationPreset: mock(async () => stored),
    saveNarrationPreset: mock(async () => { throw new StudioImportRequestError(409, "narration_preset_conflict"); }),
  };
  await act(async () => { render(<NarrationPresetForm client={client as never} projectId="p" />); });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save preset" })));
  expect(screen.getByRole("status").textContent).toBe("Someone saved the preset first. Reload to see it.");
});

test("the sound effect library lists each entry with its licence, or says it is empty", async () => {
  const client = { listSfx: mock(async () => [{ sfx_id: "whoosh", file_name: "whoosh.mp3", duration_seconds: 1.2, labels: { licence: "CC0-1.0", category: "transition" } }]) };
  await act(async () => { render(<SfxLibrary client={client as never} />); });
  expect(screen.getByText("whoosh")).toBeTruthy();
  expect(screen.getByText("Licence CC0-1.0")).toBeTruthy();
  cleanup();

  await act(async () => { render(<SfxLibrary client={{ listSfx: async () => [] } as never} />); });
  expect(screen.getByText("No licensed sound effects are in the library yet.")).toBeTruthy();
});
