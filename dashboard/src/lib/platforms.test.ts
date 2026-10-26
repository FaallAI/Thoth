// Link recognition for the New run dialog (DESIGN §8.2).
import { expect, test } from "bun:test";

import { detectPlatform, displayHost } from "./platforms";

test("each supported host, and its subdomains, is recognised", () => {
  expect(detectPlatform("https://vt.tiktok.com/ZSj4kR8Lp/")).toBe("tiktok");
  expect(detectPlatform("https://www.tiktok.com/@a/video/1")).toBe("tiktok");
  expect(detectPlatform(" https://x.com/a/status/1 ")).toBe("x");
  expect(detectPlatform("https://mobile.twitter.com/a/status/1")).toBe("x");
  expect(detectPlatform("https://www.instagram.com/p/abc/")).toBe("instagram");
  expect(detectPlatform("https://youtu.be/abc")).toBe("youtube");
  expect(detectPlatform("https://m.youtube.com/watch?v=abc")).toBe("youtube");
  expect(detectPlatform("https://www.threads.net/@a/post/1")).toBe("threads");
});

test("another host, a look-alike or text that is not a link is refused", () => {
  expect(detectPlatform("https://facebook.com/a")).toBeNull();
  expect(detectPlatform("https://nottiktok.com/a")).toBeNull();
  expect(detectPlatform("https://tiktok.com.evil.test/a")).toBeNull();
  expect(detectPlatform("javascript:alert(1)")).toBeNull();
  expect(detectPlatform("tiktok.com/@a")).toBeNull();
});

test("a row shows the host without www", () => {
  expect(displayHost("https://www.tiktok.com/@a/video/1")).toBe("tiktok.com");
  expect(displayHost("not a link")).toBe("not a link");
});
