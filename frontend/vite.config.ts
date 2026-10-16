import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * 说明：PWA 的清单与 Service Worker 由 public/manifest.json + public/sw.js 静态提供，
 * 因此这里不再引入 vite-plugin-pwa（该依赖从未写入 package.json，会导致 vite build 直接失败）。
 * 若后续要改用插件生成 SW，请先 npm i -D vite-plugin-pwa 再恢复插件配置。
 */
export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          antd: ["antd", "@ant-design/icons"],
          charts: ["echarts", "echarts-for-react"],
          flow: ["@xyflow/react"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
