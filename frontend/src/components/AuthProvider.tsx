"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, clearSession, getToken, readUser, setSession } from "@/lib/api";
import type { LoginResponse, User } from "@/lib/types";

type AuthState = {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
  isAdmin: boolean;
  canWrite: boolean;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setReady(true);
      return;
    }
    const cached = readUser<User>();
    if (cached) setUser(cached);
    api
      .get<User>("/auth/me")
      .then((fresh) => {
        setUser(fresh);
        setSession(token, fresh);
      })
      .catch(() => {
        /* the API client clears the session and redirects on 401 */
      })
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result: LoginResponse = await api.login({ email, password });
    setSession(result.access_token, result.user);
    setUser(result.user);
    setReady(true);
    return result.user;
  }, []);

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    window.location.href = "/login";
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      login,
      logout,
      isAdmin: user?.role === "admin",
      canWrite: user?.role === "admin" || user?.role === "analyst",
    }),
    [user, ready, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
