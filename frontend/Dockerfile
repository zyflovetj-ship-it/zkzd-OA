# 生产前端：多阶段构建 —— Node 构建静态资源，Nginx 托管。
# 与开发态（`npm run dev` 热更新）分离：本地开发仍用 npm run dev，生产走本镜像。
FROM node:20-alpine AS build

WORKDIR /app

# VITE_API_BASE 在**构建期**内联进产物（Vite 的 import.meta.env 是编译期替换），
# 因此必须作为构建参数传入；运行期再改容器内环境变量是无效的。
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE

COPY package*.json ./
RUN npm ci
COPY . .
# npm run build = tsc --noEmit && vite build（类型校验不过则构建失败）
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
