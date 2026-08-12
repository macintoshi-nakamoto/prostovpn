import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useEscape, useLockScroll } from "../lib/hooks";
import { Button } from "./primitives";

export function Modal({ title, onClose, children, footer, wide = false }) {
  useLockScroll(true);
  useEscape(onClose);

  return createPortal(
    <div className="gd-modal-overlay" onClick={onClose}>
      <div
        className={`gd-modal${wide ? " wide" : ""}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {title && <div className="gd-modal-title">{title}</div>}
        {children}
        {footer && <div className="gd-modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

// ── Императивные диалоги ────────────────────────────────────────────────────
// `await confirmDialog({...})` вместо window.confirm: системные диалоги
// выбиваются из оформления и блокируют поток.

let emit = null;

export function confirmDialog(options) {
  return new Promise((resolve) => {
    if (!emit) return resolve(window.confirm(options.title));
    emit({ kind: "confirm", resolve, ...options });
  });
}

export function promptDialog(options) {
  return new Promise((resolve) => {
    if (!emit) return resolve(window.prompt(options.title, options.defaultValue ?? ""));
    emit({ kind: "prompt", resolve, ...options });
  });
}

export function DialogHost() {
  const [dialog, setDialog] = useState(null);
  const [value, setValue] = useState("");

  useEffect(() => {
    emit = (next) => {
      setDialog(next);
      if (next?.kind === "prompt") setValue(next.defaultValue ?? "");
    };
    return () => {
      emit = null;
    };
  }, []);

  if (!dialog) return null;

  const finish = (result) => {
    dialog.resolve(result);
    setDialog(null);
  };
  const cancel = () => finish(dialog.kind === "confirm" ? false : null);
  const accept = () => finish(dialog.kind === "confirm" ? true : value);

  return (
    <Modal
      title={dialog.title}
      onClose={cancel}
      footer={
        <>
          <Button size="sm" onClick={cancel}>
            {dialog.cancelText || "Отмена"}
          </Button>
          <Button size="sm" variant={dialog.danger ? "danger" : "primary"} onClick={accept}>
            {dialog.confirmText || "Подтвердить"}
          </Button>
        </>
      }
    >
      {dialog.message && (
        <div style={{ fontSize: 13.5, color: "var(--gd-dim)", lineHeight: 1.5 }}>{dialog.message}</div>
      )}
      {dialog.kind === "prompt" && (
        <input
          className="gd-input"
          value={value}
          placeholder={dialog.placeholder}
          inputMode={dialog.numeric ? "decimal" : undefined}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") accept();
          }}
          style={{ marginTop: 16, background: "var(--gd-tile)" }}
        />
      )}
    </Modal>
  );
}
