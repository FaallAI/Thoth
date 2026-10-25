// Preloaded by bunfig.toml for component tests. Registers a DOM (happy-dom) on
// the global scope so @testing-library/react can render into it under `bun test`.
import { GlobalRegistrator } from "@happy-dom/global-registrator";

// A real origin: React Router builds links with `new URL(to, location.origin)`.
GlobalRegistrator.register({ url: "http://localhost:5173/" });

// happy-dom doesn't implement these DOM methods that base-ui primitives
// (ScrollArea, Select) call during render. Stub them so component tests render.
if (!Element.prototype.getAnimations) {
  Element.prototype.getAnimations = () => [];
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// happy-dom ships no EventSource. Components that subscribe to the job stream
// only ever construct one and close it, so an inert stub is enough — tests
// drive state through the fetch snapshot instead of the live stream.
// ponytail: no event dispatch; add it when a test needs to push an SseEvent.
if (!("EventSource" in globalThis)) {
  class InertEventSource {
    onerror: ((e: unknown) => void) | null = null;
    onmessage: ((e: unknown) => void) | null = null;
    close() {}
    addEventListener() {}
    removeEventListener() {}
  }
  (globalThis as Record<string, unknown>).EventSource = InertEventSource;
}

// happy-dom implements neither FontFace nor document.fonts. The shared
// composition registers its own font bytes through both, so component tests get
// an inert registry that accepts a face and reports it loaded; a test that cares
// how loading ends replaces this stub for its own duration.
if (!("FontFace" in globalThis)) {
  class InertFontFace {
    family: string;
    constructor(family: string) {
      this.family = family;
    }
    load() {
      return Promise.resolve(this);
    }
  }
  (globalThis as Record<string, unknown>).FontFace = InertFontFace;
}
if (!("fonts" in globalThis.document)) {
  Object.defineProperty(globalThis.document, "fonts", {
    configurable: true,
    value: { add: () => undefined, ready: Promise.resolve() },
  });
}

// testing-library's findBy*/waitFor drain pending work with setTimeout(0), but
// React's scheduler flushes passive effects (useEffect) with setImmediate, and Bun
// does not order the two. Wait one setImmediate inside the wrapper too, so an effect
// of the render that showed an element has run when findBy resolves. Imported after
// the DOM registration above: testing-library binds `screen` to document.body on load.
const { configure, getConfig } = await import("@testing-library/react");
const drainWithTimeout = getConfig().asyncWrapper;
configure({
  asyncWrapper: (callback) =>
    drainWithTimeout(async () => {
      const result = await callback();
      await new Promise((resolve) => setImmediate(resolve));
      return result;
    }),
});
