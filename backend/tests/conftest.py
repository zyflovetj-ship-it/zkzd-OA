"""pytest 全局配置：把应用默认数据库指向临时文件。

原因：HTTP 路由层集成测试会经过 AuditMiddleware，它使用 app.core.db.SessionLocal
（默认 sqlite+aiosqlite:///./oa.db）写审计日志。若不隔离，测试执行会污染开发库。
注意必须在任何 `app.*` 导入之前生效（conftest 先于测试模块被 pytest 加载）。
"""
import os
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="zk-oa-pytest-")
os.environ.setdefault(
    "DATABASE_URL", f"sqlite+aiosqlite:///{_TMPDIR}/app_under_test.db"
)
