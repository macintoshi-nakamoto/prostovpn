import { Link } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader.jsx";
import { SiteFooter } from "../components/SiteFooter.jsx";
import { LEGAL_DOCS, LEGAL_NAV } from "../lib/legal/index.js";
import "./legal-doc.css";

/*
 * Юридические документы: оферта, политика конфиденциальности, правила
 * использования, возвраты, лицензии.
 *
 * Один компонент на все пять: различается только содержимое, а вёрстка
 * договора не должна зависеть от того, какой это договор. Тексты лежат
 * структурой (заголовок, абзац, список, таблица), а не готовым HTML: так их
 * нельзя случайно сломать разметкой, а нумерация пунктов остаётся ровно
 * такой, как в утверждённой редакции.
 *
 * Документы только на русском — и это не недоделка: сама оферта (п. 21.6)
 * говорит, что соглашение составлено на русском и русская редакция имеет
 * приоритет. Перевод создавал бы вторую редакцию, за которую никто не
 * отвечает; вместо него — строка-пояснение для англоязычного интерфейса.
 */
export function LegalDoc({ doc }) {
  const document = LEGAL_DOCS[doc];
  if (!document) return null;

  return (
    <div className="lgd">
      <SiteHeader />

      <section className="lgd-hero">
        <div className="wrap lgd-hero-in">
          <div className="lgd-crumbs">
            <Link to="/">Главная</Link>
            <span>/</span>
            <span className="lgd-crumb-current">{document.crumb}</span>
          </div>
          <h1>{document.title}</h1>
          {document.lead && <p className="lgd-lead">{document.lead}</p>}
          <div className="lgd-meta">
            <span>{document.revision}</span>
            <span>{document.url}</span>
          </div>
        </div>
      </section>

      <section className="lgd-body">
        <div className="wrap lgd-body-in">
          <nav className="lgd-side" aria-label="Документы">
            {LEGAL_NAV.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={`lgd-side-link${item.key === doc ? " lgd-side-on" : ""}`}
              >
                {item.label}
              </Link>
            ))}
          </nav>

          <article className="lgd-text">
            {document.blocks.map((block, index) => (
              <Block key={index} block={block} />
            ))}

            <p className="lgd-sign">{document.footer}</p>
          </article>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}

function Block({ block }) {
  switch (block.type) {
    case "h2":
      return <h2 className="lgd-h2">{block.text}</h2>;
    case "h3":
      return <h3 className="lgd-h3">{block.text}</h3>;
    case "p":
      return <p className="lgd-p">{block.text}</p>;
    case "note":
      return (
        <div className="lgd-note">
          {block.items.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </div>
      );
    case "ul":
      return (
        <ul className="lgd-ul">
          {block.items.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      );
    case "table":
      // Таблица шире экрана телефона всегда: прокручиваем её саму, а не
      // страницу — иначе весь документ уезжает вбок.
      return (
        <div className="lgd-table-wrap">
          <table className="lgd-table">
            <thead>
              <tr>
                {block.head.map((cell) => (
                  <th key={cell}>{cell}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row) => (
                <tr key={row[0]}>
                  {row.map((cell, i) => (
                    <td key={i}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    default:
      return null;
  }
}
