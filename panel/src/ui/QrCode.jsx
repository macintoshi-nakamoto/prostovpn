import { useMemo } from "react";
import qrcode from "qrcode-generator";

const QUIET = 4;

export function QrCode({ value, label, fallback }) {
  const drawn = useMemo(() => {
    try {
      const qr = qrcode(0, "L");
      qr.addData(value);
      qr.make();

      const count = qr.getModuleCount();

      let path = "";
      for (let row = 0; row < count; row += 1) {
        for (let col = 0; col < count; col += 1) {
          if (qr.isDark(row, col)) path += `M${col} ${row}h1v1h-1z`;
        }
      }
      return { count, path };
    } catch {
      return null;
    }
  }, [value]);

  if (!drawn) return fallback || null;

  const side = drawn.count + QUIET * 2;
  return (
    <svg
      className="qr"
      viewBox={`0 0 ${side} ${side}`}
      role="img"
      aria-label={label}
      shapeRendering="crispEdges"
    >
      <rect x="0" y="0" width={side} height={side} fill="#ffffff" />
      <g transform={`translate(${QUIET} ${QUIET})`}>
        <path d={drawn.path} fill="#000000" />
      </g>
    </svg>
  );
}
