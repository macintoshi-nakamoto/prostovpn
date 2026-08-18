import { useState } from "react";
import { serversApi } from "../../lib/api";
import { Button, Field, Modal, Seg } from "../../ui";

const TEMPLATE_HINT = `[Interface]
Address = {address}
PrivateKey = {private_key}
DNS = 1.1.1.1, 1.0.0.1
MTU = 1280

[Peer]
PublicKey = <публичный ключ сервера>
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = <адрес>:51820
PersistentKeepalive = 25`;

const EMPTY = {
  name: "",
  country: "",
  countryEn: "",
  city: "",
  cityEn: "",
  countryCode: "",
  host: "",
  port: 51820,
  altPorts: "",
  provisioning: "ssh",
  sharedConfig: "",
  sshHost: "",
  sshPort: 22,
  sshUser: "root",
  sshPassword: "",
  sshKey: "",
  awgTemplate: "",
  isActive: true,
  sortOrder: 0,
  issueKeys: true,
};

/**
 * Добавление и настройка сервера.
 *
 * При своей генерации панель сама создаёт пару ключей на каждого клиента —
 * от администратора нужен только доступ по SSH и шаблон конфига.
 */
export function ServerModal({ server, onClose, onSaved }) {
  const [form, setForm] = useState(() =>
    server
      ? { ...EMPTY, ...server, sshPassword: "", sshKey: "" }
      : EMPTY,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const isSsh = form.provisioning === "ssh";
  // Шаблон и общий конфиг в списке серверов не приезжают — иначе они ехали бы
  // в каждой строке при каждой загрузке страницы. Поэтому у заведённого узла
  // пустое поле значит «оставить прежний», ровно как у пароля SSH, и требовать
  // его заново незачем: иначе «Сохранить» не нажать вообще, даже чтобы
  // поправить город. Заполнить обязаны только там, где сохранённого значения
  // ещё нет: у нового сервера и при переводе общего узла на свою генерацию.
  const needTemplate = !server || (isSsh && !server.hasTemplate);
  const invalid =
    !form.name.trim() ||
    !form.host.trim() ||
    (needTemplate && isSsh && !(form.awgTemplate || "").trim()) ||
    (needTemplate && !isSsh && !(form.sharedConfig || "").trim());

  const save = async () => {
    if (invalid) return;
    setBusy(true);
    setError(null);
    const payload = {
      ...form,
      port: Number(form.port) || 51820,
      sshPort: Number(form.sshPort) || 22,
      sortOrder: Number(form.sortOrder) || 0,
      countryCode: (form.countryCode || "").toUpperCase(),
    };
    try {
      const result = server
        ? await serversApi.update(server.id, payload)
        : await serversApi.create(payload);
      onSaved(result);
    } catch (err) {
      setError(err.message || "Не удалось сохранить");
      setBusy(false);
    }
  };

  return (
    <Modal
      title={server ? `Сервер «${server.name}»` : "Новый сервер"}
      wide
      onClose={onClose}
      footer={
        <>
          <Button size="sm" onClick={onClose}>
            Отмена
          </Button>
          <Button size="sm" variant="primary" disabled={busy || invalid} onClick={save}>
            {busy ? "Сохраняем…" : server ? "Сохранить" : "Добавить"}
          </Button>
        </>
      }
    >
      <div className="gd-inset" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Название" hint="Внутреннее, клиент его не видит">
            <input className="gd-input" value={form.name} onChange={set("name")} placeholder="nl-ams-01" />
          </Field>
          <Field label="Адрес сервера">
            <input className="gd-input" value={form.host} onChange={set("host")} placeholder="185.10.20.30" />
          </Field>
        </div>

        {/*
        Запасные порты — против операторов, режущих канонический 51820.

        Узел слушает один порт, остальные заворачиваются на него правилом
        DNAT (deploy/extra-ports.sh). Здесь перечисляем только то, что реально
        доступно снаружи: список уезжает в приложение, и клиент будет честно
        перебирать каждый порт по полминуты. Лишний порт в списке — это
        потерянные полминуты у каждого, кому не повезло.
        */}
        <Field
          label="Запасные порты"
          hint="Через запятую. Сначала настройте их на узле: deploy/extra-ports.sh"
        >
          <input
            className="gd-input"
            value={form.altPorts || ""}
            onChange={set("altPorts")}
            placeholder="443, 2408, 8443"
          />
        </Field>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 90px", gap: 12 }}>
          <Field label="Страна" hint="Это видит клиент">
            <input className="gd-input" value={form.country || ""} onChange={set("country")} placeholder="Нидерланды" />
          </Field>
          <Field label="Город">
            <input className="gd-input" value={form.city || ""} onChange={set("city")} placeholder="Амстердам" />
          </Field>
          <Field label="Код">
            <input className="gd-input" value={form.countryCode || ""} onChange={set("countryCode")} placeholder="NL" maxLength={2} />
          </Field>
        </div>

        {/*
        Английские названия. Заполнять их необязательно: страну приложение
        возьмёт по коду из справочника, город — покажет русским. Поля нужны
        для случаев, где справочник не подходит: свои формулировки, город с
        неочевидным написанием, узел в стране без кода.

        До этого полей не было вовсе, и приложение с английским интерфейсом
        показывало кириллицу в списке стран — заполнить их администратору
        было нечем.
        */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Страна по-английски" hint="Пусто — возьмём по коду">
            <input className="gd-input" value={form.countryEn || ""} onChange={set("countryEn")} placeholder="Netherlands" />
          </Field>
          <Field label="Город по-английски" hint="Пусто — покажем русский">
            <input className="gd-input" value={form.cityEn || ""} onChange={set("cityEn")} placeholder="Amsterdam" />
          </Field>
        </div>

        <Field label="Как выдаём конфиги">
          <Seg
            gold
            full
            value={form.provisioning}
            onChange={(id) => setForm((f) => ({ ...f, provisioning: id }))}
            options={[
              { id: "ssh", label: "Своя генерация по SSH" },
              { id: "shared", label: "Общий ключ" },
            ]}
          />
        </Field>

        {isSsh ? (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 90px 1fr", gap: 12 }}>
              <Field label="SSH-хост" hint="Пусто — возьмём адрес сервера">
                <input className="gd-input" value={form.sshHost || ""} onChange={set("sshHost")} placeholder="185.10.20.30" />
              </Field>
              <Field label="Порт">
                <input className="gd-input" value={form.sshPort} onChange={set("sshPort")} />
              </Field>
              <Field label="Пользователь">
                <input className="gd-input" value={form.sshUser || ""} onChange={set("sshUser")} placeholder="root" />
              </Field>
            </div>

            <Field label="Пароль SSH" hint={server ? "Пусто — оставить прежний" : "Либо приватный ключ ниже"}>
              <input className="gd-input" type="password" value={form.sshPassword} onChange={set("sshPassword")} />
            </Field>

            <Field label="Приватный ключ SSH" hint={server ? "Пусто — оставить прежний" : "Необязательно, если задан пароль"}>
              <textarea className="gd-textarea" value={form.sshKey} onChange={set("sshKey")} placeholder="-----BEGIN RSA PRIVATE KEY-----" />
            </Field>

            <Field
              label="Шаблон конфига AmneziaWG"
              hint={
                needTemplate
                  ? "Обязательны поля {private_key} и {address} — панель подставит их для каждого клиента"
                  : "Пусто — оставить прежний. В новом обязательны {private_key} и {address}"
              }
            >
              <textarea
                className="gd-textarea"
                style={{ minHeight: 190 }}
                value={form.awgTemplate || ""}
                onChange={set("awgTemplate")}
                placeholder={TEMPLATE_HINT}
              />
            </Field>
          </>
        ) : (
          <Field
            label="Общий конфиг"
            hint={
              server
                ? "Пусто — оставить прежний. Его получат все — отозвать доступ одному человеку будет нельзя."
                : "Ссылка vpn:// или текст wg-quick. Его получат все — отозвать доступ одному человеку будет нельзя."
            }
          >
            <textarea
              className="gd-textarea"
              style={{ minHeight: 160 }}
              value={form.sharedConfig || ""}
              onChange={set("sharedConfig")}
              placeholder="vpn://..."
            />
          </Field>
        )}

        <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={form.isActive} onChange={set("isActive")} style={{ width: 16, height: 16, accentColor: "var(--gd-gold)" }} />
            Включён
          </label>
          {!server && (
            <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" checked={form.issueKeys} onChange={set("issueKeys")} style={{ width: 16, height: 16, accentColor: "var(--gd-gold)" }} />
              Сразу выдать ключи действующим клиентам
            </label>
          )}
        </div>

        {error && <div className="gd-error">{error}</div>}
      </div>
    </Modal>
  );
}
