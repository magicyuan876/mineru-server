"""
MinerU Tianshu - Authentication Dependencies
认证依赖注入

FastAPI 依赖项,用于保护路由和验证用户权限
"""

from fastapi import Depends, HTTPException, status, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from typing import Optional

from .auth_db import AuthDB
from .jwt_handler import verify_token
from .models import User, Permission, UserRole

# 初始化安全方案
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# 全局 AuthDB 实例
_auth_db: Optional[AuthDB] = None


def get_auth_db() -> AuthDB:
    """获取 AuthDB 实例 (单例模式)"""
    global _auth_db
    if _auth_db is None:
        _auth_db = AuthDB()
    return _auth_db


def _authenticate_jwt(token: str, auth_db: AuthDB) -> Optional[User]:
    """
    校验 JWT 并返回用户（验签 + 吊销检查 + 令牌代次检查）

    Args:
        token: JWT Token
        auth_db: 认证数据库实例

    Returns:
        User: 用户对象，任何一步校验失败返回 None
    """
    token_data = verify_token(token)
    if not token_data:
        return None

    # jti 在吊销表中说明该 Token 已被主动注销
    if token_data.jti and auth_db.is_token_revoked(token_data.jti):
        return None

    user = auth_db.get_user_by_id(token_data.user_id)
    if not user:
        return None

    # 改密后 token_epoch 递增，代次偏低的旧令牌一律作废
    if token_data.epoch < auth_db.get_token_epoch(user.user_id):
        return None

    return user


async def get_current_user_from_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    auth_db: AuthDB = Depends(get_auth_db),
) -> Optional[User]:
    """
    从 Bearer Token 获取当前用户

    Args:
        credentials: HTTP Bearer 认证凭证
        auth_db: 认证数据库实例

    Returns:
        User: 用户对象,未认证返回 None
    """
    if not credentials:
        return None

    return _authenticate_jwt(credentials.credentials, auth_db)


async def get_current_user_from_apikey(
    api_key: Optional[str] = Security(api_key_header),
    auth_db: AuthDB = Depends(get_auth_db),
) -> Optional[User]:
    """
    从 API Key 获取当前用户

    Args:
        api_key: API Key
        auth_db: 认证数据库实例

    Returns:
        User: 用户对象,未认证返回 None
    """
    if not api_key:
        return None

    user = auth_db.verify_api_key(api_key)
    return user


async def get_current_user(
    user_from_token: Optional[User] = Depends(get_current_user_from_token),
    user_from_apikey: Optional[User] = Depends(get_current_user_from_apikey),
) -> User:
    """
    获取当前用户 (支持 Bearer Token 或 API Key)

    优先级: Bearer Token > API Key

    Args:
        user_from_token: 从 Token 获取的用户
        user_from_apikey: 从 API Key 获取的用户

    Returns:
        User: 用户对象

    Raises:
        HTTPException: 未认证 (401)
    """
    user = user_from_token or user_from_apikey

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    获取当前激活的用户

    Args:
        current_user: 当前用户

    Returns:
        User: 激活的用户对象

    Raises:
        HTTPException: 用户未激活 (403)
    """
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return current_user


def require_permission(permission: Permission):
    """
    要求用户拥有特定权限的依赖项工厂

    Usage:
        @app.get("/admin")
        async def admin_route(user: User = Depends(require_permission(Permission.SYSTEM_CONFIG))):
            ...

    Args:
        permission: 所需权限

    Returns:
        Dependency: FastAPI 依赖项
    """

    async def permission_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if not current_user.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: {permission.value} required",
            )
        return current_user

    return permission_checker


def require_role(role: UserRole):
    """
    要求用户拥有特定角色或更高权限的依赖项工厂

    Usage:
        @app.get("/manager")
        async def manager_route(user: User = Depends(require_role(UserRole.MANAGER))):
            ...

    Args:
        role: 所需角色

    Returns:
        Dependency: FastAPI 依赖项
    """

    async def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if not current_user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role: {role.value} or higher required",
            )
        return current_user

    return role_checker


async def get_api_key_user(
    user_from_apikey: Optional[User] = Depends(get_current_user_from_apikey),
) -> User:
    """
    仅支持 API Key 认证的用户获取 (用于程序化访问)

    Args:
        user_from_apikey: 从 API Key 获取的用户

    Returns:
        User: 用户对象

    Raises:
        HTTPException: 未提供有效的 API Key (401)
    """
    if not user_from_apikey:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API Key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return user_from_apikey


# 可选认证依赖 (不强制要求登录)
async def get_optional_user(
    user_from_token: Optional[User] = Depends(get_current_user_from_token),
    user_from_apikey: Optional[User] = Depends(get_current_user_from_apikey),
) -> Optional[User]:
    """
    获取可选的当前用户 (未登录返回 None,不抛异常)

    用于既支持公开访问又支持登录用户的接口

    Args:
        user_from_token: 从 Token 获取的用户
        user_from_apikey: 从 API Key 获取的用户

    Returns:
        Optional[User]: 用户对象或 None
    """
    return user_from_token or user_from_apikey


async def get_current_user_flexible(
    request: Request,
    auth_db: AuthDB = Depends(get_auth_db),
) -> User:
    """
    灵活认证（供文件端点使用）：优先 Authorization 头，失败后尝试 ?token= 查询参数

    浏览器内嵌预览（<img>/<iframe>）无法携带请求头，因此文件端点允许
    通过查询参数传递 JWT。两种方式都会做验签 + 吊销 + 令牌代次 + 激活状态校验。

    Returns:
        User: 激活的用户对象

    Raises:
        HTTPException: 未认证 (401) 或用户未激活 (403)
    """
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer ") :]
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = _authenticate_jwt(token, auth_db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user
