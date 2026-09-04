import { Navigate, Route, Routes } from "react-router-dom";
import { AdminLayout } from "./layout/AdminLayout";
import { useSession } from "./lib/session";
import { Loading } from "./ui";
import { LoginPage } from "./features/auth/LoginPage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { FunnelPage } from "./features/funnel/FunnelPage";
import { UsersPage } from "./features/users/UsersPage";
import { CalendarPage } from "./features/calendar/CalendarPage";
import { ServersPage } from "./features/servers/ServersPage";
import { KeysPage } from "./features/keys/KeysPage";
import { PlansPage } from "./features/plans/PlansPage";
import { ReleasesPage } from "./features/releases/ReleasesPage";
import { TunnelFilePage } from "./features/tunnel/TunnelFilePage";
import { OrdersPage } from "./features/orders/OrdersPage";
import { AuditPage } from "./features/audit/AuditPage";

export function App() {
  const { isAuthenticated, checking } = useSession();

  if (checking) {
    return (
      <div className="ax-root" style={{ minHeight: "100vh" }}>
        <Loading text="Проверяем доступ" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<AdminLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="users/:userId" element={<UsersPage />} />
        <Route path="funnel" element={<FunnelPage />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="servers" element={<ServersPage />} />
        <Route path="keys" element={<KeysPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="plans" element={<PlansPage />} />
        <Route path="releases" element={<ReleasesPage />} />
        <Route path="tunnel-file" element={<TunnelFilePage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
