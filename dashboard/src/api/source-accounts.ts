import { notifyForbidden } from "@/lib/auth-events";
import type { components } from "@/api/generated/control-plane";

export type SourcePlatform = components["schemas"]["SourceAccountCreate"]["platform"];
export type AccessMode = components["schemas"]["AccessPolicyUpdate"]["mode"];
export type BrowserEngine = components["schemas"]["PlatformAccounts"]["engine"];
export type SourceAccount = components["schemas"]["SourceAccount"];
export type PlatformAccounts = components["schemas"]["PlatformAccounts"];
export type SourceAccountsOverview = components["schemas"]["SourceAccountsOverview"];
export type AccessPolicyUpdate = components["schemas"]["AccessPolicyUpdate"];
export type CookieValidation = components["schemas"]["CookieValidation"];
export type SourceProxy = components["schemas"]["SourceProxy"];
export type ProxyImportSummary = components["schemas"]["ProxyImportSummary"];
export type SessionCheckResult = components["schemas"]["SessionCheckResult"];
// Every field may be omitted ("omit a field to keep it"); the schema marks defaults required.
export type SourceAccountUpdate = Partial<components["schemas"]["SourceAccountUpdate"]>;

export const PLATFORMS: { id: SourcePlatform; label: string }[] = [
  { id: "tiktok", label: "TikTok" },
  { id: "threads", label: "Threads" },
  { id: "instagram", label: "Instagram" },
  { id: "x", label: "X" },
  { id: "youtube", label: "YouTube" },
];

export function platformLabel(platform: string): string {
  return PLATFORMS.find((entry) => entry.id === platform)?.label ?? platform;
}

export const REQUIRED_COOKIES: Record<SourcePlatform, string[]> = {
  tiktok: ["sessionid"],
  threads: ["sessionid"],
  instagram: ["sessionid"],
  x: ["auth_token", "ct0"],
  youtube: ["SAPISID", "__Secure-3PSID"],
};

/** A failed source-account call: only the status and the server's code survive. */
export class SourceAccountsRequestError extends Error {
  readonly status: number | null;
  readonly code: string | null;
  readonly missing: string[];

  constructor(status: number | null, code: string | null, missing: string[] = []) {
    super(code ?? "source_accounts_request_failed");
    this.status = status;
    this.code = code;
    this.missing = missing;
  }
}

export type SourceAccountsClient = {
  overview: () => Promise<SourceAccountsOverview>;
  setPolicy: (platform: SourcePlatform, policy: AccessPolicyUpdate) => Promise<AccessPolicyUpdate>;
  validate: (platform: SourcePlatform, cookies: string) => Promise<CookieValidation>;
  create: (request: {
    platform: SourcePlatform;
    label: string;
    cookies: string;
    proxy_id: string | null;
  }) => Promise<SourceAccount>;
  reimport: (accountId: string, cookies: string) => Promise<SourceAccount>;
  update: (accountId: string, update: SourceAccountUpdate) => Promise<SourceAccount>;
  remove: (accountId: string) => Promise<void>;
  test: (accountId: string) => Promise<SessionCheckResult>;
  proxies: () => Promise<SourceProxy[]>;
  importProxies: (text: string) => Promise<ProxyImportSummary>;
  removeProxy: (proxyId: string) => Promise<void>;
};

type ClientOptions = { baseUrl?: string; apiKey?: string; fetch?: typeof fetch };

export function createSourceAccountsClient(options: ClientOptions = {}): SourceAccountsClient {
  const baseUrl = (options.baseUrl ?? import.meta.env.VITE_CONTROL_PLANE_URL ?? "").replace(/\/$/, "");
  const apiKey = options.apiKey ?? "";
  const doFetch = options.fetch ?? fetch;

  async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    let response: Response;
    try {
      response = await doFetch(`${baseUrl}/api/v1${path}`, {
        method,
        headers: {
          ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (response.status === 403) notifyForbidden();
    } catch {
      throw new SourceAccountsRequestError(null, null);
    }
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as
        | { detail?: { code?: unknown; missing?: unknown } }
        | null;
      const code = payload?.detail?.code;
      const missing = payload?.detail?.missing;
      throw new SourceAccountsRequestError(
        response.status,
        typeof code === "string" ? code : null,
        Array.isArray(missing) ? missing.filter((name): name is string => typeof name === "string") : [],
      );
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  const id = encodeURIComponent;
  return {
    overview: () => call("/source-accounts"),
    setPolicy: (platform, policy) => call(`/source-accounts/policies/${id(platform)}`, "PUT", policy),
    validate: (platform, cookies) => call("/source-accounts/validate", "POST", { platform, cookies }),
    create: (request) => call("/source-accounts", "POST", request),
    reimport: (accountId, cookies) => call(`/source-accounts/${id(accountId)}/cookies`, "PUT", { cookies }),
    update: (accountId, update) => call(`/source-accounts/${id(accountId)}`, "PATCH", update),
    remove: (accountId) => call(`/source-accounts/${id(accountId)}`, "DELETE"),
    test: (accountId) => call(`/source-accounts/${id(accountId)}/test`, "POST"),
    proxies: () => call("/source-proxies"),
    importProxies: (text) => call("/source-proxies/import", "POST", { text }),
    removeProxy: (proxyId) => call(`/source-proxies/${id(proxyId)}`, "DELETE"),
  };
}

export const sourceAccountsClient = createSourceAccountsClient();

const ERROR_TEXT: Record<string, string> = {
  source_accounts_unavailable: "Source accounts are not configured on this server.",
  label_taken: "Another account on this platform already uses that label.",
  proxy_in_use: "That proxy already serves another account.",
  proxy_not_found: "That proxy is no longer in the pool.",
  not_found: "That account no longer exists.",
  invalid_cookie_file: "The file is not a cookie export this page can read.",
  all_cookies_expired: "Every cookie in the export has expired. Sign in again and export.",
  missing_required_cookie: "The export is missing a required login cookie.",
  invalid_proxy_file: "The proxy list is too large. Import at most 500 lines.",
  undecryptable: "This account can no longer be read. Re-import its cookies.",
  invalid_request: "Some fields are not valid.",
  engine_unsupported: "Camoufox runs only for Instagram.",
};

/** Fixed, safe copy for an error; never the server's own words. */
export function errorText(error: unknown): string {
  const code = error instanceof SourceAccountsRequestError ? error.code : null;
  return (code && ERROR_TEXT[code]) || "The request did not complete. Try again.";
}
