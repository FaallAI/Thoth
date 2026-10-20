// The caller's workspace usage (spec 2026-10-20 metering, 2.4).
import type { components } from "@/api/generated/control-plane";

export type UsageView = components["schemas"]["UsageView"];

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export function createUsageClient(doFetch: Fetch = (input, init) => fetch(input, init)) {
  return {
    async get(month?: string): Promise<UsageView> {
      const query = month ? `?month=${encodeURIComponent(month)}` : "";
      const response = await doFetch(`/api/v1/usage${query}`);
      if (!response.ok) throw new Error(`usage_request_failed_${response.status}`);
      return (await response.json()) as UsageView;
    },
  };
}

export type UsageClient = ReturnType<typeof createUsageClient>;
export const usageClient = createUsageClient();
