/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import type { EditorAsset } from "@/api/control-plane";
import { render } from "@/test-render";
import { ReplaceMediaDialog } from "./ReplaceMediaDialog";

afterEach(cleanup);

const asset = (asset_id: string, kind: EditorAsset["kind"], validation_state: EditorAsset["validation_state"] = "ready"): EditorAsset => ({
  asset_id,
  project_id: "project_001",
  kind,
  has_audio: true,
  media_type: "video/mp4",
  validation_state,
});

test("only other ready videos are offered, and a choice is handed back", () => {
  const onReplace = mock((_assetId: string) => {});
  render(
    <ReplaceMediaDialog
      currentAssetId="asset_now"
      assets={[asset("asset_now", "video"), asset("asset_ok", "video"), asset("asset_pending", "video", "pending"), asset("asset_photo", "image")]}
      nameOf={(item) => item.asset_id}
      onReplace={onReplace}
      onClose={() => {}}
    />,
  );
  const options = screen.getAllByRole("button", { name: /^Use / }).map((button) => button.getAttribute("aria-label"));
  expect(options).toEqual(["Use asset_ok"]);
  fireEvent.click(screen.getByRole("button", { name: "Use asset_ok" }));
  expect(onReplace).toHaveBeenCalledWith("asset_ok");
});

test("with nothing to offer it says so, and Cancel and Escape close it", () => {
  const onClose = mock(() => {});
  render(<ReplaceMediaDialog currentAssetId="asset_now" assets={[asset("asset_now", "video")]} nameOf={(item) => item.asset_id} onReplace={() => {}} onClose={onClose} />);
  expect(screen.getByText("No other ready video in this project")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.keyDown(screen.getByRole("dialog", { name: "Replace media" }), { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(2);
});
