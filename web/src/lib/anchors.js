/*
 * Переход по пунктам меню: доезжаем до секции и проигрываем её появление
 * заново.
 *
 * Обычное появление срабатывает один раз — наблюдатель отключается, как
 * только блок показался. Дальше человек прокрутил страницу до конца, нажал
 * «Тарифы» и приехал к готовой секции: переход выглядит как прыжок, потому
 * что играть уже нечему. Здесь секция сначала прячется, потом страница
 * доезжает, и только на месте содержимое собирается — каскадом, теми же
 * кадрами, что и при первой прокрутке.
 *
 * Прятать до прокрутки, а показывать после — важно именно в таком порядке.
 * Если проиграть сразу, движение случится за экраном, и человек приедет
 * ровно к тому же готовому блоку.
 */

import { useEffect } from "react";
import { markRevealed, prefersReducedMotion } from "./hooks";

// Высота закреплённой шапки: без поправки начало секции уезжает под неё.
const HEADER = 76;

// Прокрутку считаем законченной, когда столько миллисекунд не было ни
// одного события. Меньше — срабатывает на паузах между кадрами плавной
// прокрутки, больше — появление заметно опаздывает за приездом.
const SETTLE_MS = 110;

// Фора на запуск: между вызовом scrollTo и первым событием проходит кадр,
// а то и несколько. Без форы тишина этого промежутка считалась бы приездом,
// и секция проявлялась бы, ещё не показавшись на экране.
const START_MS = 260;

// Страховка на случай, если событий прокрутки не будет вовсе: например,
// секция уже на месте или система запретила плавный ход.
const MAX_WAIT_MS = 1400;

/** Уже приехали — доводить нечего. */
const AT_PLACE_PX = 8;

/**
 * Прячет всё, что в секции уже показано, и возвращает функцию, которая
 * покажет это заново.
 *
 * Вариант движения хранится в значении атрибута, поэтому переносим его
 * туда-обратно, а не пересоздаём: у картинок это «art», у заголовков
 * «zoom», и подменять их одним «up» значит поменять характер анимации.
 */
function hideSection(section) {
  const nodes = [];
  if (section.hasAttribute("data-revealed")) nodes.push(section);
  nodes.push(...section.querySelectorAll("[data-revealed]"));

  for (const node of nodes) {
    node.setAttribute("data-reveal", node.getAttribute("data-revealed") || "up");
    node.removeAttribute("data-revealed");
  }

  return () => {
    // Чтение раскладки между снятием и возвратом атрибута обязательно:
    // без него браузер схлопнет оба изменения в один кадр и анимация
    // просто не начнётся заново.
    void section.offsetHeight;
    for (const node of nodes) markRevealed(node);
  };
}

/**
 * Ждёт, пока прокрутка успокоится, и один раз вызывает `run`.
 *
 * Событие scrollend поддержано не везде, поэтому тишину ловим сами.
 */
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

/**
 * Прокручивает к секции с якорем `id` и проигрывает её появление.
 *
 * Возвращает false, если такой секции на странице нет: тогда ссылку нужно
 * оставить браузеру, а не глотать её молча.
 */
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
    /*
    Ехать некуда — играем сразу, иначе ждали бы полторы секунды
    страховочного таймера на пустом месте. Сюда же попадает случай, когда
    браузер не умеет плавную прокрутку и перескочил мгновенно.

    Именно вызовом, а не через requestAnimationFrame: кадры не выдаются
    свёрнутому окну и вкладке в фоне, и появление там не сыграло бы вообще
    никогда. Перерисовку между «спрятать» и «показать» обеспечивает чтение
    раскладки внутри show.
    */
    show();
  } else {
    afterScrollSettles(show);
  }
  return true;
}

/**
 * Перехватывает клики по внутренним якорям на всей странице.
 *
 * Один обработчик на документ, а не по обработчику на ссылку: якоря есть и
 * в шапке, и в кнопках секций («Подключить», «Как это работает»), и все они
 * должны вести себя одинаково.
 */
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
        // Адрес обновляем сами: preventDefault отменил и переход, и запись
        // якоря в строку браузера, а ссылкой на раздел люди делятся.
        history.replaceState(null, "", `#${id}`);
      }
    };

    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
}
