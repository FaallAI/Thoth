import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { Feather } from "lucide-react";

import { authClient, type AuthClient } from "@/api/auth";
import { buttonVariants } from "@/components/ui/button";

export const SIGN_IN_ERRORS: Record<string, string> = {
  unverified_email: "Your provider has not verified this email address.",
  not_allowed: "This account is not allowed to sign in to this workspace.",
  provider_error: "Sign-in did not complete. Try again.",
  not_configured: "Sign-in is not configured on this server.",
  too_many_codes: "Too many codes were sent today. Try again tomorrow.",
  code_not_sent: "The sign-in code could not be sent. Try again.",
  unavailable: "Sign-in is unavailable right now. Try again shortly.",
};
const LABELS: Record<string, string> = { google: "Continue with Google", github: "Continue with GitHub" };

export function LoginPage({ client = authClient }: { client?: Pick<AuthClient, "providers"> }) {
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/workflows";
  const error = params.get("error");
  const [providers, setProviders] = useState<string[] | null>(null);
  useEffect(() => {
    client.providers().then(setProviders, () => setProviders([]));
  }, [client]);
  return (
    <main className="dashboard-login">
      <div className="dashboard-login-card">
        <p className="dashboard-brand"><Feather aria-hidden="true" /><span>Thoth</span></p>
        <h1>Sign in</h1>
        {error && <p role="alert">{SIGN_IN_ERRORS[error] ?? SIGN_IN_ERRORS.provider_error}</p>}
        {providers === null ? (
          <p role="status">Loading…</p>
        ) : providers.length === 0 ? (
          <p>{SIGN_IN_ERRORS.not_configured}</p>
        ) : (
          providers.map((provider) => (
            <a key={provider} className={buttonVariants({ variant: "outline" })} href={`/auth/login/${provider}?next=${encodeURIComponent(next)}`}>
              {LABELS[provider] ?? provider}
            </a>
          ))
        )}
        <p className="dashboard-login-note">After signing in we email you a one-time code.</p>
      </div>
    </main>
  );
}
