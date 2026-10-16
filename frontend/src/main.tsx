import React from "react";
import ReactDOM from "react-dom/client";
import { App as AntdApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import ErrorBoundary from "./components/ErrorBoundary";
import type { ApiError } from "./api/client";
import { antdTheme } from "./theme";
import "antd/dist/reset.css";
import "./styles/global.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 4xx 是客户端错误，重试无意义（权限不足/参数错误不会因为重试而成功）；
      // 5xx 与网络错误最多重试 3 次，容忍后端瞬时抖动。
      retry: (failureCount, error) => {
        const status = (error as ApiError)?.status ?? 0;
        if (status >= 400 && status < 500) return false;
        return failureCount < 3;
      },
      refetchOnWindowFocus: false,
    },
    mutations: { retry: 0 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={antdTheme}>
      <AntdApp>
        <ErrorBoundary>
          <QueryClientProvider client={queryClient}>
            <BrowserRouter>
              <AuthProvider>
                <App />
              </AuthProvider>
            </BrowserRouter>
          </QueryClientProvider>
        </ErrorBoundary>
      </AntdApp>
    </ConfigProvider>
  </React.StrictMode>
);
