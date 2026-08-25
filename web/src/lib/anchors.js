import { useEffect } from "react";
import { markRevealed, prefersReducedMotion } from "./hooks";

const HEADER = 76;

const SETTLE_MS = 110;

const START_MS = 260;

const MAX_WAIT_MS = 1400;

const AT_PLACE_PX = 8;

function hideSection(section) {
  const nodes = [];
  if (section.hasAttribute("data-revealed")) nodes.push(section);
  nodes.push(...section.querySelectorAll("[data-revealed]"));

  for (const node of nodes) {
    node.setAttribute("data-reveal", node.getAttribute("data-revealed") || "up");
    node.removeAttribute("data-revealed");
  }

  return () => {
    void section.offsetHeight;
    for (const node of nodes) markRevealed(node);
  };
}

function afterScrollSettles(run) {
  let done = false;
  let quiet = 0;
  let guard = 0;

  const finish = () => {
    if (done) return;
    done = true;
    window.removeEventListener("scroll", tick);
    clearTimeout(quiet);
    clearTimeout(guard);
    run();
  };

  const tick = () => {
    clearTimeout(quiet);
    quiet = setTimeout(finish, SETTLE_MS);
  };

  window.addEventListener("scroll", tick, { passive: true });
  guard = setTimeout(finish, MAX_WAIT_MS);
  quiet = setTimeout(finish, START_MS);
}

export function goToSection(id) {
  const section = document.getElementById(id);
  if (!section) return false;

  const top = Math.max(0, section.getBoundingClientRect().top + window.scrollY - HEADER);

  if (prefersReducedMotion()) {
    window.scrollTo({ top });
    return true;
  }

  const show = hideSection(section);
  window.scrollTo({ top, behavior: "smooth" });

  if (Math.abs(window.scrollY - top) < AT_PLACE_PX) {
    show();
  } else {
    afterScrollSettles(show);
  }
  return true;
}

export function useAnchorReveal() {
  useEffect(() => {
    const onClick = (event) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

      const link = event.target.closest?.('a[href^="#"]');
      if (!link) return;

      const id = link.getAttribute("href").slice(1);
      if (!id) return;

      if (goToSection(id)) {
        event.preventDefault();

        history.replaceState(null, "", `#${id}`);
      }
    };

    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
}
