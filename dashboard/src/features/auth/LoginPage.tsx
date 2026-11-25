import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { Feather } from "lucide-react";

import { authClient, AuthRequestError, type AuthClient } from "@/api/auth";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

import { sameSite } from "./VerifyPage";

/** Every /login?error= code has fixed copy (spec 2026-10-19, section 2); others read as a failed sign-in. */
const ERRORS = new Set(["unverified_email", "not_allowed", "provider_error", "not_configured", "too_many_codes", "too_soon", "code_not_sent", "unavailable", "bad_credentials", "cross_site_request"]);
const LABELS: Record<string, MessageKey> = { google: "signin.google", github: "signin.github" };
/** The env username and password: a form, not a provider link (operator 2026-11-25). */
const PASSWORD = "password";

function errorKey(code: string): MessageKey {
  return `signin.error.${ERRORS.has(code) ? code : "provider_error"}` as MessageKey;
}

function PasswordForm({ client, next, onSignedIn }: { client: Pick<AuthClient, "password">; next: string; onSignedIn: (target: string) => void }) {
  const { t } = useLocale();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(sameSite(await client.password(username, password, next)));
    } catch (failure) {
      setError(failure instanceof AuthRequestError && failure.code ? failure.code : "unavailable");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="grid gap-2" onSubmit={(event) => void submit(event)}>
      {error && <p role="alert">{t(errorKey(error))}</p>}
      <label htmlFor="sign-in-username">{t("signin.username")}</label>
      <Input id="sign-in-username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required />
      <label htmlFor="sign-in-password">{t("signin.password")}</label>
      <Input id="sign-in-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
      <Button type="submit" disabled={busy}>{t("signin.submit")}</Button>
    </form>
  );
}

export function LoginPage({
  client = authClient,
  onSignedIn = (target: string) => window.location.assign(target),
}: {
  client?: Pick<AuthClient, "providers"> & Partial<Pick<AuthClient, "password">>;
  onSignedIn?: (target: string) => void;
}) {
  const { t } = useLocale();
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/workflows";
  const error = params.get("error");
  const [providers, setProviders] = useState<string[] | null>(null);
  useEffect(() => {
    client.providers().then(setProviders, () => setProviders([]));
  }, [client]);
  const links = (providers ?? []).filter((provider) => provider !== PASSWORD);
  const password = client.password && providers?.includes(PASSWORD) ? { password: client.password } : null;
  return (
    <main className="dashboard-login">
      <div className="dashboard-login-card">
        <p className="dashboard-brand"><Feather aria-hidden="true" /><span>Thoth</span></p>
        <h1>{t("signin.title")}</h1>
        {error && <p role="alert">{t(errorKey(error))}</p>}
        {providers === null ? (
          <p role="status">{t("common.loading")}</p>
        ) : providers.length === 0 ? (
          <p>{t("signin.error.not_configured")}</p>
        ) : (
          <>
            {password && <PasswordForm client={password} next={next} onSignedIn={onSignedIn} />}
            {links.map((provider) => (
              <a key={provider} className={buttonVariants({ variant: "outline" })} href={`/auth/login/${provider}?next=${encodeURIComponent(next)}`}>
                {LABELS[provider] ? t(LABELS[provider]) : provider}
              </a>
            ))}
          </>
        )}
        {links.length > 0 && <p className="dashboard-login-note">{t("signin.note")}</p>}
      </div>
    </main>
  );
}
