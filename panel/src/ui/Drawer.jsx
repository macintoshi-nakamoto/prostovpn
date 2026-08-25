import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useEscape, useLockScroll } from "../lib/hooks";

export function Drawer({ onClose, head, children }) {
  useLockScroll(true);
  useEscape(onClose);

  return createPortal(
    <div className="gd-overlay" onClick={onClose}>
      <div className="gd-drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="gd-drawer-head">
          {head}
          <button className="gd-x" onClick={onClose} aria-label="Закрыть">
            <X size={17} />
          </button>
        </div>
        <div className="gd-drawer-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
