import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "../lib/i18n/index.jsx";
import { tmaHaptic } from "../lib/telegram.js";
import "./faq-list.css";

/**
 * Вопросы и ответы — общий список для сайта и кабинета.
 *
 * Поиск по вопросу и ответу сразу, темы — чипами: по клику список
 * сужается до одной темы, а не прыгает по якорям (на телефоне якорь
 * уводит под шапку). Ответ раскрывается по нажатию; открытых может
 * быть сколько угодно — человек часто сравнивает два соседних.
 */

function normalize(text) {
  return (text || "").toLowerCase().replace(/ё/g, "е");
}

export function FaqList({ compact = false }) {
  const { raw, t } = useI18n();
  const blocks = raw("faq.blocks") || [];
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("");
  const [open, setOpen] = useState(() => new Set());
  const input = useRef(null);

  const needle = normalize(query.trim());
  const shown = useMemo(() => {
    return blocks
      .filter((block) => !topic || block.key === topic)
      .map((block) => ({
        ...block,
        items: block.items.filter(
          ([q, a]) => !needle || normalize(q).includes(needle) || normalize(a).includes(needle),
        ),
      }))
      .filter((block) => block.items.length > 0);
  }, [blocks, topic, needle]);

  // По поиску ответы раскрываем сразу: человек ищет фразу, а не заголовок.
  useEffect(() => {
    if (!needle) return;
    const all = new Set();
    shown.forEach((block) => block.items.forEach(([q]) => all.add(block.key + "|" + q)));
    setOpen(all);
  }, [needle, shown]);

  const toggle = (id) => {
    tmaHaptic("light");
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className={"fq" + (compact ? " fq-compact" : "")}>
      <label className="fq-search">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M16.5 16.5 21 21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
        <input
          ref={input}
          type="search"
          value={query}
          placeholder={t("faq.search")}
          onChange={(e) => setQuery(e.target.value)}
          autoCorrect="off"
          autoCapitalize="none"
        />
        {query ? (
          <button
            type="button"
            className="fq-clear"
            aria-label="×"
            onClick={() => {
              setQuery("");
              input.current?.focus();
            }}
          >
            ×
          </button>
        ) : null}
      </label>

      <div className="fq-topics" role="tablist">
        <button
          type="button"
          className={"fq-topic" + (topic ? "" : " is-on")}
          onClick={() => setTopic("")}
        >
          {t("faq.allTopics")}
        </button>
        {blocks.map((block) => (
          <button
            key={block.key}
            type="button"
            className={"fq-topic" + (topic === block.key ? " is-on" : "")}
            onClick={() => setTopic(topic === block.key ? "" : block.key)}
          >
            {block.h}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="fq-empty">{t("faq.empty")}</p>
      ) : (
        shown.map((block) => (
          <section className="fq-block" key={block.key} id={"faq-" + block.key}>
            <h2>{block.h}</h2>
            <div className="fq-items">
              {block.items.map(([q, a]) => {
                const id = block.key + "|" + q;
                const isOpen = open.has(id);
                return (
                  <div className={"fq-item" + (isOpen ? " is-open" : "")} key={q}>
                    <button
                      type="button"
                      className="fq-q"
                      aria-expanded={isOpen}
                      onClick={() => toggle(id)}
                    >
                      <span>{q}</span>
                      <i aria-hidden="true" />
                    </button>
                    <div className="fq-a">
                      <p>{a}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
