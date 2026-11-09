/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import { render } from "@/test-render";

import { PreviewControls } from "./PreviewControls";
import { formatTimecode } from "./timeline_domain";
import type { PlayerTimelineRef } from "./usePlayerTimeline";

afterEach(cleanup);

function fakePlayer(overrides: Partial<PlayerTimelineRef> = {}) {
  const listeners: Record<string, ((event: unknown) => void) | undefined> = {};
  const player = {
    addEventListener: (type: string, listener: (event: unknown) => void) => {
      listeners[type] = listener;
    },
    removeEventListener: (type: string) => {
      listeners[type] = undefined;
    },
    getCurrentFrame: () => 0,
    seekTo: () => {},
    play: () => {},
    pause: () => {},
    // Like Remotion's: the change arrives later, through the mutechange event.
    mute: mock(() => {}),
    unmute: mock(() => {}),
    requestFullscreen: mock(() => {}),
    isFullscreen: () => false,
    ...overrides,
  };
  return { player, listeners };
}

function mount(player: PlayerTimelineRef | null, playing = false) {
  const onPlay = mock(() => {});
  const onPause = mock(() => {});
  const onFullscreenChange = mock((_fullscreen: boolean) => {});
  const view = render(
    <PreviewControls
      player={player}
      frame={180}
      durationInFrames={825}
      fps={30}
      playing={playing}
      canvas={{ width: 1080, height: 1920 }}
      onPlay={onPlay}
      onPause={onPause}
      onFullscreenChange={onFullscreenChange}
    />,
  );
  return { onPlay, onPause, onFullscreenChange, ...view };
}

test("the time and the canvas are shown", () => {
  mount(fakePlayer().player);
  expect(screen.getByText(`${formatTimecode(180, 30)} / ${formatTimecode(825, 30)}`)).toBeDefined();
  expect(screen.getByText("9:16 · 1080×1920")).toBeDefined();
});

test("play and pause call the timeline's handlers", () => {
  const stopped = mount(fakePlayer().player, false);
  fireEvent.click(screen.getByRole("button", { name: "Play video" }));
  expect(stopped.onPlay).toHaveBeenCalledTimes(1);
  cleanup();
  const running = mount(fakePlayer().player, true);
  fireEvent.click(screen.getByRole("button", { name: "Pause video" }));
  expect(running.onPause).toHaveBeenCalledTimes(1);
});

test("mute toggles and the label follows", () => {
  const { player, listeners } = fakePlayer();
  mount(player);
  fireEvent.click(screen.getByRole("button", { name: "Mute sound" }));
  expect(player.mute).toHaveBeenCalledTimes(1);
  act(() => listeners.mutechange!({ detail: { isMuted: true } }));
  fireEvent.click(screen.getByRole("button", { name: "Unmute sound" }));
  expect(player.unmute).toHaveBeenCalledTimes(1);
  act(() => listeners.mutechange!({ detail: { isMuted: false } }));
  expect(screen.getByRole("button", { name: "Mute sound" })).toBeDefined();
});

test("fullscreen asks the player", () => {
  const { player } = fakePlayer();
  mount(player);
  fireEvent.click(screen.getByRole("button", { name: "Enter Fullscreen" }));
  expect(player.requestFullscreen).toHaveBeenCalledTimes(1);
});

test("a refused fullscreen is not an error", () => {
  const { player } = fakePlayer({
    requestFullscreen: () => {
      throw new Error("not allowed");
    },
  });
  mount(player);
  expect(() => fireEvent.click(screen.getByRole("button", { name: "Enter Fullscreen" }))).not.toThrow();
});

test("no player yet leaves the buttons off", () => {
  mount(null);
  expect((screen.getByRole("button", { name: "Mute sound" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Enter Fullscreen" }) as HTMLButtonElement).disabled).toBe(true);
});

test("a bar that appears during fullscreen says so, and leaving says it no longer counts", () => {
  const { player } = fakePlayer({ isFullscreen: () => true });
  const { onFullscreenChange, unmount } = mount(player);
  expect(onFullscreenChange).toHaveBeenLastCalledWith(true);
  unmount();
  expect(onFullscreenChange).toHaveBeenLastCalledWith(false);
});

test("the player's fullscreen state is reported", () => {
  const { player, listeners } = fakePlayer();
  const { onFullscreenChange, unmount } = mount(player);
  listeners.fullscreenchange!({ detail: { isFullscreen: true } });
  expect(onFullscreenChange).toHaveBeenLastCalledWith(true);
  unmount();
  expect(listeners.fullscreenchange).toBeUndefined();
});

test("a browser that does not allow fullscreen leaves the button off", () => {
  Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: false });
  try {
    const { player } = fakePlayer();
    mount(player);
    const button = screen.getByRole("button", { name: "Enter Fullscreen" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  } finally {
    delete (document as unknown as Record<string, unknown>).fullscreenEnabled;
  }
});
