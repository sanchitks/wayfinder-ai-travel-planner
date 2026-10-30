"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { logout as apiLogout, me, type User } from "@/lib/auth";
import { takeTokenFromUrl } from "@/lib/site";

interface AuthState {
  user: User | null;
  /** True until the first "who am I" check finishes. */
  loading: boolean;
  setUser: React.Dispatch<React.SetStateAction<User | null>>;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await me());
    } catch {
      setUser(null); // backend offline: behave as signed out
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    takeTokenFromUrl(); // returning from Google sign-in (token mode)
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  }, []);

  return <AuthContext.Provider value={{ user, loading, setUser, refresh, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
