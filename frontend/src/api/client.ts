import axios, { AxiosError } from "axios";
import type { TokenResponse } from "../types";

const BASE = (import.meta.env.VITE_API_BASE as string) || "http://localhost:8000";

// 令牌仅存内存（不写 localStorage，降低 XSS 窃取风险）；生产建议刷新令牌改用 httpOnly Cookie。
let accessToken: string | null = null;
let refreshToken: string | null = null;
let refreshing: Promise<string> | null = null;

export function setTokens(access: string, refresh: string) {
  accessToken = access;
  refreshToken = refresh;
}
export function getAccessToken() {
  return accessToken;
}
export function getRefreshToken() {
  return refreshToken;
}
export function clearTokens() {
  accessToken = null;
  refreshToken = null;
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const api = axios.create({
  baseURL: BASE,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const orig = error.config as any;
    if (!orig) return Promise.reject(mapError(error));
    // 访问令牌过期：用刷新令牌换发新对，最多重试一次原请求
    if (error.response?.status === 401 && !orig._retry && refreshToken) {
      orig._retry = true;
      try {
        if (!refreshing) refreshing = doRefresh();
        const newAccess = await refreshing;
        refreshing = null;
        orig.headers.Authorization = `Bearer ${newAccess}`;
        return api(orig);
      } catch {
        refreshing = null;
        clearTokens();
        return Promise.reject(mapError(error));
      }
    }
    return Promise.reject(mapError(error));
  }
);

async function doRefresh(): Promise<string> {
  const res = await axios.post(`${BASE}/api/auth/refresh`, {
    refresh_token: refreshToken,
  });
  const data = res.data as TokenResponse;
  setTokens(data.access_token, data.refresh_token);
  return data.access_token;
}

function mapError(error: AxiosError): ApiError {
  // 网络层失败（无响应：断网 / 后端不可达 / 请求超时）：统一为可读的离线提示，
  // 避免把底层 "Network Error" 之类技术文案直接抛给用户。
  if (!error.response) {
    return new ApiError("网络连接不可用，请检查网络后重试", "network_error", 0);
  }
  const data = error.response?.data as any;
  const msg = data?.error?.message || error.message || "请求失败";
  const code = data?.error?.code || "unknown";
  const status = error.response?.status || 0;
  return new ApiError(msg, code, status);
}

export default api;
