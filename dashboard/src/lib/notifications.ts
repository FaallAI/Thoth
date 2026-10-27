// Desktop notifications (DESIGN §12.3): offered in the page first, then once per run and event.

const OFFER_KEY = "thoth.notifyOffer";
const SENT_PREFIX = "thoth.notified.";

export type RunEvent = "waiting" | "done" | "failed";

function stored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage can be blocked; the page then asks again next time.
  }
}

function supported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** The in-page offer shows while the browser has not been asked and the person has not declined it here. */
export function offerWanted(): boolean {
  return supported() && Notification.permission === "default" && stored(OFFER_KEY) !== "dismissed";
}

export function dismissOffer(): void {
  store(OFFER_KEY, "dismissed");
}

export async function askPermission(): Promise<boolean> {
  if (!supported()) return false;
  dismissOffer();
  return (await Notification.requestPermission()) === "granted";
}

/**
 * Tells the person about a run event once, and only when they are looking elsewhere: a page in
 * view already shows the change.
 */
export function notifyOnce(workflowId: string, event: RunEvent, title: string, body: string): void {
  if (!supported() || Notification.permission !== "granted" || document.visibilityState === "visible") return;
  const key = `${SENT_PREFIX}${workflowId}.${event}`;
  if (stored(key)) return;
  store(key, "1");
  new Notification(title, { body, tag: key });
}
