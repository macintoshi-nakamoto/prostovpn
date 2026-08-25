import { useEffect, useRef, useState } from "react";
import { useI18n } from "../lib/i18n/index.jsx";
import "./sheet.css";

const CLOSE_MS = 200;

export function Sheet({ open, title, sub, onClose, children }) {
  const { t } = useI18n();

  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);
  const box = useRef(null);
  const returnTo = useRef(null);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setClosing(false);
      return undefined;
    }
    if (!mounted) return undefined;
    setClosing(true);
    const id = setTimeout(() => {
      setMounted(false);
      setClosing(false);
    }, CLOSE_MS);
    return () => clearTimeout(id);
  }, [open, mounted]);

  useEffect(() => {
    if (!mounted) return undefined;
    const was = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = was;
    };
  }, [mounted]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return undefined;
    returnTo.current = document.activeElement;
    const node = box.current;
    const target = node ? node.querySelector("[data-autofocus]") || node : null;
    if (target && target.focus) target.focus({ preventScroll: true });
    return () => {
      const back = returnTo.current;
      if (back && back.focus) back.focus({ preventScroll: true });
    };
  }, [open]);

  if (!mounted) return null;

  const tail = closing ? " is-closing" : "";
  return (
    <div className={"sheet-overlay" + tail} onMouseDown={onClose}>
      <div
        className={"sheet" + tail}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={box}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <span className="sheet-grip" aria-hidden="true" />

        <button
          className="sheet-close"
          type="button"
          onClick={onClose}
          aria-label={t("account.sheetClose")}
        >
          ✕
        </button>

        <div className="sheet-head">
          <h3 className="sheet-title">{title}</h3>
          {sub && <p className="sheet-sub">{sub}</p>}
        </div>

        {children}
      </div>
    </div>
  );
}
