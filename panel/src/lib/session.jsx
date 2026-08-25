import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { authApi, getToken, onUnauthorized, setToken } from "./api";

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [token, setTokenState] = useState(() => getToken());
  const [admin, setAdmin] = useState(null);

  const [checking, setChecking] = useState(Boolean(getToken()));

  const signOut = useCallback(() => {
    setToken(null);
    setTokenState(null);
    setAdmin(null);
  }, []);

  useEffect(() => onUnauthorized(signOut), [signOut]);

  useEffect(() => {
    if (!token) {
      setChecking(false);
      return;
    }
    let alive = true;
    authApi
      .me()
      .then((data) => alive && setAdmin(data))
      .catch(() => alive && signOut())
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, [token, signOut]);

  const signIn = useCallback(async (login, password) => {
    const data = await authApi.login(login, password);
    setTokenState(data.token);
    setAdmin({ login: data.login });
    return data;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      signOut();
    }
  }, [signOut]);

  const value = useMemo(
    () => ({ token, admin, checking, signIn, logout, isAuthenticated: Boolean(token) }),
    [token, admin, checking, signIn, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession вне SessionProvider");
  return ctx;
}
