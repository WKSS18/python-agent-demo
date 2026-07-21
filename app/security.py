"""密码与 JWT 安全工具。

密码使用 bcrypt 单向哈希；JWT 只保存用户 ID 和过期时间，不放密码、密钥等敏感
信息。令牌解析失败统一返回 ``None``，由鉴权依赖转换成稳定的 401 响应。
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings


settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """生成自带随机 salt 的 bcrypt 哈希。"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """使用哈希算法提供的安全校验，而不是比较明文。"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str) -> str:
    """签发带 UTC 过期时间的 HS256 Bearer Token。"""
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes,
    )
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """校验签名和过期时间，并提取 JWT subject。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        return str(subject) if subject is not None else None
    except JWTError:
        return None
