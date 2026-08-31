import { useCallback, useEffect, useRef, useState } from "react";
import { isBackTop, pushBack } from "../lib/telegram.js";
import "./password-dialog.css";

/*
  Оболочка модального листа. На сайте — центрированное окно (стили .pd как
  были), в мини-аппе — нижний лист: плавный выезд снизу и постепенный блюр
  фона на CSS-переходах (см. tma.css), закрытие тем же путём в обратную
  сторону. Пока лист открыт, системная кнопка «назад» Telegram закрывает
  его, а не уводит со страницы. Esc и тап по фону — тоже закрытие.

  open управляется родителем; сам размонтаж откладывается до конца
  анимации закрытия (в мини-аппе), чтобы лист успел уехать вниз.
*/
export function SheetShell({ open, onClose, onSubmit, children }) {
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
      // короткая пауза: смонтироваться в исходной позе, потом поехать.
      // Таймер, а не requestAnimationFrame: в свёрнутом вебвью кадров нет,
      // и rAF-цепочка никогда бы не выстрелила.
      const wait = setTimeout(() => setActive(true), 30);
      return () => clearTimeout(wait);
    }
    if (shown) {
      setActive(false);
      const wait = setTimeout(() => setShown(false), 460);
      return () => clearTimeout(wait);
    }
    return undefined;
  }, [open, shown]);

  useEffect(() => {
    if (!shown) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape" && isBackTop(stableClose)) stableClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shown, stableClose]);

  useEffect(() => {
    if (!shown || !open) return undefined;
    return pushBack(stableClose);
  }, [shown, open, stableClose]);

  if (!shown) return null;

  const Tag = onSubmit ? "form" : "div";
  return (
    <div className={`pd-overlay${active ? " is-open" : ""}`} onMouseDown={onClose}>
      <Tag className="pd" onMouseDown={(e) => e.stopPropagation()} onSubmit={onSubmit}>
        <span className="pd-grip" aria-hidden="true" />
        {children}
      </Tag>
    </div>
  );
}
