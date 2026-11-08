// One right-click menu for Studio (spec 2026-11-08 §5.3): a right click, Shift+F10 or the Menu key,
// or a long touch press opens it; Escape, a click outside, scroll or a choice closes it.
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

export type MenuEntry =
  | { kind: "item"; id: string; label: string; shortcut?: string; disabled?: boolean; reason?: string; onSelect: () => void }
  | { kind: "group"; id: string; label: string; entries: MenuEntry[] }
  | { kind: "separator"; id: string };

type Open = { x: number; y: number; entries: MenuEntry[]; owner: HTMLElement | null };

const LONG_PRESS_MS = 500;
const EDGE = 4;

export function useContextMenu(): {
  bind: (entries: () => MenuEntry[]) => {
    onContextMenu: (event: ReactMouseEvent) => void;
    onKeyDown: (event: ReactKeyboardEvent) => void;
    onPointerDown: (event: ReactPointerEvent) => void;
    onPointerUp: () => void;
    onPointerCancel: () => void;
  };
  element: ReactNode;
  close: () => void;
  open: boolean;
} {
  const [state, setState] = useState<Open | null>(null);
  const press = useRef<ReturnType<typeof setTimeout> | null>(null);

  const close = useCallback(() => {
    setState((current) => {
      current?.owner?.focus?.();
      return null;
    });
  }, []);

  const cancelPress = () => {
    if (press.current) clearTimeout(press.current);
    press.current = null;
  };
  useEffect(() => cancelPress, []);

  const show = (owner: HTMLElement | null, x: number, y: number, entries: MenuEntry[]) => {
    if (entries.length) setState({ x, y, entries, owner });
    return entries.length > 0;
  };

  const bind = (entries: () => MenuEntry[]) => ({
    onContextMenu: (event: ReactMouseEvent) => {
      cancelPress();
      if (show(event.currentTarget as HTMLElement, event.clientX, event.clientY, entries())) event.preventDefault();
    },
    onKeyDown: (event: ReactKeyboardEvent) => {
      if (!((event.key === "F10" && event.shiftKey) || event.key === "ContextMenu")) return;
      const owner = event.currentTarget as HTMLElement;
      const box = owner.getBoundingClientRect();
      if (show(owner, box.left, box.bottom, entries())) event.preventDefault();
    },
    onPointerDown: (event: ReactPointerEvent) => {
      if (event.pointerType !== "touch") return;
      const owner = event.currentTarget as HTMLElement;
      const { clientX, clientY } = event;
      cancelPress();
      press.current = setTimeout(() => show(owner, clientX, clientY, entries()), LONG_PRESS_MS);
    },
    onPointerUp: cancelPress,
    onPointerCancel: cancelPress,
  });

  const element = state ? createPortal(<MenuView state={state} onClose={close} />, document.body) : null;
  return { bind, element, close, open: state !== null };
}

function MenuView({ state, onClose }: { state: Open; onClose: () => void }) {
  const menu = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState({ left: state.x, top: state.y });

  // Measured after it renders, so a menu opened in a corner turns back inside the viewport.
  useLayoutEffect(() => {
    const box = menu.current?.getBoundingClientRect();
    if (!box) return;
    setPlace({
      left: Math.max(EDGE, Math.min(state.x, window.innerWidth - box.width - EDGE)),
      top: Math.max(EDGE, Math.min(state.y, window.innerHeight - box.height - EDGE)),
    });
    enabled(menu.current)[0]?.focus();
  }, [state.x, state.y]);

  useEffect(() => {
    const outside = (event: Event) => {
      if (!menu.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", outside, true);
    window.addEventListener("scroll", outside, true);
    window.addEventListener("resize", onClose);
    return () => {
      window.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("scroll", outside, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  const choose = (entry: Extract<MenuEntry, { kind: "item" }>) => {
    if (entry.disabled) return;
    onClose();
    entry.onSelect();
  };

  const onKeyDown = (event: ReactKeyboardEvent) => {
    const items = enabled(menu.current);
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      onClose();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      items[(at + step + items.length) % items.length]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      (event.key === "Home" ? items[0] : items.at(-1))?.focus();
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      (document.activeElement as HTMLElement | null)?.click();
    }
  };

  const render = (entries: MenuEntry[]): ReactNode =>
    entries.map((entry) => {
      if (entry.kind === "separator") return <div key={entry.id} role="separator" className="my-1 h-px bg-hairline" />;
      if (entry.kind === "group")
        return (
          <div key={entry.id} role="group" aria-label={entry.label} className="flex flex-col">
            <span aria-hidden="true" className="px-3 pb-0.5 pt-1.5 text-[11px] uppercase tracking-wide text-faint">
              {entry.label}
            </span>
            {render(entry.entries)}
          </div>
        );
      return (
        <button
          key={entry.id}
          type="button"
          role="menuitem"
          tabIndex={-1}
          aria-label={entry.label}
          aria-disabled={entry.disabled ? "true" : undefined}
          title={entry.disabled ? entry.reason : undefined}
          onClick={() => choose(entry)}
          className="flex items-center gap-6 rounded px-3 py-1.5 text-left text-[13px] text-ink outline-none hover:bg-well focus:bg-well aria-disabled:cursor-not-allowed aria-disabled:text-faint aria-disabled:hover:bg-transparent"
        >
          <span className="grow">{entry.label}</span>
          {entry.shortcut ? <kbd className="font-mono text-[11px] text-faint">{entry.shortcut}</kbd> : null}
        </button>
      );
    });

  return (
    <div
      ref={menu}
      role="menu"
      onKeyDown={onKeyDown}
      onContextMenu={(event) => event.preventDefault()}
      style={{ left: `${place.left}px`, top: `${place.top}px` }}
      className="fixed z-50 flex min-w-48 flex-col rounded-md border border-hairline bg-raised p-1 shadow-lg"
    >
      {render(state.entries)}
    </div>
  );
}

const enabled = (menu: HTMLElement | null): HTMLElement[] =>
  menu ? [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')] : [];
