"""
MinerU Tianshu - Authentication Routes
认证路由

提供用户注册、登录、API Key 管理、SSO 等接口
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from typing import List
from datetime import datetime, timedelta
from loguru import logger

from .models import (
    User,
    RegisterRequest,
    UserCreate,
    UserRole,
    UserUpdate,
    UserLogin,
    PasswordChange,
    Token,
    APIKeyCreate,
    APIKeyResponse,
    Permission,
)
from .auth_db import AuthDB
from .jwt_handler import create_access_token, decode_token_payload, JWT_EXPIRE_MINUTES
from .dependencies import (
    get_auth_db,
    get_current_active_user,
    require_permission,
)
from .sso import get_sso_config, create_sso_provider, OIDC_AVAILABLE
from .system_config import SystemConfig
from storage.rustfs_client import get_rustfs_client

# 创建路由
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
async def register(user_data: RegisterRequest, auth_db: AuthDB = Depends(get_auth_db)):
    """
    用户注册

    创建新用户账户。角色恒为 'user'，需要管理员才能创建其他角色。
    """
    # 注册开关 fail-closed：配置缺失或读取失败一律拒绝注册
    try:
        allow_registration = SystemConfig().get_config("allow_registration")
    except Exception as e:
        logger.error(f"❌ Failed to read allow_registration config: {e}")
        allow_registration = None

    if allow_registration != "true":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled")

    # 邀请码校验：管理员配置后注册必须携带，比对用常量时间比较防止时序侧信道
    try:
        required_invite_code = (SystemConfig().get_config("registration_invite_code") or "").strip()
    except Exception as e:
        logger.error(f"❌ Failed to read registration_invite_code config: {e}")
        required_invite_code = ""

    if required_invite_code:
        import hmac

        provided = (user_data.invite_code or "").strip()
        if not provided or not hmac.compare_digest(provided, required_invite_code):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid invite code")

    try:
        # 公开注册入口不允许指定角色，固定为普通用户
        user = auth_db.create_user(
            UserCreate(
                username=user_data.username,
                email=user_data.email,
                password=user_data.password,
                full_name=user_data.full_name,
                role=UserRole.USER,
            )
        )
        logger.info(f"✅ User registered: {user.username} ({user.email})")
        return user
    except ValueError as e:
        # 不回显具体冲突字段，防止账号枚举
        logger.warning(f"⚠️ Registration failed for username '{user_data.username}': {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed, please try different credentials",
        )


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, auth_db: AuthDB = Depends(get_auth_db)):
    """
    用户登录

    使用用户名和密码登录，返回 JWT Access Token。
    """
    user = auth_db.authenticate_user(credentials.username, credentials.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled")

    # 生成 JWT Token（携带当前令牌代次，改密后旧令牌失效）
    access_token = create_access_token(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        expires_delta=timedelta(minutes=JWT_EXPIRE_MINUTES),
        epoch=auth_db.get_token_epoch(user.user_id),
    )

    logger.info(f"✅ User logged in: {user.username}")

    return Token(access_token=access_token, token_type="bearer", expires_in=JWT_EXPIRE_MINUTES * 60)


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    用户登出

    将当前 JWT 写入吊销表，Token 到期前无法再使用。API Key 认证用户无 JWT 可吊销，直接返回成功。
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer ") :]
        payload = decode_token_payload(token)
        if payload:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                auth_db.revoke_token(jti, current_user.user_id, datetime.utcfromtimestamp(exp))
                logger.info(f"✅ Token revoked on logout: {current_user.username} (jti: {jti[:8]}...)")

    return {"success": True}


@router.get("/me", response_model=User)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """
    获取当前登录用户信息

    需要认证。返回当前用户的详细信息。
    """
    return current_user


@router.patch("/me", response_model=User)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    更新当前用户信息

    用户可以更新自己的邮箱和全名，不能更新角色。
    """
    # 用户不能更改自己的角色
    if user_update.role is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot change your own role")

    update_data = user_update.model_dump(exclude_unset=True, exclude={"role", "is_active"})

    if not update_data:
        return current_user

    success = auth_db.update_user(current_user.user_id, **update_data)

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to update user")

    updated_user = auth_db.get_user_by_id(current_user.user_id)
    logger.info(f"✅ User updated: {updated_user.username}")
    return updated_user


