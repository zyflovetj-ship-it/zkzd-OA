"""集中配置：全部来自环境变量，启动时校验、生产环境快速失败。"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "zk-oa"
    environment: str = "development"  # development | production | test
    debug: bool = False

    # 生产必须改为 PostgreSQL；本地开发默认 SQLite（async）
    database_url: str = "sqlite+aiosqlite:///./oa.db"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    # 文件上传：本地开发存 uploads 目录，生产应改走对象存储（S3/OSS）并下发签名 URL
    upload_dir: str = "uploads"
    max_upload_size: int = 20 * 1024 * 1024  # 单文件上限 20MB

    # 对象存储后端：local = 本地磁盘（开发）；s3 = S3 兼容（生产，下发签名 URL）
    storage_backend: str = "local"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str | None = None
    signed_url_expire_minutes: int = 15

    # 后台调度：审批超时自动升级提醒（默认关闭，生产按需开启）
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 300
    workflow_sla_days: int = 3
    # 超时处理策略：notify=仅通知 admin/manager；escalate=通知并自动转交至兜底角色审批人
    workflow_timeout_action: str = "notify"
    workflow_timeout_fallback_role: str = "admin"

    # 轻量限流：每分钟每客户端 IP 允许的最大请求数（0 = 关闭）
    rate_limit_per_minute: int = 0

    # 实时 SSE：心跳间隔（秒），必须小于网关/代理空闲超时，避免长连接被误断
    sse_heartbeat_seconds: int = 25

    # 优雅停机：收到终止信号后，等待在途请求完成的最长时间（秒），超时则强制退出
    graceful_shutdown_timeout_seconds: int = 15

    @field_validator("environment")
    @classmethod
    def _check_env(cls, v: str) -> str:
        if v not in ("development", "production", "test"):
            raise ValueError("environment must be development|production|test")
        return v

    @field_validator("storage_backend")
    @classmethod
    def _check_storage_backend(cls, v: str) -> str:
        if v not in ("local", "s3"):
            raise ValueError("storage_backend must be local|s3")
        return v

    @field_validator("workflow_timeout_action")
    @classmethod
    def _check_timeout_action(cls, v: str) -> str:
        if v not in ("notify", "escalate"):
            raise ValueError("workflow_timeout_action must be notify|escalate")
        return v

    def model_post_init(self, __context) -> None:
        # 生产环境快速失败：禁止弱密钥与 SQLite
        if self.environment == "production":
            if self.jwt_secret == "change-me-in-production":
                raise ValueError("生产环境必须设置强随机 JWT_SECRET")
            if self.database_url.startswith("sqlite"):
                raise ValueError("生产环境必须使用 PostgreSQL")
        # s3 后端缺配置则启动即失败，避免运行时才暴露
        if self.storage_backend == "s3":
            missing = [
                name
                for name, val in (
                    ("AWS_ACCESS_KEY_ID", self.aws_access_key_id),
                    ("AWS_SECRET_ACCESS_KEY", self.aws_secret_access_key),
                    ("S3_BUCKET", self.s3_bucket),
                )
                if not val
            ]
            if missing:
                raise ValueError(f"storage_backend=s3 缺少必需配置：{','.join(missing)}")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
