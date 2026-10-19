/** API clients raise `forbidden` on a 403 so the auth gate re-checks whether anyone is signed in. */
export const authEvents = new EventTarget();

export function notifyForbidden(): void {
  authEvents.dispatchEvent(new Event("forbidden"));
}
