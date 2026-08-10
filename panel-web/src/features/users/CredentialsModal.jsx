import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button, Modal } from "../../ui";

/**
 * Готовые доступы для передачи клиенту.
 *
 * Отдельным окном, а не строчкой в списке: пароль виден один раз, и его
 * нужно успеть скопировать, пока окно открыто.
 */
export function CredentialsModal({ title = "Доступы созданы", login, password, publicId, onClose }) {
  const [copied, setCopied] = useState(false);

  const text = `Логин: ${login}\nПароль: ${password}`;
  const copyAll = () => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    });
  };

  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button size="sm" onClick={copyAll}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? "Скопировано" : "Скопировать всё"}
          </Button>
          <Button size="sm" variant="primary" onClick={onClose}>
            Готово
          </Button>
        </>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {publicId && <CredentialRow label="ID клиента" value={publicId} />}
        <CredentialRow label="Логин" value={login} />
        <CredentialRow label="Пароль" value={password} />
        <div style={{ fontSize: 12.5, color: "var(--gd-faint)", lineHeight: 1.5, marginTop: 4 }}>
          С этими доступами человек входит в приложение и сразу получает серверы. Пароль показывается
          один раз — сохраните его сейчас.
        </div>
      </div>
    </Modal>
  );
}

function CredentialRow({ label, value }) {
  const [copied, setCopied] = useState(false);
  return (
    <div
      style={{
        background: "var(--gd-tile)",
        borderRadius: 14,
        padding: "12px 14px",
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11.5, color: "var(--gd-faint)" }}>{label}</div>
        <div className="gd-mono" style={{ fontSize: 15, marginTop: 3, overflowWrap: "anywhere" }}>
          {value}
        </div>
      </div>
      <button
        className="gd-btn sm"
        style={{ marginLeft: "auto", flexShrink: 0 }}
        onClick={() => {
          navigator.clipboard?.writeText(value).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
          });
        }}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}
