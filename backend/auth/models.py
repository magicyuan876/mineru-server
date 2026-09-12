"""
MinerU Tianshu - Authentication Models
认证数据模型

定义用户、角色、权限、API Key 等核心数据结构
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    """用户角色枚举"""

    ADMIN = "admin"  # 系统管理员：完全控制权限
    MANAGER = "manager"  # 管理者：可管理用户和查看所有任务
    USER = "user"  # 普通用户：可提交任务和查看自己的任务


class Permission(str, Enum):
    """权限枚举 (细粒度控制)"""

    # 任务相关
    TASK_SUBMIT = "task:submit"  # 提交任务
    TASK_VIEW_OWN = "task:view:own"  # 查看自己的任务
    TASK_VIEW_ALL = "task:view:all"  # 查看所有任务
    TASK_DELETE_OWN = "task:delete:own"  # 删除自己的任务
    TASK_DELETE_ALL = "task:delete:all"  # 删除任何任务

    # 队列管理
    QUEUE_VIEW = "queue:view"  # 查看队列统计
    QUEUE_MANAGE = "queue:manage"  # 管理队列（清理、重置等）

    # 用户管理
    USER_CREATE = "user:create"  # 创建用户
    USER_UPDATE = "user:update"  # 更新用户
    USER_DELETE = "user:delete"  # 删除用户
    USER_LIST = "user:list"  # 列出用户

    # API Key 管理
    APIKEY_CREATE = "apikey:create"  # 创建 API Key
    APIKEY_DELETE = "apikey:delete"  # 删除 API Key
    APIKEY_LIST_OWN = "apikey:list:own"  # 查看自己的 API Key
    APIKEY_LIST_ALL = "apikey:list:all"  # 查看所有 API Key

    # 系统管理
    SYSTEM_CONFIG = "system:config"  # 系统配置
    SYSTEM_STATS = "system:stats"  # 系统统计


# 角色权限映射
ROLE_PERMISSIONS = {
    UserRole.ADMIN: [p for p in Permission],  # 管理员拥有所有权限
    UserRole.MANAGER: [
        Permission.TASK_SUBMIT,
        Permission.TASK_VIEW_ALL,
        Permission.TASK_DELETE_OWN,
        Permission.QUEUE_VIEW,
        Permission.USER_LIST,
        Permission.APIKEY_CREATE,
        Permission.APIKEY_DELETE,
        Permission.APIKEY_LIST_OWN,
        Permission.SYSTEM_STATS,
    ],
    UserRole.USER: [
        Permission.TASK_SUBMIT,
        Permission.TASK_VIEW_OWN,
        Permission.TASK_DELETE_OWN,
        Permission.QUEUE_VIEW,
        Permission.APIKEY_CREATE,
        Permission.APIKEY_LIST_OWN,
    ],
}


class User(BaseModel):
    """用户模型"""

    user_id: str
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    is_sso: bool = False  # 是否通过 SSO 登录
    sso_provider: Optional[str] = None  # SSO 提供者 (oidc/saml)
    sso_subject: Optional[str] = None  # SSO 用户唯一标识
    created_at: datetime
    last_login: Optional[datetime] = None
    api_key_scopes: Optional[List[str]] = None  # API Key 作用域，None 表示不限

    def has_permission(self, permission: Permission) -> bool:
        """检查用户是否拥有指定权限"""
        if permission not in ROLE_PERMISSIONS.get(self.role, []):
            return False
        # API Key 携带作用域时，还需落在作用域白名单内
        if self.api_key_scopes is not None:
            return permission.value in self.api_key_scopes
        return True

    def has_role(self, role: UserRole) -> bool:
        """检查用户是否拥有指定角色或更高权限"""
        role_hierarchy = [UserRole.USER, UserRole.MANAGER, UserRole.ADMIN]
        user_level = role_hierarchy.index(self.role)
        required_level = role_hierarchy.index(role)
        return user_level >= required_level


class RegisterRequest(BaseModel):
    """注册请求（公开注册入口，不允许指定角色，角色恒为普通用户）"""

    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    full_name: Optional[str] = Field(None, max_length=100)


class UserCreate(BaseModel):
    """创建用户请求"""

    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    full_name: Optional[str] = Field(None, max_length=100)
    role: UserRole = UserRole.USER


class UserUpdate(BaseModel):
    """更新用户请求"""

    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserLogin(BaseModel):
    """用户登录请求"""

    username: str
    password: str


class PasswordChange(BaseModel):
    """修改密码请求"""

    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)


class Token(BaseModel):
    """JWT Token 响应"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒


class TokenData(BaseModel):
    """JWT Token 数据"""

    user_id: str
    username: str
    role: UserRole
    jti: Optional[str] = None  # Token 唯一标识，用于吊销
    epoch: int = 0  # 签发时的令牌代次，改密后旧令牌失效


class APIKey(BaseModel):
    """API Key 模型"""

    key_id: str
    user_id: str
    api_key: str  # 哈希后的 key
    name: str  # API Key 名称/描述
    prefix: str  # Key 前缀 (用于识别,如 "sk-abc...")
    is_active: bool = True
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None


class APIKeyCreate(BaseModel):
    """创建 API Key 请求"""

    name: str = Field(..., min_length=1, max_length=100)
    expires_days: int = Field(90, gt=0, le=3650)  # 默认 90 天，最长 10 年，必须限期
    scopes: Optional[List[str]] = None  # 权限作用域（Permission 枚举值），None 表示不限

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        valid = {p.value for p in Permission}
        invalid = [s for s in v if s not in valid]
        if invalid:
            raise ValueError(f"Invalid scopes: {invalid}")
        return v


class APIKeyResponse(BaseModel):
    """API Key 创建响应 (只返回一次完整 key)"""

    key_id: str
    api_key: str  # 完整的 key (只返回一次)
    prefix: str
    name: str
    created_at: datetime
    expires_at: Optional[datetime] = None


class SSOConfig(BaseModel):
    """SSO 配置"""

    enabled: bool = False
    provider_type: str  # oidc / saml
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    issuer_url: Optional[str] = None
    redirect_uri: Optional[str] = None
    # SAML 特定配置
    saml_metadata_url: Optional[str] = None
    saml_entity_id: Optional[str] = None
