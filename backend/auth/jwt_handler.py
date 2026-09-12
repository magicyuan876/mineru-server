"""
MinerU Tianshu - JWT Token Handler
JWT Token 处理器

负责 JWT Token 的生成和验证
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
import jwt
from loguru import logger

from .models import TokenData, UserRole

# JWT 配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
# 历史版本出厂默认值与文档占位符，命中即视为未配置（fail-closed）
_KNOWN_PLACEHOLDERS = {
    "your-secret-key-change-in-production",
    "your-super-secret-key-change-in-production-min-32-chars",
    "dev-secret-key-change-in-production",
    "cpu-dev-secret-key-change-in-production",
    "temp-secret-key",
    "CHANGE_THIS_TO_A_SECURE_RANDOM_STRING_IN_PRODUCTION",
}
if len(JWT_SECRET_KEY) < 32 or JWT_SECRET_KEY in _KNOWN_PLACEHOLDERS:
    raise RuntimeError("JWT_SECRET_KEY 未设置或过弱：请设置长度 ≥32 的随机字符串（openssl rand -hex 32）")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))  # 默认 1 小时


def create_access_token(
    user_id: str,
    username: str,
    role: UserRole,
    expires_delta: Optional[timedelta] = None,
    epoch: int = 0,
) -> str:
    """
    创建 JWT Access Token

    Args:
        user_id: 用户ID
        username: 用户名
        role: 用户角色
        expires_delta: 过期时间增量 (None 则使用默认值)
        epoch: 用户当前令牌代次（改密后递增，旧令牌失效）

    Returns:
        str: JWT Token
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)

    to_encode = {
        "sub": user_id,
        "username": username,
        "role": role.value,
        "exp": expire,
        "iat": datetime.utcnow(),
        "jti": uuid.uuid4().hex,
        "epoch": epoch,
    }

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_token_payload(token: str) -> Optional[dict]:
    """
    验签并解码 JWT，返回完整 payload（吊销时需要读取 jti/exp）

    Args:
        token: JWT Token

    Returns:
        dict: 完整 payload，验证失败返回 None
    """
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return None


def verify_token(token: str) -> Optional[TokenData]:
    """
    验证 JWT Token

    Args:
        token: JWT Token

    Returns:
        TokenData: Token 数据，验证失败返回 None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        role_str: str = payload.get("role")

        if user_id is None or username is None or role_str is None:
            return None

        return TokenData(
            user_id=user_id,
            username=username,
            role=UserRole(role_str),
            jti=payload.get("jti"),
            epoch=int(payload.get("epoch", 0)),
        )

    except jwt.ExpiredSignatureError:
        logger.debug("Token expired")
        return None
    except jwt.InvalidSignatureError:
        logger.debug("Invalid signature")
        return None
    except (jwt.DecodeError, jwt.InvalidTokenError) as e:
        logger.debug(f"JWT validation error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error validating token: {e}")
        return None
