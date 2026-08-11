import { useCallback, useEffect, useState } from "react";

const KEY = "vpn_panel_theme";

function initial() {
  const stored = localStorage.getItem(KEY);
  if (stored === "light" || stored === "dark") return stored;
  // Первый заход — как в системе; дальше решает выбор человека.
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function useTheme() {
  const [theme, setTheme] = useState(initial);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, toggle };
}
