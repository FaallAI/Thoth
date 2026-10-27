import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { authClient, type AuthClient, type Me } from "@/api/auth";
import { authEvents } from "@/lib/auth-events";
import { useLocale } from "@/lib/locale";

import { AuthContext } from "./auth-context";

/** Renders its children only for a signed-in caller; a session that ends sends them to /login. */
export function AuthGate({ client = authClient, children }: { client?: Pick<AuthClient, "me">; children: ReactNode }) {
  const { t } = useLocale();
  const location = useLocation();
  const [state, setState] = useState<"loading" | "signed_out" | "unreachable" | Me>("loading");
  const check = useCallback(async () => {
    try {
      setState((await client.me()) ?? "signed_out");
    } catch {
      setState("unreachable");
    }
  }, [client]);

  useEffect(() => {
    void check();
  }, [check]);
  useEffect(() => {
    const recheck = () => void check();
    authEvents.addEventListener("forbidden", recheck);
    return () => authEvents.removeEventListener("forbidden", recheck);
  }, [check]);

  if (state === "loading") return <p role="status" className="dashboard-auth-status">{t("auth.checking")}</p>;
  if (state === "unreachable") {
    return (
      <div role="alert" className="dashboard-auth-status">
        <p>{t("auth.unreachable")}</p>
        <button type="button" onClick={() => void check()}>{t("common.retry")}</button>
      </div>
    );
  }
  if (state === "signed_out") {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  return <AuthContext.Provider value={{ me: state, refresh: check }}>{children}</AuthContext.Provider>;
}
