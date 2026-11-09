// Studio's keyboard (spec 2026-11-08 §5.1): Clipchamp's grammar, never while a person types.
import { useEffect, useRef } from "react";

/** A target where a key types or changes a value, so a shortcut must leave it alone. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target.getAttribute("contenteditable") === "true") return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) return !["checkbox", "radio", "button", "submit", "reset", "range"].includes(target.type);
  return false;
}

export type TimelineKey =
  | "delete"
  | "ripple_delete"
  | "split"
  | "play"
  | "start"
  | "end"
  | "frame_back"
  | "frame_forward"
  | "second_back"
  | "second_forward"
  | "zoom_in"
  | "zoom_out"
  | "zoom_fit"
  | "select_all"
  | "copy"
  | "paste"
  | "duplicate"
  | "shuttle_back"
  | "shuttle_stop"
  | "shuttle_forward"
  | "clear";

type Keys = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">;

export function timelineKey(event: Keys): TimelineKey | null {
  const mod = event.ctrlKey || event.metaKey;
  if (event.altKey) return null;
  if (mod) {
    if (event.key === "=" || event.key === "+") return "zoom_in";
    if (event.key === "-") return "zoom_out";
    if (event.key === "0") return "zoom_fit";
    const letter = event.key.toLowerCase();
    if (letter === "a" && !event.shiftKey) return "select_all";
    if (letter === "c" && !event.shiftKey) return "copy";
    if (letter === "v" && !event.shiftKey) return "paste";
    if (letter === "d" && !event.shiftKey) return "duplicate";
    return null;
  }
  switch (event.key) {
    case "Delete":
      return event.shiftKey ? "ripple_delete" : "delete";
    case "Backspace":
      return event.shiftKey ? "ripple_delete" : "delete";
    case "s":
    case "S":
      return "split";
    case " ":
      return "play";
    case "Home":
      return "start";
    case "End":
      return "end";
    case "ArrowLeft":
      return event.shiftKey ? "second_back" : "frame_back";
    case "ArrowRight":
      return event.shiftKey ? "second_forward" : "frame_forward";
    case "Escape":
      return "clear";
    case "j":
    case "J":
      return "shuttle_back";
    case "k":
    case "K":
      return "shuttle_stop";
    case "l":
    case "L":
      return "shuttle_forward";
    default:
      return null;
  }
}

export type ShortcutAction = TimelineKey | "undo" | "redo" | "shortcuts" | "zoom_wheel" | "open_menu" | "slip_drag" | "roll_drag";
export type ShortcutGroup = "editing" | "playback" | "view" | "studio";

/** The one list the menus and the shortcut dialog both read, so the two never drift. */
export const SHORTCUTS: readonly { action: ShortcutAction; keys: string; group: ShortcutGroup }[] = [
  { action: "delete", keys: "Delete / Backspace", group: "editing" },
  { action: "ripple_delete", keys: "Shift+Delete", group: "editing" },
  { action: "split", keys: "S", group: "editing" },
  { action: "undo", keys: "Ctrl+Z", group: "editing" },
  { action: "redo", keys: "Ctrl+Y / Ctrl+Shift+Z", group: "editing" },
  { action: "select_all", keys: "Ctrl+A", group: "editing" },
  { action: "copy", keys: "Ctrl+C", group: "editing" },
  { action: "paste", keys: "Ctrl+V", group: "editing" },
  { action: "duplicate", keys: "Ctrl+D", group: "editing" },
  { action: "slip_drag", keys: "Alt+drag", group: "editing" },
  { action: "roll_drag", keys: "Alt+drag", group: "editing" },
  { action: "clear", keys: "Esc", group: "editing" },
  { action: "play", keys: "Space", group: "playback" },
  { action: "start", keys: "Home", group: "playback" },
  { action: "end", keys: "End", group: "playback" },
  { action: "frame_back", keys: "←", group: "playback" },
  { action: "frame_forward", keys: "→", group: "playback" },
  { action: "second_back", keys: "Shift+←", group: "playback" },
  { action: "second_forward", keys: "Shift+→", group: "playback" },
  { action: "shuttle_back", keys: "J", group: "playback" },
  { action: "shuttle_stop", keys: "K", group: "playback" },
  { action: "shuttle_forward", keys: "L", group: "playback" },
  { action: "zoom_in", keys: "Ctrl+=", group: "view" },
  { action: "zoom_out", keys: "Ctrl+-", group: "view" },
  { action: "zoom_fit", keys: "Ctrl+0", group: "view" },
  { action: "zoom_wheel", keys: "Ctrl+wheel", group: "view" },
  { action: "open_menu", keys: "Shift+F10", group: "studio" },
  { action: "shortcuts", keys: "? / Ctrl+/", group: "studio" },
];

/**
 * The rate after a press of L: it starts playing at 1, and each L while playing doubles it, up to 4.
 * J does not play backwards: a browser cannot play video or audio in reverse (Remotion's Player docs),
 * so J steps back one second instead.
 */
export function shuttleRate(playing: boolean, rate: number): number {
  return playing ? Math.min(4, rate * 2) : 1;
}

export const shortcutKeys = (action: ShortcutAction) => SHORTCUTS.find((entry) => entry.action === action)?.keys;

/** Undo, redo and the shortcut list, from anywhere in an editing Studio except a field. */
export function useStudioShortcuts(handlers: { undo: () => void; redo: () => void; shortcuts: () => void; enabled: boolean }): void {
  const latest = useRef(handlers);
  latest.current = handlers;
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const { undo, redo, shortcuts, enabled } = latest.current;
      if (!enabled || event.defaultPrevented || isTypingTarget(event.target)) return;
      // A menu or a dialog owns its keys (final review 2026-11-08 #3).
      if ((event.target as HTMLElement | null)?.closest?.("[role='dialog'], [role='menu']")) return;
      const mod = event.ctrlKey || event.metaKey;
      const letter = event.key.toLowerCase();
      if (mod && letter === "z" && !event.shiftKey) undo();
      else if (mod && (letter === "y" || (letter === "z" && event.shiftKey))) redo();
      else if (event.key === "?" || (mod && event.key === "/")) shortcuts();
      else return;
      event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
