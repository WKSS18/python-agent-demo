from datetime import UTC, datetime
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
        upload = validate_upload(filename, media_type, content)
        bucket = self._bucket()
        date_path = datetime.now(UTC).strftime("%Y/%m/%d")
        object_key = (
            f"{self.settings.oss_object_prefix.strip('/')}/{owner_id}/"
            f"{date_path}/{uuid4().hex}{upload.suffix}"
        )
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
        self.ensure_owned(owner_id, object_key)
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
        try:
            self._bucket().delete_object(object_key)
        except (oss2.exceptions.OssError, oss2.exceptions.RequestError) as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="删除 OSS 文件失败。") from exc

    def refresh_attachment_url(self, owner_id: int, attachment: dict | None) -> dict | None:
        if not isinstance(attachment, dict):
            return None
        result = dict(attachment)
        object_key = result.get("object_key")
        if isinstance(object_key, str) and object_key:
            result["url"] = self.sign_get_url(owner_id, object_key)
        return result

    def ensure_owned(self, owner_id: int, object_key: str) -> None:
        expected_prefix = f"{self.settings.oss_object_prefix.strip('/')}/{owner_id}/"
        if not object_key.startswith(expected_prefix):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该附件。")

    def _bucket(self) -> oss2.Bucket:
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
