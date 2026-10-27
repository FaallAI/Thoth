// Desktop notifications (DESIGN §12.3): once per run and event, only when allowed and unseen.
import { afterEach, beforeEach, expect, mock, test } from "bun:test";

import { dismissOffer, notifyOnce, offerWanted } from "./notifications";

const shown = mock((_title: string, _options?: NotificationOptions) => {});
let permission: NotificationPermission = "granted";
let visibility: DocumentVisibilityState = "hidden";
const original = Object.getOwnPropertyDescriptor(document, "visibilityState");

beforeEach(() => {
  localStorage.clear();
  shown.mockClear();
  permission = "granted";
  visibility = "hidden";
  class FakeNotification {
    static get permission() {
      return permission;
    }
    constructor(title: string, options?: NotificationOptions) {
      shown(title, options);
    }
  }
  Object.assign(window, { Notification: FakeNotification });
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
});

afterEach(() => {
  if (original) Object.defineProperty(document, "visibilityState", original);
});

test("a run event is told once, and only while the page is out of view", () => {
  visibility = "visible";
  notifyOnce("wf_1", "done", "A run is done", "Haze");
  expect(shown).not.toHaveBeenCalled();

  visibility = "hidden";
  notifyOnce("wf_1", "done", "A run is done", "Haze");
  notifyOnce("wf_1", "done", "A run is done", "Haze");
  notifyOnce("wf_1", "failed", "A run failed", "Haze");
  expect(shown.mock.calls.map((call) => call[0])).toEqual(["A run is done", "A run failed"]);
});

test("nothing is shown without permission, and the offer waits for the browser's question", () => {
  permission = "denied";
  notifyOnce("wf_1", "waiting", "A run needs your review", "Haze");
  expect(shown).not.toHaveBeenCalled();
  expect(offerWanted()).toBe(false);

  permission = "default";
  expect(offerWanted()).toBe(true);
  dismissOffer();
  expect(offerWanted()).toBe(false);
});
