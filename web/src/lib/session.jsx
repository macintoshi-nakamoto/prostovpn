import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { api, getToken, setToken } from "./api";
import { forgetRef } from "./referral.js";

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [authed, setAuthed] = useState(() => Boolean(getToken()));

  const signIn = useCallback(async (login, password, remember = true) => {
    const result = await api.login(login, password);
    setToken(result.token, { remember });
    setAuthed(true);
    return result;
  }, []);

  const signUp = useCallback(async (login, password, email) => {
    const result = await api.register(login, password, email);

    forgetRef();
    setToken(result.token);
    setAuthed(true);
    return result;
  }, []);

  const signOut = useCallback(async () => {
    await api.logout();
    setToken(null);
    setAuthed(false);
  }, []);

  const value = useMemo(
    () => ({ authed, signIn, signUp, signOut }),
    [authed, signIn, signUp, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession вне SessionProvider");
  return ctx;
}
