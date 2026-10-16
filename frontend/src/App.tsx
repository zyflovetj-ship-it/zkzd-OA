import { useAuth } from "./auth/AuthContext";
import AppShell from "./layouts/AppShell";
import Login from "./pages/Login";

/**
 * 应用根组件：只负责「未登录 → 登录页 / 已登录 → 应用外壳」的切换。
 * 已登录后的路由由 AppShell 的多页签工作区接管（每个页签独立渲染一条路由）。
 */
export default function App() {
  const { user, loading } = useAuth();

  if (loading) return null;
  if (!user) return <Login />;

  return <AppShell />;
}