@router.post("/me/change-password")
async def change_password(
    password_data: PasswordChange,
    current_user: User = Depends(get_current_active_user),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    修改当前用户密码

    用户需要提供旧密码和新密码。SSO 用户不能修改密码。
    """
    try:
        success = auth_db.change_password(
            current_user.user_id,
            password_data.old_password,
            password_data.new_password,
        )

        if success:
            logger.info(f"✅ Password changed: {current_user.username}")
            return {"success": True, "message": "Password changed successfully"}
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to change password")

    except ValueError as e:
        error_message = str(e)
        if "Incorrect old password" in error_message:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect old password")
        elif "SSO users" in error_message:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SSO users cannot change password")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_message)


# ==================== API Key 管理 ====================


@router.post("/apikeys", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: APIKeyCreate,
    current_user: User = Depends(require_permission(Permission.APIKEY_CREATE)),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    创建 API Key

    为当前用户创建一个新的 API Key。API Key 只会在创建时返回一次，请妥善保管。
    """
    key_info = auth_db.create_api_key(
        user_id=current_user.user_id,
        name=key_data.name,
        expires_days=key_data.expires_days,
        scopes=key_data.scopes,
    )

    logger.info(f"✅ API Key created: {key_info['prefix']}... for user {current_user.username}")

    return APIKeyResponse(
        key_id=key_info["key_id"],
        api_key=key_info["api_key"],
        prefix=key_info["prefix"],
        name=key_data.name,
        created_at=key_info["created_at"],
        expires_at=key_info["expires_at"],
    )


@router.get("/apikeys")
async def list_api_keys(
    current_user: User = Depends(require_permission(Permission.APIKEY_LIST_OWN)),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    列出当前用户的所有 API Key

    返回 API Key 列表，不包含完整的 key，只显示前缀。
    """
    keys = auth_db.list_api_keys(current_user.user_id)
    return {"success": True, "count": len(keys), "api_keys": keys}


@router.delete("/apikeys/{key_id}")
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(require_permission(Permission.APIKEY_DELETE)),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    删除 API Key

    删除指定的 API Key。只能删除自己的 API Key。
    """
    success = auth_db.delete_api_key(key_id, current_user.user_id)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")

    logger.info(f"✅ API Key deleted: {key_id} by user {current_user.username}")
    return {"success": True, "message": "API Key deleted successfully"}


# ==================== 用户管理 (需要管理员权限) ====================


@router.get("/users", response_model=List[User])
async def list_users(
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_permission(Permission.USER_LIST)),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    列出所有用户

    需要管理员权限。返回用户列表。
    """
    users = auth_db.list_users(limit=limit, offset=offset)
    return users


@router.post("/users", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_permission(Permission.USER_CREATE)),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    创建用户 (管理员)

    管理员可以创建任意角色的用户。
    """
    try:
        user = auth_db.create_user(user_data)
        logger.info(f"✅ User created by admin: {user.username} (role: {user.role.value})")
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/users/{user_id}", response_model=User)
async def update_user(
    user_id: str,
    user_update: UserUpdate,
    current_user: User = Depends(require_permission(Permission.USER_UPDATE)),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    更新用户信息 (管理员)

    管理员可以更新任意用户的信息，包括角色和状态。
    """
    update_data = user_update.model_dump(exclude_unset=True)

    if not update_data:
        user = auth_db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    success = auth_db.update_user(user_id, **update_data)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    updated_user = auth_db.get_user_by_id(user_id)
    logger.info(f"✅ User updated by admin: {updated_user.username}")
    return updated_user


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_permission(Permission.USER_DELETE)),
    auth_db: AuthDB = Depends(get_auth_db),
):
    """
    删除用户 (管理员)

    管理员可以删除用户。不能删除自己。
    """
    if user_id == current_user.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")

    success = auth_db.delete_user(user_id)

    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info(f"✅ User deleted by admin: {user_id}")
    return {"success": True, "message": "User deleted successfully"}


# ==================== SSO 集成 ====================


@router.get("/sso/enabled")
async def sso_status():
    """
    检查 SSO 是否启用

    返回 SSO 配置状态。
    """
    sso_config = get_sso_config()
    return {
        "enabled": sso_config is not None,
        "type": sso_config.get("type") if sso_config else None,
    }


if OIDC_AVAILABLE:
    # 只有在 authlib 可用时才注册 SSO 路由

    @router.get("/sso/login")
    async def sso_login(request: Request):
        """
        SSO 登录入口

        重定向到 SSO 提供者进行认证。
        """
        sso_config = get_sso_config()
        if not sso_config:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="SSO not configured")

        provider = create_sso_provider(sso_config["type"], sso_config)
        if not provider:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to initialize SSO")

        # 对于 OIDC,使用 authlib 的 OAuth 客户端
        if sso_config["type"] == "oidc":
            from authlib.integrations.starlette_client import OAuth

            oauth = OAuth()
            oauth.register(
                name="oidc",
                client_id=sso_config["client_id"],
                client_secret=sso_config["client_secret"],
                server_metadata_url=f"{sso_config['issuer_url']}/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )

            redirect_uri = sso_config["redirect_uri"]
            return await oauth.oidc.authorize_redirect(request, redirect_uri)

        # SAML 实现类似
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="SAML not implemented yet")

    @router.get("/sso/callback")
    async def sso_callback(request: Request, auth_db: AuthDB = Depends(get_auth_db)):
        """
        SSO 回调接口

        处理 SSO 提供者的回调，创建或获取用户，返回 JWT Token。
        """
        sso_config = get_sso_config()
        if not sso_config:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="SSO not configured")

        if sso_config["type"] == "oidc":
            from authlib.integrations.starlette_client import OAuth

            oauth = OAuth()
            oauth.register(
                name="oidc",
                client_id=sso_config["client_id"],
                client_secret=sso_config["client_secret"],
                server_metadata_url=f"{sso_config['issuer_url']}/.well-known/openid-configuration",
                client_kwargs={"scope": "openid email profile"},
            )

            # 获取 access token 和用户信息
            token = await oauth.oidc.authorize_access_token(request)
            user_info = token.get("userinfo")

            if not user_info:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get user info from SSO")

            # 获取或创建 SSO 用户
            sso_subject = user_info.get("sub")
            user = auth_db.get_or_create_sso_user(
                sso_subject=sso_subject,
                provider="oidc",
                user_info={
                    "email": user_info.get("email"),
                    "name": user_info.get("name"),
                    "preferred_username": user_info.get("preferred_username"),
                },
            )

            # 生成 JWT Token（携带当前令牌代次）
            access_token = create_access_token(
                user_id=user.user_id,
                username=user.username,
                role=user.role,
                expires_delta=timedelta(minutes=JWT_EXPIRE_MINUTES),
                epoch=auth_db.get_token_epoch(user.user_id),
            )

            logger.info(f"✅ SSO user logged in: {user.username} (provider: oidc)")

            # 重定向到前端，携带 token
            frontend_url = request.url_for("root").replace("/api/v1/auth/sso/callback", "")
            return RedirectResponse(url=f"{frontend_url}?token={access_token}")

        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="SAML not implemented yet")


# ==================== 系统配置管理 (管理员) ====================


@router.get("/system/config")
async def get_system_config():
    """
    获取系统配置

    公开接口，无需认证。返回系统名称、Logo、GitHub Star 显示、注册开关等配置。
    """
    config = SystemConfig()
    configs = config.get_all_configs()

    # 邀请码只暴露"是否需要"，绝不回传真实值；掩码供管理员页面回显
    invite_code_set = bool((configs.get("registration_invite_code") or "").strip())

    # 转换布尔值配置项
    return {
        "success": True,
        "config": {
            "system_name": configs.get("system_name", "MinerU Tianshu"),
            "system_logo": configs.get("system_logo", ""),
            "show_github_star": configs.get("show_github_star", "true") == "true",
            "allow_registration": configs.get("allow_registration", "true") == "true",
            "registration_invite_required": invite_code_set,
            "registration_invite_code": "********" if invite_code_set else "",
        },
    }


@router.post("/system/config")
async def update_system_config(
    config_data: dict,
    current_user: User = Depends(require_permission(Permission.SYSTEM_CONFIG)),
):
    """
    更新系统配置 (管理员)

    需要管理员权限。可以更新系统名称、Logo、GitHub Star 显示、注册开关等配置。

    请求体示例:
    {
        "system_name": "My Custom System",
        "system_logo": "https://example.com/logo.png",
        "show_github_star": false,
        "allow_registration": true
    }
    """
    config = SystemConfig()

    # 允许的配置键
    allowed_keys = {
        "system_name",
        "system_logo",
        "show_github_star",
        "allow_registration",
        "registration_invite_code",
        # 图片描述（多模态大模型）配置
        "image_caption_enabled",
        "image_caption_api_base",
        "image_caption_api_key",
        "image_caption_model",
        "image_caption_prompt",
        "image_caption_max_images",
        "image_caption_concurrency",
        "image_caption_timeout",
    }
    update_data = {}

    for key, value in config_data.items():
        if key in allowed_keys:
            # 掩码占位符表示前端未修改，跳过不更新
            if key in {"image_caption_api_key", "registration_invite_code"} and value == "********":
                continue
            # 转换布尔值配置项为字符串
            if key in {"show_github_star", "allow_registration", "image_caption_enabled"}:
                update_data[key] = "true" if value else "false"
            else:
                update_data[key] = str(value)

    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid configuration provided")

    success = config.update_configs(update_data)

    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update configuration")

    logger.info(f"✅ System config updated by {current_user.username}: {list(update_data.keys())}")

    # 返回更新后的配置
    updated_configs = config.get_all_configs()
    invite_code_set = bool((updated_configs.get("registration_invite_code") or "").strip())
    return {
        "success": True,
        "message": "Configuration updated successfully",
        "config": {
            "system_name": updated_configs.get("system_name", "MinerU Tianshu"),
            "system_logo": updated_configs.get("system_logo", ""),
            "show_github_star": updated_configs.get("show_github_star", "true") == "true",
            "allow_registration": updated_configs.get("allow_registration", "true") == "true",
            "registration_invite_required": invite_code_set,
            "registration_invite_code": "********" if invite_code_set else "",
        },
    }


# ==================== 图片描述（多模态大模型）配置 (管理员) ====================

# api_key 的掩码占位符：接口不返回真实密钥，前端未修改时原样发回
IMAGE_CAPTION_KEY_MASK = "********"


def _get_image_caption_configs() -> dict:
    """读取图片描述相关配置（含读取端默认值兜底，兼容存量部署）"""
    from image_caption.config import (
        DEFAULT_API_BASE,
        DEFAULT_CONCURRENCY,
        DEFAULT_MAX_IMAGES,
        DEFAULT_PROMPT,
        DEFAULT_TIMEOUT,
    )

    config = SystemConfig()
    raw = config.get_all_configs()

    def get(key: str, default: str) -> str:
        value = raw.get(key)
        return value if value is not None else default

    def get_int(key: str, default: int) -> int:
        try:
            return int(get(key, str(default)))
        except (ValueError, TypeError):
            return default

    return {
        "enabled": get("image_caption_enabled", "false") == "true",
        "api_base": get("image_caption_api_base", DEFAULT_API_BASE),
        "api_key": get("image_caption_api_key", ""),
        "model": get("image_caption_model", ""),
        "prompt": get("image_caption_prompt", DEFAULT_PROMPT),
        "max_images": get_int("image_caption_max_images", DEFAULT_MAX_IMAGES),
        "concurrency": get_int("image_caption_concurrency", DEFAULT_CONCURRENCY),
        "timeout": get_int("image_caption_timeout", DEFAULT_TIMEOUT),
    }


@router.get("/system/config/image-caption")
async def get_image_caption_config(
    current_user: User = Depends(require_permission(Permission.SYSTEM_CONFIG)),
):
    """
    获取图片描述（多模态大模型）配置 (管理员)

    api_key 属敏感信息，以掩码返回；公开接口 /system/config 不包含这些配置。
    """
    config = _get_image_caption_configs()
    config["api_key"] = IMAGE_CAPTION_KEY_MASK if config["api_key"] else ""
    return {"success": True, "config": config}


@router.post("/system/config/image-caption/test")
async def test_image_caption_connection(
    test_data: dict,
    current_user: User = Depends(require_permission(Permission.SYSTEM_CONFIG)),
):
    """
    测试多模态模型端点连通性 (管理员)

    请求体可携带表单中尚未保存的配置（api_base/api_key/model/timeout），
    api_key 为掩码占位符时回落到已保存的值。
    """
    import asyncio

    from image_caption.captioner import ImageCaptioner
    from image_caption.config import ImageCaptionConfig

    stored = _get_image_caption_configs()

    api_key = test_data.get("api_key", "")
    if api_key == IMAGE_CAPTION_KEY_MASK:
        api_key = stored["api_key"]

    config = ImageCaptionConfig(
        enabled=True,
        api_base=(test_data.get("api_base") or stored["api_base"]).strip(),
        api_key=api_key.strip(),
        model=(test_data.get("model") or stored["model"]).strip(),
        prompt=stored["prompt"],
        max_images=stored["max_images"],
        concurrency=stored["concurrency"],
        timeout=int(test_data.get("timeout") or stored["timeout"]),
    )
    if not config.api_base or not config.model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API Base 和模型名不能为空",
        )

    # 同步 SDK 调用放到线程中，避免阻塞事件循环
    success, message, latency_ms = await asyncio.to_thread(ImageCaptioner(config).test_connection)
    logger.info(f"🔍 Image caption connection test by {current_user.username}: {success} ({message})")
    return {"success": success, "message": message, "latency_ms": latency_ms}


@router.post("/system/logo/upload")
async def upload_system_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(Permission.SYSTEM_CONFIG)),
):
    """
    上传系统 Logo (管理员)

    需要管理员权限。上传 Logo 图片文件到 RustFS，支持 PNG、JPG、SVG 等格式。
    """
    import tempfile
    from pathlib import Path

    # 检查文件类型
    allowed_extensions = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}",
        )

    # 检查文件大小 (最大 5MB)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:  # 5MB
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds 5MB limit")

    try:
        # 创建临时文件保存上传的图片
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            tmp_file.write(content)
            tmp_file_path = tmp_file.name

        # 上传到 RustFS (使用 logos/ 前缀)
        rustfs = get_rustfs_client()
        logo_url = rustfs.upload_file(
            file_path=tmp_file_path,
            object_name=f"logos/logo{file_ext}",  # 固定名称，方便替换
        )

        # 清理临时文件
        Path(tmp_file_path).unlink()

        # 更新系统配置
        config = SystemConfig()
        config.set_config("system_logo", logo_url)

        logger.info(f"✅ Logo uploaded by {current_user.username}: {logo_url}")

        return {
            "success": True,
            "message": "Logo uploaded successfully",
            "logo_url": logo_url,
        }
    except Exception as e:
        logger.error(f"❌ Failed to upload logo: {e}")
        # 清理临时文件
        if "tmp_file_path" in locals() and Path(tmp_file_path).exists():
            Path(tmp_file_path).unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to upload logo: {str(e)}"
        )
