// The caller's plan, allowance and checkout (spec 2026-10-20 billing, 2.4).
import type { components } from "@/api/generated/control-plane";

export type BillingView = components["schemas"]["BillingView"];
export type CheckoutView = components["schemas"]["CheckoutView"];

/** Why a billing request was refused: the HTTP status and the server's fixed code. */
export class BillingRequestError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null) {
    super(code ?? `billing_request_failed_${status}`);
    this.status = status;
    this.code = code;
  }
}

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export function createBillingClient(doFetch: Fetch = (input, init) => fetch(input, init)) {
  return {
    async get(): Promise<BillingView> {
      const response = await doFetch("/api/v1/billing");
      if (!response.ok) throw new Error(`billing_request_failed_${response.status}`);
      return (await response.json()) as BillingView;
    },
    async checkout(planId: string): Promise<CheckoutView> {
      const response = await doFetch("/api/v1/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: planId }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
        throw new BillingRequestError(response.status, typeof body?.detail === "string" ? body.detail : null);
      }
      return (await response.json()) as CheckoutView;
    },
  };
}

export type BillingClient = ReturnType<typeof createBillingClient>;
export const billingClient = createBillingClient();
