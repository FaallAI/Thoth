// Local development auth (spec 2026-10-19, 3.4): the server never bypasses authentication.
// The dev server adds a personal developer token from the developer's own environment; it is
// read by Node at request time and never becomes a VITE_ variable, so no bundle can contain it.
import type { Plugin, ProxyOptions } from "vite";

type HeaderTarget = { setHeader(name: string, value: string): void };

export function injectDevToken(request: HeaderTarget, env: Record<string, string | undefined> = process.env): void {
  const token = env.THOTH_DEV_TOKEN?.trim();
  if (token) request.setHeader("Authorization", `Bearer ${token}`);
}

export function devProxy(target = "http://127.0.0.1:8000"): Record<string, ProxyOptions> {
  const withToken: ProxyOptions = {
    target,
    configure: (proxy) => proxy.on("proxyReq", (request) => injectDevToken(request)),
  };
  return { "/api/v1": withToken, "/auth": { ...withToken } };
}

export function refuseBundledKey(): Plugin {
  return {
    name: "thoth-refuse-bundled-key",
    config(_config, { command }) {
      if (command === "build" && process.env.VITE_CONTROL_PLANE_API_KEY) {
        throw new Error("VITE_CONTROL_PLANE_API_KEY is set: the dashboard must not bundle a control-plane key. Unset it; the browser signs in instead.");
      }
    },
  };
}
