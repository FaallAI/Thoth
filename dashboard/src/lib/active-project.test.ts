/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { act, renderHook } from "@testing-library/react";

import { useActiveProject } from "./active-project";

afterEach(() => localStorage.clear());

test("the active project persists across mounts", () => {
  const first = renderHook(() => useActiveProject());
  act(() => first.result.current[1]("p1"));
  expect(renderHook(() => useActiveProject()).result.current[0]).toBe("p1");
});

test("clearing the active project forgets it", () => {
  const hook = renderHook(() => useActiveProject());
  act(() => hook.result.current[1]("p1"));
  act(() => hook.result.current[1](null));
  expect(localStorage.getItem("thoth.activeProject")).toBeNull();
});

test("a storage that throws still works in memory", () => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = () => {
    throw new Error("blocked");
  };
  try {
    const hook = renderHook(() => useActiveProject());
    act(() => hook.result.current[1]("p2"));
    expect(hook.result.current[0]).toBe("p2");
  } finally {
    Storage.prototype.setItem = original;
  }
});
