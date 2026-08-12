import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, RotateCw, ShieldOff } from "lucide-react";
import { keysApi, serversApi } from "../../lib/api";
import { useAsync, useDebounced } from "../../lib/hooks";
import { ago, bytes, flag, num } from "../../lib/format";
import { userStatus } from "../../lib/status";
import {
  Button,
  Card,
  CellName,
  Copyable,
  Dot,
  ErrorBox,
  PageHead,
  SearchInput,
  Table,
  Tile,
  confirmDialog,
} from "../../ui";

/**
 * Какой аккаунт на каком сервере и с каким ключом.
 *
 * Отдельный раздел, потому что вопрос третий: не «что у человека» и не
 * «что на сервере», а связь между ними.
 */
export function KeysPage() {
  const [query, setQuery] = useState("");
  const [serverId, setServerId] = useState("");
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const debounced = useDebounced(query, 300);

  const servers = useAsync(() => serversApi.list(), []);
  const keys = useAsync(
    () => keysApi.list({ q: debounced || undefined, server_id: serverId || undefined }),
    [debounced, serverId],
  );

  const rows = keys.data || [];
  const byServer = useMemo(() => {
    const map = new Map();
    for (const row of rows) map.set(row.serverId, (map.get(row.serverId) || 0) + 1);
    return map;
  }, [rows]);

  const revoke = async (row) => {
    const ok = await confirmDialog({
      title: "Отозвать ключ?",
      message: `${row.name || row.login} потеряет доступ к серверу «${row.country || row.serverName}». Пир будет снят с сервера.`,
      confirmText: "Отозвать",
      danger: true,
    });
    if (!ok) return;
    setBusy(row.id);
    setNotice(null);
    try {
      await keysApi.revoke(row.id);
      keys.reload(true);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const reissue = async (row) => {
    const ok = await confirmDialog({
      title: "Перевыпустить ключ?",
      message: "Старый конфиг перестанет работать — клиент получит новый при следующем входе.",
      confirmText: "Перевыпустить",
    });
    if (!ok) return;
    setBusy(row.id);
    setNotice(null);
    try {
      await keysApi.reissue(row.userId, row.serverId);
      keys.reload(true);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const syncAll = async () => {
    setBusy("sync");
    setNotice(null);
    try {
      const results = await keysApi.syncAll();
      const errors = results.filter((r) => r.error);
      setNotice(
        errors.length
          ? `Не ответили: ${errors.map((r) => r.error).join("; ")}`
          : `Обход завершён, серверов: ${results.length}`,
      );
      keys.reload(true);
    } catch (err) {
      setNotice(err.message);
    } finally {
      setBusy(null);
    }
  };

  const columns = [
    {
      key: "user",
      title: "Аккаунт",
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <Dot color={userStatus(row.userStatus).color} />
          <Link to={`/users/${row.userId}`} style={{ color: "inherit", textDecoration: "none" }}>
            <CellName title={row.name || row.login} sub={row.publicId} />
          </Link>
        </div>
      ),
    },
    {
      key: "server",
      title: "Сервер",
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
          <span style={{ fontSize: 17 }}>{flag(row.countryCode)}</span>
          <CellName
            title={`${row.country || row.serverName}${row.city ? `, ${row.city}` : ""}`}
            sub={row.serverName}
          />
        </div>
      ),
    },
    {
      key: "address",
      title: "Адрес в подсети",
      render: (row) => (
        <span className="gd-mono" style={{ fontSize: 12.5, color: "var(--gd-dim)" }}>
          {row.address || "—"}
        </span>
      ),
    },
    {
      key: "key",
      title: "Публичный ключ",
      render: (row) =>
        row.publicKey ? (
          <span style={{ fontSize: 12, color: "var(--gd-dim)", maxWidth: 180, display: "inline-block" }}>
            <Copyable text={row.publicKey}>{`${row.publicKey.slice(0, 14)}…`}</Copyable>
          </span>
        ) : (
          <span style={{ color: "var(--gd-faint)" }}>общий</span>
        ),
    },
    {
      key: "traffic",
      title: "Трафик",
      num: true,
      render: (row) => bytes(row.rxBytes + row.txBytes),
    },
    {
      key: "handshake",
      title: "Подключался",
      render: (row) => (
        <span style={{ fontSize: 12.5, color: "var(--gd-dim)" }}>
          {row.lastHandshakeAt ? ago(row.lastHandshakeAt) : "ни разу"}
        </span>
      ),
    },
    {
      key: "actions",
      title: "",
      render: (row) => (
        <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
          <Button
            size="sm"
            disabled={busy === row.id}
            title="Перевыпустить"
            onClick={(e) => {
              e.stopPropagation();
              reissue(row);
            }}
          >
            <RotateCw size={14} />
          </Button>
          <Button
            size="sm"
            variant="danger"
            disabled={busy === row.id}
            title="Отозвать"
            onClick={(e) => {
              e.stopPropagation();
              revoke(row);
            }}
          >
            <ShieldOff size={14} />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="gd-root">
      <PageHead title="Аккаунты на серверах" sub="Кто, где и с каким ключом подключён">
        <Button disabled={busy === "sync"} onClick={syncAll}>
          <RefreshCw size={15} />
          Снять трафик со всех
        </Button>
      </PageHead>

      <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))", marginBottom: 16 }}>
        <Tile label="Активных ключей" value={num(rows.length)} />
        <Tile label="Серверов задействовано" value={num(byServer.size)} />
        <Tile
          label="Суммарный трафик"
          value={bytes(rows.reduce((sum, r) => sum + r.rxBytes + r.txBytes, 0))}
        />
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Поиск по клиенту, серверу или адресу"
          style={{ flex: "1 1 300px", maxWidth: 440 }}
        />
        <select
          className="gd-select"
          value={serverId}
          onChange={(e) => setServerId(e.target.value)}
          style={{ width: "auto", minWidth: 180 }}
        >
          <option value="">Все серверы</option>
          {(servers.data || []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.country || s.name}
            </option>
          ))}
        </select>
      </div>

      {notice && (
        <div className="gd-error" style={{ marginBottom: 12, background: "var(--gd-card)", color: "var(--gd-dim)" }}>
          {notice}
        </div>
      )}
      <ErrorBox error={keys.error} onRetry={keys.reload} />

      <Card className="gd-table-card">
        <Table
          columns={columns}
          rows={rows}
          keyOf={(row) => row.id}
          loading={keys.loading && !keys.data}
          empty="Ключей не найдено"
        />
      </Card>
    </div>
  );
}
