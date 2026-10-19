// Sign-in and developer tokens (spec 2026-10-19). /auth is not in OpenAPI; /api/v1/me is.
import type { components } from "@/api/generated/control-plane";

export type Me = components["schemas"]["MeView"];
export type TokenView = components["schemas"]["TokenView"];
export type CreateToken = components["schemas"]["CreateToken"];
export type CreatedToken = components["schemas"]["CreatedToken"];

export class AuthRequestError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null) {
    super(code ?? `auth_request_failed_${status}`);
    this.status = status;
    this.code = code;
  }
}

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

async function failure(response: Response): Promise<AuthRequestError> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return new AuthRequestError(response.status, typeof body?.detail === "string" ? body.detail : null);
}

const JSON_BODY = { "Content-Type": "application/json" };

export function createAuthClient(doFetch: Fetch = (input, init) => fetch(input, init)) {
  async function send(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await doFetch(path, init);
    if (!response.ok) throw await failure(response);
    return response;
  }
  return {
    async me(): Promise<Me | null> {
      const response = await doFetch("/auth/me");
      if (response.status === 401) return null;
      if (!response.ok) throw await failure(response);
      return (await response.json()) as Me;
    },
    async providers(): Promise<string[]> {
      const response = await doFetch("/auth/providers");
      if (!response.ok) return [];
      return ((await response.json()) as { providers: string[] }).providers;
    },
    async verify(code: string, trustDevice: boolean, next: string): Promise<string> {
      const response = await send("/auth/verify", {
        method: "POST", headers: JSON_BODY, body: JSON.stringify({ code, trust_device: trustDevice, next }),
      });
      return ((await response.json()) as { next: string }).next;
    },
    async resend(): Promise<void> {
      await send("/auth/resend", { method: "POST" });
    },
    async logout(forgetDevice: boolean): Promise<void> {
      await send("/auth/logout", { method: "POST", headers: JSON_BODY, body: JSON.stringify({ forget_device: forgetDevice }) });
    },
    async listTokens(): Promise<TokenView[]> {
      return (await (await send("/api/v1/me/tokens")).json()) as TokenView[];
    },
    async createToken(request: CreateToken): Promise<CreatedToken> {
      const response = await send("/api/v1/me/tokens", { method: "POST", headers: JSON_BODY, body: JSON.stringify(request) });
      return (await response.json()) as CreatedToken;
    },
    async revokeToken(tokenId: string): Promise<void> {
      await send(`/api/v1/me/tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE" });
    },
  };
}

export type AuthClient = ReturnType<typeof createAuthClient>;
export const authClient = createAuthClient();
