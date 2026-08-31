import { useCallback, useEffect, useRef, useState } from "react";
import { isBackTop, pushBack } from "../lib/telegram.js";

/*
  Полноэкранная «страница» мини-аппа: въезжает справа, как пуш-экран в
  нативных приложениях, уезжает так же. Системная кнопка «назад» Telegram
  закрывает её (стек pushBack), своя стрелка в шапке — для остальных.
*/
export function ScreenShell({ open, title, back = false, headless = false, onClose, children }) {
  const [shown, setShown] = useState(open);
  const [active, setActive] = useState(false);

  // Родители передают inline-стрелки: их identity меняется каждый рендер,
  // а перезапуск pushBack-эффекта дёргал бы историю (back+pushState) на
  // каждом поллинге. Держим актуальный onClose в ref, наружу — стабильный.
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });
  const stableClose = useCallback(() => {
    if (closeRef.current) closeRef.current();
  }, []);

  useEffect(() => {
    if (open) {
      setShown(true);
      const wait = setTimeout(() => setActive(true), 30);
      return () => clearTimeout(wait);
    }
    if (shown) {
      setActive(false);
      const wait = setTimeout(() => setShown(false), 420);
      return () => clearTimeout(wait);
    }
    return undefined;
  }, [open, shown]);

  useEffect(() => {
    if (!shown || !open) return undefined;
    return pushBack(stableClose);
  }, [shown, open, stableClose]);

  useEffect(() => {
    if (!shown) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape" && isBackTop(stableClose)) stableClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shown, stableClose]);

  if (!shown) return null;

  return (
    // Клик по затемнению закрывает окно (десктоп); на телефоне экран
    // заполнен шапкой и телом целиком, так что сюда не попасть.
    <div
      className={`scr${active ? " is-open" : ""}${headless ? " scr-bare" : ""}`}
      role="dialog"
      aria-label={title}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* headless: экран без своей шапки — закрывает его системная
          кнопка Telegram, а заголовок избыточен. */}
      {!headless && (
        <header className="scr-head">
          {back && (
            <button type="button" className="scr-back" onClick={stableClose} aria-label={title}>
              ‹
            </button>
          )}
          <h2>{title}</h2>
        </header>
      )}
      <div className="scr-body">{children}</div>
    </div>
  );
}
