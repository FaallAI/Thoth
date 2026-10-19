import { expect, test } from "bun:test";

import config from "./vite.config";
import { injectDevToken, refuseBundledKey } from "./vite.auth.ts";

test("proxies the control plane and the sign-in routes", () => {
  const proxy = config.server?.proxy as Record<string, { target: string }>;
  expect(proxy["/api/v1"].target).toBe("http://127.0.0.1:8000");
  expect(proxy["/auth"].target).toBe("http://127.0.0.1:8000");
});

test("a local developer token is added on the dev server only when set", () => {
  const headers = new Map<string, string>();
  const request = { setHeader: (name: string, value: string) => headers.set(name, value) };
  injectDevToken(request, {});
  expect(headers.size).toBe(0);
  injectDevToken(request, { THOTH_DEV_TOKEN: "thoth_pat_local" });
  expect(headers.get("Authorization")).toBe("Bearer thoth_pat_local");
});

test("a build refuses a control-plane key in the bundle environment", () => {
  const plugin = refuseBundledKey() as { config: (c: object, e: { command: string }) => void };
  const saved = process.env.VITE_CONTROL_PLANE_API_KEY;
  process.env.VITE_CONTROL_PLANE_API_KEY = "leak";
  try {
    expect(() => plugin.config({}, { command: "build" })).toThrow(/VITE_CONTROL_PLANE_API_KEY/);
    expect(() => plugin.config({}, { command: "serve" })).not.toThrow();
  } finally {
    if (saved === undefined) delete process.env.VITE_CONTROL_PLANE_API_KEY;
    else process.env.VITE_CONTROL_PLANE_API_KEY = saved;
  }
});
