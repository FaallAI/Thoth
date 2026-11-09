/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { render } from "@/test-render";
import { MarkerNameDialog } from "./MarkerNameDialog";

afterEach(cleanup);

// Tier 3a: a marker's name, at most 60 characters, saved only on Save.
test("it shows the current name and saves the new one", () => {
  const onSave = mock((_label: string) => {});
  render(<MarkerNameDialog label="Old" onSave={onSave} onClose={() => {}} />);
  const field = screen.getByRole("textbox", { name: "Marker name" }) as HTMLInputElement;
  expect(field.value).toBe("Old");
  expect(field.maxLength).toBe(60);
  fireEvent.change(field, { target: { value: "  New  " } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(onSave).toHaveBeenCalledWith("New");
});

test("Escape and Cancel close it without saving", () => {
  const onSave = mock((_label: string) => {});
  const onClose = mock(() => {});
  render(<MarkerNameDialog label="" onSave={onSave} onClose={onClose} />);
  fireEvent.keyDown(screen.getByRole("dialog", { name: "Rename marker" }), { key: "Escape" });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalledTimes(2);
  expect(onSave).not.toHaveBeenCalled();
});

test("focus returns to where it was when it closes", () => {
  const opener = document.body.appendChild(document.createElement("button"));
  opener.focus();
  const { unmount } = render(<MarkerNameDialog label="" onSave={() => {}} onClose={() => {}} />);
  unmount();
  expect(document.activeElement).toBe(opener);
  opener.remove();
});
