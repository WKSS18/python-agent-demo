"""阿里云 OSS 适配器。

业务层只认识上传、签名、删除和归属校验，不直接操作 oss2 SDK。对象键内嵌用户 ID，
同时每次访问都检查前缀，防止用户提交别人的 object_key 造成水平越权。
"""

from datetime import UTC, datetime
import hashlib
import hmac
from pathlib import Path
import time
from urllib.parse import quote
from uuid import uuid4

import oss2
from fastapi import HTTPException, status

from app import schemas
from app.config import get_settings
from app.file_parser import validate_upload


class OssStorage:
    """封装 OSS 上传和签名，业务层不直接依赖厂商 SDK。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    def upload(
        self,
        owner_id: int,
        filename: str | None,
        media_type: str | None,
        content: bytes,
    ) -> schemas.UploadedFile:
        """把私有文件写入 OSS，并只返回短期可访问的签名 URL。"""
        upload = validate_upload(filename, media_type, content)
        date_path = datetime.now(UTC).strftime("%Y/%m/%d")
        object_key = (
            f"{self.settings.oss_object_prefix.strip('/')}/{owner_id}/"
            f"{date_path}/{uuid4().hex}{upload.suffix}"
        )
        if self._use_local_storage():
            path = self._local_path(object_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return schemas.UploadedFile(
                name=upload.name,
                media_type=upload.media_type,
                size=upload.size,
                object_key=object_key,
                url=self.sign_get_url(owner_id, object_key),
            )
        bucket = self._bucket()
        try:
            result = bucket.put_object(
                object_key,
                content,
                headers={"Content-Type": upload.media_type},
            )
        except (oss2.exceptions.OssError, oss2.exceptions.RequestError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="文件上传 OSS 失败，请检查 Bucket、Endpoint 和权限配置。",
            ) from exc
        if result.status not in {200, 201}:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="文件上传 OSS 失败。")

        return schemas.UploadedFile(
            name=upload.name,
            media_type=upload.media_type,
            size=upload.size,
            object_key=object_key,
            url=self.sign_get_url(owner_id, object_key),
        )

    def sign_get_url(self, owner_id: int, object_key: str) -> str:
        """校验对象归属后生成临时 GET 地址，数据库无需保存会过期的 URL。"""
        self.ensure_owned(owner_id, object_key)
        if self._use_local_storage():
            expires = int(time.time()) + self.settings.oss_signed_url_expire_seconds
            signature = self._local_signature(object_key, expires)
            encoded_key = quote(object_key, safe="/")
            return f"{self.settings.local_upload_url_prefix.rstrip('/')}/{encoded_key}?expires={expires}&signature={signature}"
        try:
            return self._bucket().sign_url(
                "GET",
                object_key,
                self.settings.oss_signed_url_expire_seconds,
                slash_safe=True,
            )
        except (oss2.exceptions.OssError, oss2.exceptions.RequestError) as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="生成文件预览地址失败。") from exc

    def delete(self, owner_id: int, object_key: str) -> None:
        """删除用户已上传但尚未发送的对象，避免 OSS 残留垃圾文件。"""
        self.ensure_owned(owner_id, object_key)
        if self._use_local_storage():
            self._local_path(object_key).unlink(missing_ok=True)
            return
        try:
            self._bucket().delete_object(object_key)
        except (oss2.exceptions.OssError, oss2.exceptions.RequestError) as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="删除 OSS 文件失败。") from exc

    def refresh_attachment_url(self, owner_id: int, attachment: dict | None) -> dict | None:
        """读取历史消息时重新签名，使刷新页面后私有附件仍可展示。"""
        if not isinstance(attachment, dict):
            return None
        result = dict(attachment)
        object_key = result.get("object_key")
        if isinstance(object_key, str) and object_key:
            result["url"] = self.sign_get_url(owner_id, object_key)
        return result

    def ensure_owned(self, owner_id: int, object_key: str) -> None:
        """以用户目录前缀校验对象归属，阻断跨账户读取和删除。"""
        expected_prefix = f"{self.settings.oss_object_prefix.strip('/')}/{owner_id}/"
        if not object_key.startswith(expected_prefix):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该附件。")

    def _bucket(self) -> oss2.Bucket:
        """延迟创建 Bucket 客户端，让不使用上传功能的接口不依赖 OSS 配置。"""
        if not all(
            (
                self.settings.oss_access_key_id,
                self.settings.oss_access_key_secret,
                self.settings.oss_endpoint,
                self.settings.oss_bucket,
            ),
        ):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OSS 尚未配置。")
        auth = oss2.Auth(self.settings.oss_access_key_id, self.settings.oss_access_key_secret)
        return oss2.Bucket(auth, self.settings.oss_endpoint, self.settings.oss_bucket)

    def read_local_signed(self, object_key: str, expires: int, signature: str) -> tuple[bytes, str]:
        """Validate an expiring HMAC URL and read an opaque local attachment."""
        if not self._use_local_storage():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在。")
        if expires < int(time.time()) or not hmac.compare_digest(signature, self._local_signature(object_key, expires)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="附件链接无效或已过期。")
        path = self._local_path(object_key)
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在。")
        media_types = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".pdf": "application/pdf", ".txt": "text/plain",
            ".md": "text/markdown", ".csv": "text/csv",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        return path.read_bytes(), media_types.get(path.suffix.lower(), "application/octet-stream")

    def _use_local_storage(self) -> bool:
        backend = self.settings.attachment_storage_backend.lower()
        if backend == "local":
            return True
        if backend == "oss":
            return False
        return not all((self.settings.oss_access_key_id, self.settings.oss_access_key_secret,
                        self.settings.oss_endpoint, self.settings.oss_bucket))

    def _local_path(self, object_key: str) -> Path:
        root = Path(self.settings.local_upload_dir).resolve()
        path = (root / object_key).resolve()
        if root not in path.parents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="附件路径无效。")
        return path

    def _local_signature(self, object_key: str, expires: int) -> str:
        return hmac.new(
            self.settings.secret_key.encode(), f"{object_key}:{expires}".encode(), hashlib.sha256,
        ).hexdigest()
