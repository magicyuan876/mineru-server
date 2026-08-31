"""
MinerU Tianshu - Authentication Database
认证数据库管理

管理用户、角色、API Key 的持久化存储
"""

import sqlite3
import hashlib
import secrets
import uuid
from contextlib import contextmanager
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from loguru import logger

from .models import User, UserCreate, UserRole


class AuthDB:
    """认证数据库管理类"""

    def __init__(self, db_path: str = None):
        """
        初始化认证数据库

        Args:
            db_path: 数据库文件路径 (复用主数据库)，默认从环境变量读取
        """
        # 导入所需模块
        import os
        from pathlib import Path

        # 优先使用传入的路径，其次使用环境变量，最后使用默认路径
        if db_path is None:
            # 获取项目根目录
            project_root = Path(__file__).parent.parent.parent
            default_db = project_root / "data" / "db" / "mineru_tianshu.db"
            db_path = os.getenv("DATABASE_PATH", str(default_db))
            # 确保父目录存在
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            # 确保使用绝对路径
            db_path = str(Path(db_path).resolve())
        else:
            # 确保使用绝对路径
            db_path = str(Path(db_path).resolve())
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        """获取数据库连接

        与 task_db 共用同一个数据库文件，PRAGMA 设置需保持一致（详见 task_db._get_conn）。
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def get_cursor(self):
        """上下文管理器,自动提交和错误处理"""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        """
        初始化认证相关数据表

        时区策略：
        - 数据库存储 UTC 时间（使用 datetime.utcnow()）
        - 前端显示本地时间（使用 dayjs.utc().local()）
        """
        with self.get_cursor() as cursor:
            # 用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    full_name TEXT,
                    role TEXT DEFAULT 'user',
                    is_active BOOLEAN DEFAULT 1,
                    is_sso BOOLEAN DEFAULT 0,
                    sso_provider TEXT,
                    sso_subject TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)

            # API Key 表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    api_key_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    prefix TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    last_used TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_username ON users(username)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_email ON users(email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sso_subject ON users(sso_subject)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_key_prefix ON api_keys(prefix)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_key_user ON api_keys(user_id)")

            # 修改 tasks 表，添加 user_id 字段 (如果不存在)
            try:
                cursor.execute("ALTER TABLE tasks ADD COLUMN user_id TEXT")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_user ON tasks(user_id)")
                logger.info("✅ Added user_id column to tasks table")
            except sqlite3.OperationalError:
                # 字段已存在，忽略
                pass

            # 创建默认管理员账户 (如果不存在)
            cursor.execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'")
            admin_count = cursor.fetchone()["count"]

            if admin_count == 0:
                admin_id = str(uuid.uuid4())
                admin_password = "admin123"  # 默认密码，生产环境应该修改
                password_hash = self._hash_password(admin_password)

                cursor.execute(
                    """
                    INSERT INTO users (user_id, username, email, password_hash, full_name, role)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (admin_id, "admin", "admin@example.com", password_hash, "System Administrator", "admin"),
                )
                logger.warning(f"🔐 Created default admin account: admin / {admin_password}")
                logger.warning("⚠️  Please change the default password immediately!")

    @staticmethod
    def _hash_password(password: str) -> str:
        """哈希密码"""
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return f"{salt}${pwd_hash.hex()}"

    @staticmethod
    def _verify_password(password: str, password_hash: str) -> bool:
        """验证密码"""
        try:
            salt, pwd_hash = password_hash.split("$")
            new_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
            return new_hash.hex() == pwd_hash
        except Exception:
            return False

    def create_user(self, user_data: UserCreate) -> User:
        """
        创建新用户

        Args:
            user_data: 用户创建数据

        Returns:
            User: 创建的用户对象

        Raises:
            ValueError: 用户名或邮箱已存在
        """
        user_id = str(uuid.uuid4())
        password_hash = self._hash_password(user_data.password)

        with self.get_cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO users (user_id, username, email, password_hash, full_name, role)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        user_id,
                        user_data.username,
                        user_data.email,
                        password_hash,
                        user_data.full_name,
                        user_data.role.value,
                    ),
                )
            except sqlite3.IntegrityError as e:
                if "username" in str(e):
                    raise ValueError(f"Username '{user_data.username}' already exists")
                elif "email" in str(e):
                    raise ValueError(f"Email '{user_data.email}' already exists")
                raise ValueError(f"Failed to create user: {e}")

        return self.get_user_by_id(user_id)

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """根据用户ID获取用户"""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_user(row)
            return None

    def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if row:
                return self._row_to_user(row)
            return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                return self._row_to_user(row)
            return None

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """
        验证用户名和密码

        Args:
            username: 用户名
            password: 密码

        Returns:
            User: 认证成功返回用户对象，失败返回 None
        """
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
            row = cursor.fetchone()

            if not row:
                return None

            password_hash = row["password_hash"]
            if not password_hash or not self._verify_password(password, password_hash):
                return None

            # 更新最后登录时间
            cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?", (row["user_id"],))

            return self._row_to_user(row)

    def list_users(self, limit: int = 100, offset: int = 0) -> List[User]:
        """列出所有用户"""
        with self.get_cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM users
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """,
                (limit, offset),
            )
            return [self._row_to_user(row) for row in cursor.fetchall()]

    def update_user(self, user_id: str, **kwargs) -> bool:
        """
        更新用户信息

        Args:
            user_id: 用户ID
            **kwargs: 要更新的字段

        Returns:
            bool: 更新是否成功
        """
        allowed_fields = {"email", "full_name", "role", "is_active"}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

        if not update_fields:
            return False

        set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
        values = list(update_fields.values())
        values.append(user_id)

        with self.get_cursor() as cursor:
            cursor.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
            return cursor.rowcount > 0

    def change_password(self, user_id: str, old_password: str, new_password: str) -> bool:
        """
        修改用户密码

        Args:
            user_id: 用户ID
            old_password: 旧密码
            new_password: 新密码

        Returns:
            bool: 修改是否成功

        Raises:
            ValueError: 旧密码错误或用户不存在
        """
        with self.get_cursor() as cursor:
            # 获取用户信息
            cursor.execute("SELECT password_hash, is_sso FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()

            if not row:
                raise ValueError("User not found")

            # SSO 用户不能修改密码
            if row["is_sso"]:
                raise ValueError("SSO users cannot change password")

            # 验证旧密码
            password_hash = row["password_hash"]
            if not password_hash or not self._verify_password(old_password, password_hash):
                raise ValueError("Incorrect old password")

            # 更新密码
            new_password_hash = self._hash_password(new_password)
            cursor.execute("UPDATE users SET password_hash = ? WHERE user_id = ?", (new_password_hash, user_id))

            return cursor.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0

    def create_api_key(self, user_id: str, name: str, expires_days: Optional[int] = None) -> Dict[str, str]:
        """
        创建 API Key

        Args:
            user_id: 用户ID
            name: API Key 名称
            expires_days: 过期天数 (None 表示永不过期)

        Returns:
            dict: 包含 key_id, api_key, prefix, created_at, expires_at
        """
        key_id = str(uuid.uuid4())
        # 生成 API Key: sk-<random_32_chars>
        api_key = f"sk-{secrets.token_urlsafe(32)}"
        prefix = api_key[:10]  # 前10个字符作为前缀

        # 哈希存储
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # 统一使用 UTC 时间
        created_at = datetime.utcnow()
        expires_at = None
        if expires_days:
            expires_at = created_at + timedelta(days=expires_days)

        with self.get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO api_keys (key_id, user_id, api_key_hash, name, prefix, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (key_id, user_id, api_key_hash, name, prefix, expires_at.isoformat() if expires_at else None),
            )

        return {
            "key_id": key_id,
            "api_key": api_key,
            "prefix": prefix,
            "created_at": created_at,
            "expires_at": expires_at,
        }

    def verify_api_key(self, api_key: str) -> Optional[User]:
        """
        验证 API Key 并返回关联用户

        Args:
            api_key: API Key

        Returns:
            User: 用户对象，验证失败返回 None
        """
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        prefix = api_key[:10]

        with self.get_cursor() as cursor:
            cursor.execute(
                """
                SELECT ak.*, u.* FROM api_keys ak
                JOIN users u ON ak.user_id = u.user_id
                WHERE ak.prefix = ? AND ak.api_key_hash = ? AND ak.is_active = 1 AND u.is_active = 1
                AND (ak.expires_at IS NULL OR ak.expires_at > datetime('now'))
            """,
                (prefix, api_key_hash),
            )

            row = cursor.fetchone()
            if not row:
                return None

            # 更新最后使用时间
            cursor.execute("UPDATE api_keys SET last_used = CURRENT_TIMESTAMP WHERE key_id = ?", (row["key_id"],))

            return self._row_to_user(row)

    def list_api_keys(self, user_id: str) -> List[Dict]:
        """列出用户的所有 API Key"""
        with self.get_cursor() as cursor:
            cursor.execute(
                """
                SELECT key_id, name, prefix, is_active, created_at, expires_at, last_used
                FROM api_keys
                WHERE user_id = ?
                ORDER BY created_at DESC
            """,
                (user_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def delete_api_key(self, key_id: str, user_id: str) -> bool:
        """删除 API Key"""
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM api_keys WHERE key_id = ? AND user_id = ?", (key_id, user_id))
            return cursor.rowcount > 0

    def get_or_create_sso_user(self, sso_subject: str, provider: str, user_info: Dict) -> User:
        """
        获取或创建 SSO 用户

        Args:
            sso_subject: SSO 用户唯一标识
            provider: SSO 提供者 (oidc/saml)
            user_info: SSO 返回的用户信息 (email, name, etc.)

        Returns:
            User: 用户对象
        """
        with self.get_cursor() as cursor:
            # 查找现有 SSO 用户
            cursor.execute(
                "SELECT * FROM users WHERE sso_subject = ? AND sso_provider = ?",
                (sso_subject, provider),
            )
            row = cursor.fetchone()

            if row:
                # 更新最后登录时间
                cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?", (row["user_id"],))
                return self._row_to_user(row)

            # 创建新 SSO 用户
            user_id = str(uuid.uuid4())
            email = user_info.get("email", f"{sso_subject}@sso.local")
            username = user_info.get("preferred_username", sso_subject)
            full_name = user_info.get("name", username)

            cursor.execute(
                """
                INSERT INTO users (
                    user_id, username, email, full_name, role,
                    is_sso, sso_provider, sso_subject, last_login
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, CURRENT_TIMESTAMP)
            """,
                (user_id, username, email, full_name, UserRole.USER.value, provider, sso_subject),
            )

            return self.get_user_by_id(user_id)

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        """将数据库行转换为 User 对象"""
        return User(
            user_id=row["user_id"],
            username=row["username"],
            email=row["email"],
            full_name=row["full_name"],
            role=UserRole(row["role"]),
            is_active=bool(row["is_active"]),
            is_sso=bool(row["is_sso"]),
            sso_provider=row["sso_provider"],
            sso_subject=row["sso_subject"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_login=datetime.fromisoformat(row["last_login"]) if row["last_login"] else None,
        )


if __name__ == "__main__":
    # 测试代码
    from pathlib import Path

    test_db = "test_auth.db"
    auth_db = AuthDB(test_db)

    # 测试创建用户
    from .models import UserCreate

    user_data = UserCreate(username="testuser", email="test@example.com", password="password123", role=UserRole.USER)

    user = auth_db.create_user(user_data)
    print(f"Created user: {user}")

    # 测试认证
    auth_user = auth_db.authenticate_user("testuser", "password123")
    print(f"Authenticated: {auth_user}")

    # 测试创建 API Key
    api_key_data = auth_db.create_api_key(user.user_id, "Test API Key", expires_days=30)
    print(f"Created API Key: {api_key_data}")

    # 测试验证 API Key
    verified_user = auth_db.verify_api_key(api_key_data["api_key"])
    print(f"Verified user from API Key: {verified_user}")

    # 清理
    Path(test_db).unlink(missing_ok=True)
    print("✅ Test completed!")
