import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import api, {
  clearTokens,
  getRefreshToken,
  setTokens,
  ApiError,
} from "../api/client";
import { authApi } from "../api/endpoints";
import type { MeOut, MenuOut } from "../types";

interface AuthState {
  user: MeOut | null;
  permissions: string[];
  dataScope: string;
  menus: MenuOut[];
  loading: boolean;
  hasPerm: (code: string) => boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeOut | null>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [dataScope, setDataScope] = useState<string>("all");
  const [menus, setMenus] = useState<MenuOut[]>([]);
  const [loading, setLoading] = useState(false);

  const login = async (username: string, password: string) => {
    const res = await api.post<{ access_token: string; refresh_token: string }>(
      "/api/auth/login",
      { username, password }
    );
    setTokens(res.data.access_token, res.data.refresh_token);
    const me = await api.get<MeOut>("/api/auth/me");
    setUser(me.data);
    setPermissions(me.data.permissions || []);
    setDataScope(me.data.data_scope || "all");
    const menusRes = await authApi.menus();
    setMenus(menusRes);
  };

  const logout = async () => {
    try {
      await api.post("/api/auth/logout", { refresh_token: getRefreshToken() });
    } catch {
      /* 忽略网络错误，本地清理即可 */
    }
    clearTokens();
    setUser(null);
    setPermissions([]);
    setDataScope("all");
    setMenus([]);
  };

  const hasPerm = (code: string) =>
    permissions.includes("*") || permissions.includes(code);

  return (
    <AuthContext.Provider
      value={{
        user,
        permissions,
        dataScope,
        menus,
        loading,
        hasPerm,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}

export type { ApiError };
