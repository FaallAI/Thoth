import { createContext, useContext } from "react";

import type { Me } from "@/api/auth";

export type AuthState = { me: Me; refresh: () => Promise<void> };
export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth must be used inside <AuthGate>");
  return state;
}
