import { useEffect, useState } from "react";
import { isTma, pushBack } from "../lib/telegram.js";

/*
  Полноэкранная «страница» мини-аппа: въезжает справа, как пуш-экран в
  нативных приложениях, уезжает так же. Системная кнопка «назад» Telegram
  закрывает её (стек pushBack), своя стрелка в шапке — для остальных.
*/
export function ScreenShell({ open, title, onClose, children }) {
  const [shown, setShown] = useState(open);
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (open) {
      setShown(true);
      const wait = setTimeout(() => setActive(true), 30);
      return () => clearTimeout(wait);
    }
    if (shown) {
      setActive(false);
      const wait = setTimeout(() => setShown(false), isTma() ? 420 : 0);
      return () => clearTimeout(wait);
    }
    return undefined;
  }, [open, shown]);

  useEffect(() => {
    if (!shown || !open || !isTma()) return undefined;
    return pushBack(onClose);
  }, [shown, open, onClose]);

  useEffect(() => {
    if (!shown) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shown, onClose]);

  if (!shown) return null;

  return (
    <div className={`scr${active ? " is-open" : ""}`}>
      <header className="scr-head">
        <h2>{title}</h2>
      </header>
      <div className="scr-body">{children}</div>
    </div>
  );
}
