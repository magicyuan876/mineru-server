"""
MinerU Tianshu - System Configuration
系统配置管理

管理系统级别的配置项，如系统名称、Logo、GitHub Star 引导等
"""

import sqlite3
from contextlib import contextmanager
from typing import Optional, Dict
from pathlib import Path
from loguru import logger


class SystemConfig:
    """系统配置管理类"""

    def __init__(self, db_path: str = None):
        """
        初始化系统配置管理

        Args:
            db_path: 数据库文件路径 (复用主数据库)
        """
        import os

        if db_path is None:
            # 获取项目根目录
            project_root = Path(__file__).parent.parent.parent
            default_db = project_root / "data" / "db" / "mineru_tianshu.db"
            db_path = os.getenv("DATABASE_PATH", str(default_db))
            # 确保父目录存在
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            db_path = str(Path(db_path).resolve())
        else:
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
        """初始化系统配置表"""
        with self.get_cursor() as cursor:
            # 系统配置表 (Key-Value 存储)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_config (
                    config_key TEXT PRIMARY KEY,
                    config_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 初始化默认配置
            cursor.execute("SELECT COUNT(*) as count FROM system_config")
            config_count = cursor.fetchone()["count"]

            if config_count == 0:
                default_configs = {
                    "system_name": "MinerU Tianshu",
                    "system_logo": "",  # 空字符串表示使用默认 Logo
                    "show_github_star": "true",  # 字符串 "true" / "false"
                    "allow_registration": "true",  # 字符串 "true" / "false" - 是否允许用户注册
                }

                for key, value in default_configs.items():
                    cursor.execute(
                        "INSERT INTO system_config (config_key, config_value) VALUES (?, ?)",
                        (key, value),
                    )
                logger.info("✅ Initialized default system configuration")

    def get_config(self, key: str) -> Optional[str]:
        """
        获取配置项

        Args:
            key: 配置键名

        Returns:
            配置值，不存在返回 None
        """
        with self.get_cursor() as cursor:
            cursor.execute("SELECT config_value FROM system_config WHERE config_key = ?", (key,))
            row = cursor.fetchone()
            return row["config_value"] if row else None

    def get_all_configs(self) -> Dict[str, str]:
        """
        获取所有配置项

        Returns:
            配置字典
        """
        with self.get_cursor() as cursor:
            cursor.execute("SELECT config_key, config_value FROM system_config")
            return {row["config_key"]: row["config_value"] for row in cursor.fetchall()}

    def set_config(self, key: str, value: str) -> bool:
        """
        设置配置项 (INSERT OR REPLACE)

        Args:
            key: 配置键名
            value: 配置值

        Returns:
            是否设置成功
        """
        with self.get_cursor() as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO system_config (config_key, config_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
                (key, value),
            )
            return cursor.rowcount > 0

    def update_configs(self, configs: Dict[str, str]) -> bool:
        """
        批量更新配置项

        Args:
            configs: 配置字典

        Returns:
            是否更新成功
        """
        try:
            with self.get_cursor() as cursor:
                for key, value in configs.items():
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO system_config (config_key, config_value, updated_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                        (key, value),
                    )
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update configs: {e}")
            return False

    def delete_config(self, key: str) -> bool:
        """
        删除配置项

        Args:
            key: 配置键名

        Returns:
            是否删除成功
        """
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM system_config WHERE config_key = ?", (key,))
            return cursor.rowcount > 0
