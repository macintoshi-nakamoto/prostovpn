import { useCallback, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { RefreshCw, UserPlus } from "lucide-react";
import { plansApi, usersApi } from "../../lib/api";
import { useAsync, useDebounced, useSort, sortRows } from "../../lib/hooks";
import { USER_STATUS_FILTERS } from "../../lib/status";
import { bytes, money, num } from "../../lib/format";
import { Button, Card, ErrorBox, PageHead, SearchInput, Seg, Table, Tile } from "../../ui";
import { userColumns } from "./UsersTable";
import { UserDrawer } from "./UserDrawer";
import { CreateUserModal } from "./CreateUserModal";

const SORT_ACCESSORS = {
  name: (u) => u.name || u.login,
  traffic: (u) => u.trafficUsedBytes,
  price: (u) => Number(u.price),
  expires: (u) => (u.expiresAt ? Date.parse(u.expiresAt) : null),
  paid: (u) => Number(u.paidTotal),
  created: (u) => Date.parse(u.createdAt),
};

export function UsersPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [creating, setCreating] = useState(false);
  const debouncedQuery = useDebounced(query, 300);
  const { sort, toggle } = useSort("created", "desc");

  const navigate = useNavigate();
  const { userId } = useParams();

  // Поиск и фильтр уходят на сервер: он один знает про все статусы и умеет
  // искать по публичному номеру, логину, имени и контакту сразу.
  const users = useAsync(
    () => usersApi.list({ q: debouncedQuery || undefined, status }),
    [debouncedQuery, status],
  );
  const plans = useAsync(() => plansApi.list(), []);

  const rows = useMemo(
    () => sortRows(users.data || [], sort, SORT_ACCESSORS),
    [users.data, sort],
  );

  const totals = useMemo(() => {
    const list = users.data || [];
    return {
      count: list.length,
      online: list.filter((u) => u.isOnline).length,
      revenue: list.reduce((sum, u) => sum + Number(u.price || 0), 0),
      traffic: list.reduce((sum, u) => sum + Number(u.trafficUsedBytes || 0), 0),
    };
  }, [users.data]);

  const openUser = useCallback((user) => navigate(`/users/${user.id}`), [navigate]);
  const closeUser = useCallback(() => navigate("/users"), [navigate]);

  // После действия в шторке список должен показать новое состояние, но без
  // мигания «загружаем»: тихое обновление.
  const refreshQuietly = useCallback(() => users.reload(true), [users]);

  return (
    <div className="gd-root">
      <PageHead title="Пользователи" sub="Доступы, тарифы, трафик и оплата">
        <Button onClick={() => users.reload()} title="Обновить">
          <RefreshCw size={15} />
        </Button>
        <Button variant="primary" onClick={() => setCreating(true)}>
          <UserPlus size={16} />
          Новый пользователь
        </Button>
      </PageHead>

      <div className="gd-tiles" style={{ gridTemplateColumns: "repeat(4, minmax(0,1fr))", marginBottom: 16 }}>
        <Tile label="Всего клиентов" value={num(totals.count)} />
        <Tile label="Сейчас онлайн" value={num(totals.online)} dot="var(--gd-pos)" />
        <Tile label="Сумма подписок" value={money(totals.revenue)} />
        <Tile label="Израсходовано трафика" value={bytes(totals.traffic)} />
      </div>

      <div
        style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}
      >
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Поиск по ID, логину, имени или контакту"
          style={{ flex: "1 1 320px", maxWidth: 460 }}
        />
        <Seg options={USER_STATUS_FILTERS} value={status} onChange={setStatus} />
      </div>

      <ErrorBox error={users.error} onRetry={users.reload} />

      <Card className="gd-table-card">
        <Table
          columns={userColumns}
          rows={rows}
          keyOf={(u) => u.id}
          onRowClick={openUser}
          sort={sort}
          onSort={toggle}
          loading={users.loading && !users.data}
          empty={query ? `По запросу «${query}» никого нет` : "Пользователей пока нет"}
        />
      </Card>

      {userId && (
        <UserDrawer
          userId={Number(userId)}
          plans={plans.data || []}
          onClose={closeUser}
          onChanged={refreshQuietly}
        />
      )}

      {creating && (
        <CreateUserModal
          plans={plans.data || []}
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setCreating(false);
            users.reload(true);
            navigate(`/users/${created.user.id}`);
          }}
        />
      )}
    </div>
  );
}
