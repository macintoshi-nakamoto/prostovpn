import { useEffect, useState } from "react";
import { isTma, pushBack } from "../lib/telegram.js";
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
      const wait = setTimeout(() => setShown(false), isTma() ? 460 : 0);
      return () => clearTimeout(wait);
    }
    return undefined;
  }, [open, shown]);

  useEffect(() => {
    if (!shown) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [shown, onClose]);

  useEffect(() => {
    if (!shown || !open || !isTma()) return undefined;
    return pushBack(onClose);
  }, [shown, open, onClose]);

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
