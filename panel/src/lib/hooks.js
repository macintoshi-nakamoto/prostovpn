import { useCallback, useEffect, useRef, useState } from "react";

export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const runId = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback((quiet = false) => {
    const id = ++runId.current;
    if (!quiet) setState((s) => ({ ...s, loading: true, error: null }));

    return Promise.resolve()
      .then(() => fnRef.current())
      .then((data) => {
        if (id === runId.current) setState({ loading: false, error: null, data });
        return data;
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        if (id === runId.current) setState((s) => ({ loading: false, error, data: s.data }));
      });
  }, []);

  useEffect(() => {
    run();
  }, deps);

  return { ...state, reload: run, setData: (data) => setState((s) => ({ ...s, data })) };
}

export function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function usePolling(callback, intervalMs) {
  const saved = useRef(callback);
  saved.current = callback;

  useEffect(() => {
    if (!intervalMs) return undefined;
    const tick = () => {
      if (document.visibilityState === "visible") saved.current();
    };
    const timer = setInterval(tick, intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
}

export function useLockScroll(active = true) {
  useEffect(() => {
    if (!active) return undefined;
    const { body } = document;
    const prevOverflow = body.style.overflow;
    const prevPad = body.style.paddingRight;
    const width = window.innerWidth - document.documentElement.clientWidth;
    body.style.overflow = "hidden";
    if (width > 0) body.style.paddingRight = `${width}px`;
    return () => {
      body.style.overflow = prevOverflow;
      body.style.paddingRight = prevPad;
    };
  }, [active]);
}

export function useEscape(handler, active = true) {
  useEffect(() => {
    if (!active) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") handler();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handler, active]);
}

export function useSort(initialKey, initialDir = "desc") {
  const [sort, setSort] = useState({ key: initialKey, dir: initialDir });
  const toggle = useCallback((key) => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  }, []);
  return { sort, toggle };
}

export function sortRows(rows, { key, dir }, accessors = {}) {
  if (!key) return rows;
  const get = accessors[key] || ((row) => row[key]);
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = get(a);
    const bv = get(b);

    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string" && typeof bv === "string") return sign * av.localeCompare(bv, "ru");
    return sign * (Number(av) - Number(bv));
  });
}
