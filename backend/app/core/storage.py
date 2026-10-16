"""对象存储抽象：local（本地磁盘，开发）与 s3（S3 兼容，生产下发签名 URL）。

设计要点：
- 控制器只关心「本地流式返回」还是「跳转到签名 URL(302)」，不感知底层后端。
- file_url 始终是逻辑地址 /api/documents/{id}/file，前端无需改动。
- key 统一采用 {doc_id}.{ext}（与旧版磁盘命名一致），扩展名在上传入口受白名单约束。
- aioboto3 仅在使用 s3 后端时惰性导入，本地开发无需安装。
"""
from __future__ import annotations

import inspect
import os
from abc import ABC, abstractmethod
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationError


class StorageBackend(ABC):
    """统一存储接口。"""

    @abstractmethod
    async def save(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """写入对象；失败抛 ValidationError。"""

    @abstractmethod
    async def get_download(self, key: str, download_name: str) -> tuple[str | None, str | None]:
        """返回 (本地磁盘路径, 签名URL)；本地模式前者非空、S3 模式后者非空。"""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除对象；best-effort，失败抛原异常交由上层告警。"""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """对象是否存在。"""


class LocalStorageBackend(StorageBackend):
    """本地磁盘后端：开发环境使用，下载时由鉴权端点直接流式返回。"""

    def __init__(self, settings: Settings) -> None:
        self.upload_dir = settings.upload_dir
        os.makedirs(self.upload_dir, exist_ok=True)

    async def save(self, key: str, data: bytes, content_type: str | None = None) -> None:
        # key 来自受约束的 {id}.{ext}，不应含路径分隔符；做基础校验防穿越
        if os.path.dirname(key):
            raise ValidationError("非法存储键")
        disk_path = os.path.join(self.upload_dir, key)
        try:
            with open(disk_path, "wb") as f:
                f.write(data)
        except OSError as exc:
            raise ValidationError(f"文件写入失败：{exc}")

    async def get_download(self, key: str, download_name: str) -> tuple[str | None, str | None]:
        disk_path = os.path.join(self.upload_dir, key)
        if not os.path.isfile(disk_path):
            raise NotFoundError("文件已不存在，可能已被清理")
        return disk_path, None

    async def delete(self, key: str) -> None:
        disk_path = os.path.join(self.upload_dir, key)
        if os.path.isfile(disk_path):
            os.remove(disk_path)

    async def exists(self, key: str) -> bool:
        return os.path.isfile(os.path.join(self.upload_dir, key))


class S3StorageBackend(StorageBackend):
    """S3 兼容后端（AWS S3 / 阿里云 OSS / MinIO 等）：下载下发签名 URL 重定向。"""

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.endpoint_url = settings.s3_endpoint_url
        self.access_key = settings.aws_access_key_id
        self.secret_key = settings.aws_secret_access_key
        self.expire = settings.signed_url_expire_minutes * 60

    def _session(self):
        import aioboto3

        return aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

    async def save(self, key: str, data: bytes, content_type: str | None = None) -> None:
        session = self._session()
        kwargs: dict = {"Bucket": self.bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        try:
            async with session.client("s3", endpoint_url=self.endpoint_url) as client:
                await client.put_object(**kwargs)
        except Exception as exc:
            raise ValidationError(f"文件上传到对象存储失败：{exc}")

    async def get_download(self, key: str, download_name: str) -> tuple[str | None, str | None]:
        from urllib.parse import quote

        session = self._session()
        disposition = f"attachment; filename*=UTF-8''{quote(download_name)}"
        try:
            async with session.client("s3", endpoint_url=self.endpoint_url) as client:
                # generate_presigned_url 不发起网络请求，属同步方法；兼容个别版本返回可等待对象
                url = client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": self.bucket,
                        "Key": key,
                        "ResponseContentDisposition": disposition,
                    },
                    ExpiresIn=self.expire,
                )
                if inspect.isawaitable(url):
                    url = await url
        except Exception as exc:
            raise NotFoundError(f"生成签名 URL 失败：{exc}")
        return None, url

    async def delete(self, key: str) -> None:
        session = self._session()
        async with session.client("s3", endpoint_url=self.endpoint_url) as client:
            await client.delete_object(Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        session = self._session()
        async with session.client("s3", endpoint_url=self.endpoint_url) as client:
            try:
                await client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False


@lru_cache
def get_storage() -> StorageBackend:
    """按环境变量选择存储后端（首次调用缓存）。"""
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3StorageBackend(settings)
    return LocalStorageBackend(settings)
