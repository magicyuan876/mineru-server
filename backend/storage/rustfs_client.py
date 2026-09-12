"""
RustFS 对象存储客户端

基于 S3 兼容 API 实现，支持图片批量上传和 URL 生成
RustFS: https://github.com/rustfs/rustfs
"""

import os
import secrets
import string
import time
from pathlib import Path
from typing import Dict, Optional, List
from loguru import logger
from minio import Minio
from minio.error import S3Error
from datetime import datetime


class RustFSClient:
    """
    RustFS 对象存储客户端

    特性：
    - S3 兼容 API (复用 minio-py)
    - 自动创建 Bucket
    - 批量上传图片
    - 生成可访问的公开 URL
    - 自动检测主机 IP（避免使用 localhost）
    - 短且唯一的文件名生成（时间 + NanoID）
    """

    @staticmethod
    def _generate_nanoid(size: int = 4) -> str:
        """
        生成 NanoID（URL安全的随机字符串）

        Args:
            size: 字符串长度

        Returns:
            随机字符串（包含大小写字母、数字、-_）
        """
        alphabet = string.ascii_letters + string.digits + "-_"
        return "".join(secrets.choice(alphabet) for _ in range(size))

    @staticmethod
    def _base62_encode(num: int) -> str:
        """
        Base62 编码（使用 0-9a-zA-Z）

        Args:
            num: 要编码的整数

        Returns:
            Base62 编码的字符串
        """
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if num == 0:
            return alphabet[0]
        result = []
        while num:
            num, rem = divmod(num, 62)
            result.append(alphabet[rem])
        return "".join(reversed(result))

    @staticmethod
    def _generate_short_filename(extension: str) -> str:
        """
        生成短且唯一的文件名: msec_nanoid.ext

        格式说明:
        - msec: 毫秒时间戳后5位（Base62编码，5字符）
        - nanoid: 随机字符串（4字符，64^4 ≈ 1600万种可能）
        - 总长度: 约11字符（不含扩展名）

        并发安全性:
        - 毫秒级时间精度，多 Worker 很难在同一毫秒上传
        - 即使同一毫秒，还有 1600万种随机可能
        - 10个Worker同时每毫秒上传100张，碰撞概率 < 0.003%

        Args:
            extension: 文件扩展名（如 .jpg）

        Returns:
            短文件名（如: a3f2K_V1St.jpg）
        """
        # 获取毫秒时间戳
        timestamp_ms = int(time.time() * 1000)

        # Base62 编码并取后5位（足够表示时间差异）
        timestamp_encoded = RustFSClient._base62_encode(timestamp_ms)
        timestamp_part = timestamp_encoded[-5:]  # 取后5位

        # 生成随机后缀
        nano_part = RustFSClient._generate_nanoid(4)  # 4字符

        return f"{timestamp_part}_{nano_part}{extension}"

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        secure: bool = False,
        public_url: Optional[str] = None,
    ):
        """
        初始化 RustFS 客户端

        Args:
            endpoint: RustFS 服务地址 (例如: rustfs:9000)
            access_key: 访问密钥
            secret_key: 密钥
            bucket_name: 存储桶名称
            secure: 是否使用 HTTPS
            public_url: 公开访问 URL (必须设置，例如: http://192.168.1.100:9000)
        """
        # 从环境变量读取配置（不再提供 rustfsadmin 默认凭据兜底）
        self.endpoint = endpoint or os.getenv("RUSTFS_ENDPOINT", "rustfs:9000")
        self.access_key = access_key or os.getenv("RUSTFS_ACCESS_KEY", "")
        self.secret_key = secret_key or os.getenv("RUSTFS_SECRET_KEY", "")
        self.bucket_name = bucket_name or os.getenv("RUSTFS_BUCKET", "ts-img")
        self.secure = secure or os.getenv("RUSTFS_SECURE", "false").lower() == "true"

        # 启用 RustFS 时凭据必须显式配置；未启用时不强制（仅 logo 上传等路径会触达本类）
        rustfs_enabled = os.getenv("RUSTFS_ENABLED", "true").lower() in ("true", "1", "yes")
        if rustfs_enabled and (not self.access_key or not self.secret_key):
            raise RuntimeError(
                "RustFS credentials missing: RUSTFS_ACCESS_KEY / RUSTFS_SECRET_KEY must be set "
                "when RUSTFS_ENABLED=true (no default credentials are allowed)."
            )

        # 公开 URL 配置：必须通过 RUSTFS_PUBLIC_URL 环境变量设置
        self.public_url = public_url or os.getenv("RUSTFS_PUBLIC_URL", "").strip()

        if not self.public_url:
            logger.error("❌ RUSTFS_PUBLIC_URL not configured!")
            logger.error("   Please set RUSTFS_PUBLIC_URL in .env file")
            logger.error("")
            logger.error("   Example:")
            logger.error("   RUSTFS_PUBLIC_URL=http://192.168.1.100:9000")
            logger.error("")
            logger.error("   For Windows/WSL users:")
            logger.error("   1. Run 'ipconfig' in Windows to get your IP")
            logger.error("   2. Set RUSTFS_PUBLIC_URL=http://YOUR_WINDOWS_IP:9000")
            raise ValueError("RUSTFS_PUBLIC_URL not configured. " "Please set RUSTFS_PUBLIC_URL in .env file.")

        # 移除末尾的斜杠
        self.public_url = self.public_url.rstrip("/")
        logger.info(f"🌐 RustFS Public URL: {self.public_url}")

        # 验证配置
        if not all([self.endpoint, self.access_key, self.secret_key, self.bucket_name]):
            raise ValueError(
                "RustFS configuration incomplete. Please set: "
                "RUSTFS_ENDPOINT, RUSTFS_ACCESS_KEY, RUSTFS_SECRET_KEY, RUSTFS_BUCKET"
            )

        # 初始化 MinIO 客户端 (S3 兼容)
        try:
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
            logger.info(f"🚀 RustFS client initialized: {self.endpoint}")
            logger.info(f"   Bucket: {self.bucket_name}")
            logger.info(f"   Public URL: {self.public_url}")

            # 确保 Bucket 存在
            self._ensure_bucket()

        except Exception as e:
            logger.error(f"❌ Failed to initialize RustFS client: {e}")
            raise

    def _ensure_bucket(self):
        """确保 Bucket 存在，不存在则创建"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"✅ Created bucket: {self.bucket_name}")

                # 设置为公开读取（可选，根据需求调整）
                # 注意：RustFS 的策略 API 可能与 MinIO 略有不同
                try:
                    policy = {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"AWS": ["*"]},
                                "Action": ["s3:GetObject"],
                                "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"],
                            }
                        ],
                    }
                    import json

                    self.client.set_bucket_policy(self.bucket_name, json.dumps(policy))
                    logger.info("✅ Set bucket policy: public read")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to set bucket policy (may need manual configuration): {e}")
            else:
                logger.debug(f"✅ Bucket exists: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"❌ Failed to ensure bucket: {e}")
            raise

    def upload_file(
        self,
        file_path: str,
        object_name: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """
        上传单个文件到 RustFS

        Args:
            file_path: 本地文件路径
            object_name: 对象名称 (不指定则自动生成: YYYYMMDD/msec_nano.ext)
            content_type: MIME 类型 (不指定则自动检测)

        Returns:
            可访问的公开 URL

        Example:
            生成的路径: 20241205/a3f2K_V1St.jpg (约24字符)

        Note:
            使用毫秒时间戳+NanoID，多Worker并发安全
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # 生成对象名称: YYYYMMDD/msec_nano.ext
        if object_name is None:
            file_extension = file_path.suffix
            date_prefix = datetime.now().strftime("%Y%m%d")
            short_filename = self._generate_short_filename(file_extension)
            object_name = f"{date_prefix}/{short_filename}"

        # 自动检测 Content-Type
        if content_type is None:
            content_type = self._get_content_type(file_path)

        try:
            # 上传文件
            self.client.fput_object(
                self.bucket_name,
                object_name,
                str(file_path),
                content_type=content_type,
            )

            # 生成公开 URL
            url = f"{self.public_url}/{self.bucket_name}/{object_name}"

            logger.debug(f"✅ Uploaded: {file_path.name} -> {object_name}")
            return url

        except S3Error as e:
            logger.error(f"❌ Failed to upload {file_path.name}: {e}")
            raise

    def upload_directory(
        self,
        dir_path: str,
        prefix: Optional[str] = None,
        extensions: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        批量上传目录中的文件

        Args:
            dir_path: 目录路径
            prefix: 对象名称前缀 (例如: "custom_prefix"，不指定则使用日期前缀 YYYYMMDD)
            extensions: 允许的文件扩展名列表 (例如: [".jpg", ".png"])

        Returns:
            {本地文件名: 公开 URL} 的映射字典

        Note:
            使用毫秒时间戳+NanoID方案，多Worker并发安全
            - 毫秒级时间精度 + 1600万种随机可能
            - 10个Worker同时每毫秒上传100张，碰撞概率 < 0.003%
        """
        dir_path = Path(dir_path)

        if not dir_path.exists() or not dir_path.is_dir():
            raise ValueError(f"Invalid directory: {dir_path}")

        # 默认只上传图片文件
        if extensions is None:
            extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"]

        # 查找所有符合条件的文件
        files = [f for f in dir_path.iterdir() if f.is_file() and f.suffix.lower() in extensions]

        if not files:
            logger.warning(f"⚠️  No files found in {dir_path}")
            return {}

        logger.info(f"📤 Uploading {len(files)} files from {dir_path.name}/")

        url_mapping = {}

        for file_path in files:
            try:
                # 生成对象名称: YYYYMMDD/msec_nano.ext
                file_extension = file_path.suffix
                date_prefix = datetime.now().strftime("%Y%m%d")
                short_filename = self._generate_short_filename(file_extension)

                if prefix:
                    object_name = f"{prefix}/{short_filename}"
                else:
                    object_name = f"{date_prefix}/{short_filename}"

                # 上传文件
                url = self.upload_file(file_path, object_name)

                # 记录映射 (原始文件名 -> URL)
                url_mapping[file_path.name] = url

            except Exception as e:
                logger.error(f"❌ Failed to upload {file_path.name}: {e}")
                # 继续上传其他文件
                continue

        logger.info(f"✅ Successfully uploaded {len(url_mapping)}/{len(files)} files")
        return url_mapping

    def _get_content_type(self, file_path: Path) -> str:
        """根据文件扩展名返回 MIME 类型"""
        extension = file_path.suffix.lower()

        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }

        return content_types.get(extension, "application/octet-stream")

    def delete_file(self, object_name: str) -> bool:
        """
        删除对象

        Args:
            object_name: 对象名称

        Returns:
            是否成功
        """
        try:
            self.client.remove_object(self.bucket_name, object_name)
            logger.debug(f"✅ Deleted: {object_name}")
            return True
        except S3Error as e:
            logger.error(f"❌ Failed to delete {object_name}: {e}")
            return False

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            RustFS 是否可用
        """
        try:
            self.client.bucket_exists(self.bucket_name)
            return True
        except Exception as e:
            logger.error(f"❌ RustFS health check failed: {e}")
            return False


# 全局单例实例（延迟初始化）
_rustfs_client: Optional[RustFSClient] = None


def get_rustfs_client() -> RustFSClient:
    """
    获取全局 RustFS 客户端实例（单例模式）

    Returns:
        RustFSClient 实例
    """
    global _rustfs_client

    if _rustfs_client is None:
        _rustfs_client = RustFSClient()

    return _rustfs_client
