import { useState } from "react";
import { Ban, Gauge, Gift, KeyRound, Power, ShieldAlert, Smartphone, Trash2, Wallet } from "lucide-react";
import { usersApi } from "../../lib/api";
import { money, trafficLimit } from "../../lib/format";
import { Button, Section, Toggle, confirmDialog } from "../../ui";
import { TrafficLimitModal } from "./TrafficLimitModal";
import { ExtendModal } from "./ExtendModal";
import { CredentialsModal } from "./CredentialsModal";

export function UserControls({ user, plans, onResult, onDeleted }) {
  const [busy, setBusy] = useState(null);
  const [modal, setModal] = useState(null);
  const [credentials, setCredentials] = useState(null);
  const [error, setError] = useState(null);

  const run = async (action, fn) => {
    setBusy(action);
    setError(null);
    try {
      const result = await fn();
      if (result) onResult(result);
      return result;
    } catch (err) {
      setError(err.message || "Не удалось выполнить");
      return null;
    } finally {
      setBusy(null);
    }
  };

  const toggleActive = () =>
    run("active", () => (user.isActive ? usersApi.disable(user.id) : usersApi.enable(user.id)));

  const toggleFree = () => run("free", () => usersApi.update(user.id, { isFree: !user.isFree }));

  const toggleBlock = async () => {
    if (user.isBlocked) return run("block", () => usersApi.unblock(user.id));

    const ok = await confirmDialog({
      title: `Заблокировать ${user.name || user.login}?`,
      message:
        "Вход в приложение закроется, живые сессии погаснут, а ключи будут сняты с серверов. " +
        "Снять блокировку можно в любой момент — ключи выдадутся заново.",
      confirmText: "Заблокировать",
      danger: true,
    });
    if (!ok) return null;
    return run("block", () => usersApi.block(user.id, "Заблокирован администратором"));
  };

  const resetPassword = async () => {
    const ok = await confirmDialog({
      title: "Сменить пароль?",
      message: "Старый пароль перестанет работать, все входы в приложение придётся выполнить заново.",
      confirmText: "Сменить",
      danger: true,
    });
    if (!ok) return;

    setBusy("password");
    setError(null);
    try {
      const { password } = await usersApi.resetPassword(user.id);
      const fresh = await usersApi.get(user.id);
      onResult(fresh);

      setCredentials({ login: user.login, password });
    } catch (err) {
      setError(err.message || "Не удалось сменить пароль");
    } finally {
      setBusy(null);
    }
  };

  const reissueSubscription = async () => {
    const ok = await confirmDialog({
      title: "Ссылка подписки скомпрометирована?",
      message:
        "Сменим ключи всех устройств и погасим все ссылки подписки. Устройства " +
        "переподключатся сами с новым конфигом, а утёкшая ссылка станет бесполезной.",
      confirmText: "Перевыпустить",
      danger: true,
    });
    if (!ok) return;

    setBusy("compromised");
    setError(null);
    try {
      const fresh = await usersApi.reissueSubscription(user.id);
      onResult(fresh);
    } catch (err) {
      setError(err.message || "Не удалось перевыпустить подписку");
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    const ok = await confirmDialog({
      title: `Удалить ${user.name || user.login}?`,
      message: "Вместе с пользователем удалятся его ключи, платежи и история. Действие необратимо.",
      confirmText: "Удалить",
      danger: true,
    });
    if (!ok) return;

    setBusy("delete");
    try {
      await usersApi.remove(user.id);
      onResult(null);
      onDeleted();
    } catch (err) {
      setError(err.message || "Не удалось удалить");
      setBusy(null);
    }
  };

  return (
    <>
      <Section title="Управление" sub="Изменения применяются сразу">
        {error && (
          <div className="gd-error" style={{ marginBottom: 10 }}>
            {error}
          </div>
        )}

        <div className="gd-menu">
          <ControlRow
            icon={<Power size={16} />}
            title="Доступ включён"
            sub={user.isActive ? "Приложение получает серверы" : "Вход есть, серверы не выдаются"}
          >
            <Toggle on={user.isActive} disabled={busy === "active" || user.isBlocked} onChange={toggleActive} />
          </ControlRow>

          <ControlRow
            icon={<Gift size={16} />}
            title="Бесплатный доступ"
            sub={
              user.isFree
                ? "Продления не пишут платежей, прогноз выручки эту учётку не ждёт"
                : "Метка для друзей и промо: выдуманные деньги не попадают в статистику"
            }
          >
            <Toggle on={user.isFree} disabled={busy === "free"} onChange={toggleFree} />
          </ControlRow>

          <ControlRow
            icon={<Ban size={16} />}
            title="Блокировка"
            sub={
              user.isBlocked
                ? user.blockedReason || "Вход запрещён, ключи сняты"
                : "Полный запрет входа со снятием ключей"
            }
          >
            <Button
              size="sm"
              variant={user.isBlocked ? "on" : "danger"}
              disabled={busy === "block"}
              onClick={toggleBlock}
            >
              {user.isBlocked ? "Разблокировать" : "Заблокировать"}
            </Button>
          </ControlRow>

          <ControlRow
            icon={<Gauge size={16} />}
            title="Лимит трафика"
            sub={`Сейчас: ${trafficLimit(user.trafficLimitBytes)}`}
          >
            <Button size="sm" onClick={() => setModal("traffic")}>
              Настроить
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy === "reset"}
              onClick={() => run("reset", () => usersApi.resetTraffic(user.id))}
            >
              Обнулить расход
            </Button>
          </ControlRow>

          <ControlRow
            icon={<Wallet size={16} />}
            title="Подписка"
            sub={
              user.expiresAt
                ? `${user.planName || user.plan} · ${money(user.price, user.currency)}`
                : "Не оплачена"
            }
          >
            <Button size="sm" variant="primary" onClick={() => setModal("extend")}>
              Продлить
            </Button>
          </ControlRow>

          <ControlRow
            icon={<Smartphone size={16} />}
            title="Ключи для iPhone"
            sub={
              !user.iosAccess
                ? "Не выдавались — на iPhone подключаются ссылкой vpn://"
                : user.iosBlocked
                  ? "Отключены: пиры сняты, кнопка в кабинете не работает"
                  : `Выдано ${user.iosKeysCount} из ${user.iosMaxKeys} · подробнее на вкладке «iPhone»`
            }
          >
            <Button
              size="sm"
              variant={user.iosAccess ? "" : "primary"}
              disabled={busy === "ios" || (user.iosAccess && !user.iosCanAdd)}
              onClick={() =>
                run("ios", () =>
                  user.iosAccess ? usersApi.iosAddKey(user.id) : usersApi.iosEnable(user.id),
                )
              }
            >
              {busy === "ios" ? "…" : user.iosAccess ? "Добавить ключ" : "Выдать ключ"}
            </Button>
          </ControlRow>

          <ControlRow icon={<KeyRound size={16} />} title="Пароль" sub="Показывается один раз после смены">
            <Button size="sm" disabled={busy === "password"} onClick={resetPassword}>
              Сменить
            </Button>
          </ControlRow>

          <ControlRow
            icon={<ShieldAlert size={16} />}
            title="Подписка"
            sub="Ссылка утекла — сменить ключи и погасить ссылки"
          >
            <Button
              size="sm"
              disabled={busy === "compromised"}
              onClick={reissueSubscription}
            >
              {busy === "compromised" ? "…" : "Перевыпустить"}
            </Button>
          </ControlRow>

          <ControlRow icon={<Trash2 size={16} />} title="Удаление" sub="Вместе со всей историей клиента">
            <Button size="sm" variant="danger" disabled={busy === "delete"} onClick={remove}>
              Удалить
            </Button>
          </ControlRow>
        </div>
      </Section>

      {modal === "traffic" && (
        <TrafficLimitModal
          user={user}
          onClose={() => setModal(null)}
          onSaved={(updated) => {
            setModal(null);
            onResult(updated);
          }}
        />
      )}

      {modal === "extend" && (
        <ExtendModal
          user={user}
          plans={plans}
          onClose={() => setModal(null)}
          onSaved={(updated) => {
            setModal(null);
            onResult(updated);
          }}
        />
      )}

      {credentials && (
        <CredentialsModal
          title="Новый пароль"
          login={credentials.login}
          password={credentials.password}
          onClose={() => setCredentials(null)}
        />
      )}
    </>
  );
}

function ControlRow({ icon, title, sub, children }) {
  return (
    <div className="gd-mrow">
      <span className="gd-badge" style={{ width: 34, height: 34 }}>
        {icon}
      </span>
      <div className="gd-mrow-l">
        <div className="gd-mrow-t">{title}</div>
        {sub && <div className="gd-mrow-s">{sub}</div>}
      </div>
      <div className="gd-mrow-r">{children}</div>
    </div>
  );
}
