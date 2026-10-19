import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { authClient, AuthRequestError, type AuthClient } from "@/api/auth";
import { Button } from "@/components/ui/button";

import { SIGN_IN_ERRORS } from "./LoginPage";

const CODE_ERRORS: Record<string, string> = {
  wrong_code: "That code is not right. Check the email and try again.",
  expired: "This code has expired. Sign in again to get a new one.",
  too_many_attempts: "Too many wrong codes. Sign in again to get a new one.",
  resend_too_soon: "Wait a minute before asking for another code.",
  daily_limit: SIGN_IN_ERRORS.too_many_codes,
  code_not_sent: SIGN_IN_ERRORS.code_not_sent,
  cross_site_request: "Open this page from the Thoth site to continue.",
  unavailable: SIGN_IN_ERRORS.unavailable,
};
const RESEND_SECONDS = 60;

export function VerifyPage({
  client = authClient,
  onSignedIn = (target: string) => window.location.assign(target),
}: {
  client?: Pick<AuthClient, "verify" | "resend">;
  onSignedIn?: (target: string) => void;
}) {
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
      onSignedIn(await client.verify(code, trust, next));
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
      setNotice("A new code is on its way.");
    } catch (failure) {
      setError(codeOf(failure));
    }
  }

  const dead = error === "expired" || error === "too_many_attempts";
  return (
    <main className="dashboard-login">
      <form className="dashboard-login-card" onSubmit={(event) => void submit(event)}>
        <h1>Check your email</h1>
        <p>We sent a 6-digit code to the address your provider verified.</p>
        <label htmlFor="sign-in-code">Code from your email</label>
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
          Trust this browser for 30 days
        </label>
        {error && <p id="sign-in-error" role="alert">{CODE_ERRORS[error] ?? CODE_ERRORS.unavailable}</p>}
        {notice && !error && <p role="status">{notice}</p>}
        {dead ? (
          <Link to={`/login?next=${encodeURIComponent(next)}`}>Back to sign in</Link>
        ) : (
          <Button type="submit" disabled={busy || code.length !== 6}>Continue</Button>
        )}
        <Button type="button" variant="outline" disabled={wait > 0 || dead} onClick={() => void resend()}>
          {wait > 0 ? `Resend in ${wait}s` : "Resend code"}
        </Button>
      </form>
    </main>
  );
}
