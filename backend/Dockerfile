FROM python:3.12-slim

WORKDIR /app

# 安装 PostgreSQL 驱动与运行时依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 运行时注入环境变量（见 docker-compose.yml）
EXPOSE 8000

# 启动前先执行 Alembic 迁移（幂等：已是最新则自动跳过），再启动服务
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
