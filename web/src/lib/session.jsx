import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { api, getToken, setToken } from "./api";
import { forgetRef } from "./referral.js";
import { isTma, tmaInitData } from "./telegram.js";

// Человек вышел из кабинета внутри Telegram — не входить обратно самим,
// пока мини-приложение не откроют заново.
const TMA_OUT = "prosto_tma_out";

export function tmaSignedOut() {
  try {
    return sessionStorage.getItem(TMA_OUT) === "1";
  } catch {
    return false;
  }
}

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [authed, setAuthed] = useState(() => Boolean(getToken()));

  const signIn = useCallback(async (login, password, remember = true) => {
    const result = await api.login(login, password);
    setToken(result.token, { remember });
    setAuthed(true);
    try {
      sessionStorage.removeItem(TMA_OUT);
    } catch {}
    return result;
  }, []);

  // Вход из мини-приложения Telegram: личность подтверждает подпись
  // initData, пароль не нужен.
  const signInTelegram = useCallback(async () => {
    const initData = tmaInitData();
    if (!initData) throw new Error("нет initData");
    const result = await api.tgLogin(initData);
    setToken(result.token, { remember: true });
    setAuthed(true);
    try {
      sessionStorage.removeItem(TMA_OUT);
    } catch {}
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
    if (isTma()) {
      try {
        sessionStorage.setItem(TMA_OUT, "1");
      } catch {}
    }
  }, []);

  const value = useMemo(
    () => ({ authed, signIn, signInTelegram, signUp, signOut }),
    [authed, signIn, signInTelegram, signUp, signOut],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession вне SessionProvider");
  return ctx;
}
