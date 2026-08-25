const KEY = "prosto_ref";
const LIFETIME_MS = 30 * 24 * 60 * 60 * 1000;

const SHAPE = /^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4,16}$/;

export function rememberRef(search = window.location.search) {
  let code = "";
  try {
    code = (new URLSearchParams(search).get("ref") || "").trim().toUpperCase();
  } catch {
    return;
  }
  if (!SHAPE.test(code)) return;

  try {
    localStorage.setItem(KEY, JSON.stringify({ code, at: Date.now() }));
  } catch {}
}

export function takeRef() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (!saved || !SHAPE.test(saved.code || "")) return null;
    if (!saved.at || Date.now() - saved.at > LIFETIME_MS) {
      forgetRef();
      return null;
    }
    return saved.code;
  } catch {
    return null;
  }
}

export function forgetRef() {
  try {
    localStorage.removeItem(KEY);
  } catch {}
}
