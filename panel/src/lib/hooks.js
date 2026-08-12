import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Загрузка данных с состояниями и перезапросом.
 *
 * Гонку решаем счётчиком, а не только AbortController: медленный первый
 * ответ не должен затирать быстрый второй, даже если запрос уже не отменить.
 */
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
    // Зависимости задаёт вызывающий — они и решают, когда перезапрашивать.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, reload: run, setData: (data) => setState((s) => ({ ...s, data })) };
}

/** Задержка значения — чтобы поиск не бил по сети на каждой букве. */
export function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** Периодическое обновление; на скрытой вкладке не тратим запросы. */
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

/** Блокировка прокрутки фона под шторкой, без «прыжка» из-за скроллбара. */
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

/** Сортировка таблиц: клик по колонке переключает направление. */
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
    // Пустые значения всегда внизу — иначе «—» вытесняет содержательные строки.
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "string" && typeof bv === "string") return sign * av.localeCompare(bv, "ru");
    return sign * (Number(av) - Number(bv));
  });
}
