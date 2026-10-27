import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { Feather } from "lucide-react";

import { authClient, type AuthClient } from "@/api/auth";
import { buttonVariants } from "@/components/ui/button";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

/** Every /login?error= code has fixed copy (spec 2026-10-19, section 2); others read as a failed sign-in. */
const ERRORS = new Set(["unverified_email", "not_allowed", "provider_error", "not_configured", "too_many_codes", "too_soon", "code_not_sent", "unavailable"]);
const LABELS: Record<string, MessageKey> = { google: "signin.google", github: "signin.github" };

export function LoginPage({ client = authClient }: { client?: Pick<AuthClient, "providers"> }) {
  const { t } = useLocale();
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
        <h1>{t("signin.title")}</h1>
        {error && <p role="alert">{t(`signin.error.${ERRORS.has(error) ? error : "provider_error"}` as MessageKey)}</p>}
        {providers === null ? (
          <p role="status">{t("common.loading")}</p>
        ) : providers.length === 0 ? (
          <p>{t("signin.error.not_configured")}</p>
        ) : (
          providers.map((provider) => (
            <a key={provider} className={buttonVariants({ variant: "outline" })} href={`/auth/login/${provider}?next=${encodeURIComponent(next)}`}>
              {LABELS[provider] ? t(LABELS[provider]) : provider}
            </a>
          ))
        )}
        <p className="dashboard-login-note">{t("signin.note")}</p>
      </div>
    </main>
  );
}
