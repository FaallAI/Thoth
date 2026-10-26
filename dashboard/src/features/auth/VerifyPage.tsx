import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { authClient, AuthRequestError, type AuthClient } from "@/api/auth";
import { Button } from "@/components/ui/button";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

/** The server's code for a refused code or resend, and the copy each one reads as. */
const CODE_ERRORS: Record<string, MessageKey> = {
  wrong_code: "signin.error.wrong_code",
  expired: "signin.error.expired",
  too_many_attempts: "signin.error.too_many_attempts",
  resend_too_soon: "signin.error.resend_too_soon",
  daily_limit: "signin.error.too_many_codes",
  code_not_sent: "signin.error.code_not_sent",
  cross_site_request: "signin.error.cross_site_request",
  unavailable: "signin.error.unavailable",
};
const RESEND_SECONDS = 60;

/** The server already refuses foreign targets; the page checks again before it navigates. */
function sameSite(target: string): string {
  try {
    const url = new URL(target, window.location.origin);
    return url.origin === window.location.origin ? url.pathname + url.search + url.hash : "/workflows";
  } catch {
    return "/workflows";
  }
}

export function VerifyPage({
  client = authClient,
  onSignedIn = (target: string) => window.location.assign(target),
}: {
  client?: Pick<AuthClient, "verify" | "resend">;
  onSignedIn?: (target: string) => void;
}) {
  const { t } = useLocale();
  const [params] = useSearchParams();
  const next = params.get("next") ?? "/workflows";
  const [code, setCode] = useState("");
  const [trust, setTrust] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(RESEND_SECONDS);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const codeOf = (failure: unknown) => (failure instanceof AuthRequestError && failure.code ? failure.code : "unavailable");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(sameSite(await client.verify(code, trust, next)));
    } catch (failure) {
      setError(codeOf(failure));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      await client.resend();
      setWait(RESEND_SECONDS);
      setNotice(t("signin.sent"));
    } catch (failure) {
      setError(codeOf(failure));
    }
  }

  const dead = error === "expired" || error === "too_many_attempts";
  return (
    <main className="dashboard-login">
      <form className="dashboard-login-card" onSubmit={(event) => void submit(event)}>
        <h1>{t("signin.verifyTitle")}</h1>
        <p>{t("signin.verifyBody")}</p>
        <label htmlFor="sign-in-code">{t("signin.code")}</label>
        <input
          id="sign-in-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          aria-describedby={error ? "sign-in-error" : undefined}
        />
        <label className="dashboard-login-trust">
          <input type="checkbox" checked={trust} onChange={(event) => setTrust(event.target.checked)} />
          {t("signin.trust")}
        </label>
        {error && <p id="sign-in-error" role="alert">{t(CODE_ERRORS[error] ?? CODE_ERRORS.unavailable)}</p>}
        {notice && !error && <p role="status">{notice}</p>}
        {dead ? (
          <Link to={`/login?next=${encodeURIComponent(next)}`}>{t("signin.back")}</Link>
        ) : (
          <Button type="submit" disabled={busy || code.length !== 6}>{t("signin.continue")}</Button>
        )}
        <Button type="button" variant="outline" disabled={wait > 0 || dead} onClick={() => void resend()}>
          {wait > 0 ? t("signin.resendIn", { seconds: wait }) : t("signin.resend")}
        </Button>
      </form>
    </main>
  );
}
