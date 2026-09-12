"""
输出结果规范化器基类
"""

from pathlib import Path
from typing import Callable, Dict, Any
from loguru import logger
import re
import json
import os


class BaseOutputNormalizer:
    """
    输出结果规范化器基类
    定义了规范化的基本流程和公共方法（如 RustFS 上传）
    """

    STANDARD_MARKDOWN_NAME = "result.md"
    STANDARD_JSON_NAME = "result.json"
    STANDARD_IMAGE_DIR = "images"

    def __init__(self):
        """
        初始化规范化器
        """
        self._rustfs_client = None

    def normalize(
        self, output_dir: Path, image_processor: Callable[[Path, Dict[str, Any]], None] = None
    ) -> Dict[str, Any]:
        """
        规范化输出目录（模板方法）

        Args:
            output_dir: 输出目录（引擎的原始输出目录）
            image_processor: 可选的图片处理回调，在本地文件规范化之后、RustFS 上传之前调用，
                此时图片引用仍是 images/<原始文件名>，可按文件名匹配（用于图片描述写回等场景）

        Returns:
            规范化后的文件信息
        """
        output_dir = Path(output_dir)
        if not output_dir.exists():
            raise ValueError(f"Output directory does not exist: {output_dir}")

        logger.info(f"🔧 Normalizing output directory: {output_dir}")

        # 1. 执行本地文件规范化（由子类实现）
        result = self._normalize_local_files(output_dir)

        # 确保基本字段存在
        result.setdefault("markdown_file", None)
        result.setdefault("json_file", None)
        result.setdefault("image_dir", None)
        result.setdefault("image_count", 0)
        result.setdefault("rustfs_enabled", False)
        result.setdefault("images_uploaded", False)

        # 1.5 可选图片处理钩子（如多模态大模型图片描述写回）
        # 必须在 RustFS 上传前执行：上传后图片被重命名为短随机名，无法按文件名匹配
        if image_processor and result["image_dir"] and result["image_count"] > 0:
            try:
                image_processor(output_dir, result)
            except Exception as e:
                logger.warning(f"⚠️  Image processor failed (continuing): {e}")

        # 2. 自动上传图片到 RustFS 并替换 URL（基础功能，始终启用）
        if result["image_dir"] and result["image_count"] > 0:
            self._process_rustfs_upload(result)
        else:
            logger.debug("ℹ️  No images to upload")
            result["rustfs_enabled"] = False
            result["images_uploaded"] = False

        logger.info("✅ Normalization complete:")
        logger.info(f"   Markdown: {result['markdown_file']}")
        logger.info(f"   Images: {result['image_count']} files in {result['image_dir']}")
        logger.info(f"   JSON: {result['json_file']}")
        logger.info(f"   RustFS: {result['rustfs_enabled']} (uploaded: {result['images_uploaded']})")

        return result

    def _normalize_local_files(self, output_dir: Path) -> Dict[str, Any]:
        """
        规范化本地文件（子类必须实现）

        Args:
            output_dir: 输出目录

        Returns:
            Dict containing:
            - markdown_file: Optional[Path]
            - json_file: Optional[Path]
            - image_dir: Optional[Path]
            - image_count: int
        """
        raise NotImplementedError

    def _process_rustfs_upload(self, result: Dict[str, Any]):
        """处理 RustFS 上传和 URL 替换"""

        # 检查是否启用 RustFS
        rustfs_enabled = os.getenv("RUSTFS_ENABLED", "true").lower() in ("true", "1", "yes")

        if not rustfs_enabled:
            logger.info("ℹ️  RustFS is disabled (RUSTFS_ENABLED=false), using local file service")
            result["rustfs_enabled"] = False
            result["images_uploaded"] = False
            return

        try:
            logger.info(f"📤 Uploading {result['image_count']} images to RustFS...")
            url_mapping = self._upload_images_to_rustfs(result["image_dir"])

            if url_mapping:
                # 替换 Markdown 中的图片路径
                if result["markdown_file"]:
                    self._replace_markdown_urls(result["markdown_file"], url_mapping)

                # 替换 JSON 中的图片路径
                if result["json_file"]:
                    self._replace_json_urls(result["json_file"], url_mapping)

                result["rustfs_enabled"] = True
                result["images_uploaded"] = True
                logger.info(f"✅ Images uploaded to RustFS: {len(url_mapping)}/{result['image_count']}")
            else:
                logger.warning("⚠️  No images uploaded (url_mapping empty)")
                result["rustfs_enabled"] = False
                result["images_uploaded"] = False
        except Exception as e:
            logger.error(f"❌ Failed to upload images to RustFS: {e}")
            logger.error(f"   Error details: {type(e).__name__}: {str(e)}")
            result["rustfs_enabled"] = False
            result["images_uploaded"] = False
            # RustFS 上传失败不应中断主流程，继续使用本地路径
            logger.warning("⚠️  Continuing with local image paths (RustFS upload failed)")

    def _upload_images_to_rustfs(self, image_dir: Path) -> Dict[str, str]:
        """
        上传图片到 RustFS 对象存储

        Args:
            image_dir: 图片目录

        Returns:
            {本地文件名: RustFS URL} 的映射字典
        """
        # 延迟导入，避免在不需要时初始化
        try:
            from storage import RustFSClient

            if self._rustfs_client is None:
                self._rustfs_client = RustFSClient()

            # 直接上传，使用日期前缀 (YYYYMMDD/短uuid.ext)
            logger.info(f"📤 Uploading images to RustFS: {image_dir}")
            url_mapping = self._rustfs_client.upload_directory(
                str(image_dir),
                prefix=None,  # 不使用额外前缀，直接用日期分组
            )

            return url_mapping

        except Exception as e:
            logger.error(f"❌ Failed to initialize RustFS client: {e}")
            raise

    def _replace_markdown_urls(self, md_file: Path, url_mapping: Dict[str, str]):
        """
        替换 Markdown 中的图片路径为 RustFS URL

        Args:
            md_file: Markdown 文件
            url_mapping: {本地文件名: RustFS URL} 映射
        """
        try:
            content = md_file.read_text(encoding="utf-8")
            original_content = content
            replaced_count = 0

            logger.debug(f"🔍 Replacing URLs in {md_file.name}")
            logger.debug(f"   URL mapping: {url_mapping}")

            # 替换所有图片引用（统一转换为 HTML 格式，更通用）
            for filename, url in url_mapping.items():
                # 方式1: Markdown 格式 -> HTML 格式
                # ![alt](images/xxx.jpg) -> <img src="https://..." alt="alt">
                pattern1 = rf"!\[(.*?)\]\({self.STANDARD_IMAGE_DIR}/{re.escape(filename)}\)"
                matches1 = re.findall(pattern1, content)
                if matches1:
                    logger.debug(f"   Found Markdown pattern: {pattern1}")
                    logger.debug(f"   Matches: {matches1}")

                # 转换为 HTML 格式（更通用，前端渲染友好）
                def markdown_to_html(match):
                    alt_text = match.group(1) or filename
                    return f'<img src="{url}" alt="{alt_text}">'

                new_content = re.sub(pattern1, markdown_to_html, content)
                if new_content != content:
                    replaced_count += 1
                    logger.debug(f"   ✅ Replaced Markdown -> HTML: {filename} -> {url}")
                content = new_content

                # 方式2: HTML 格式 -> 更新 URL
                # <img src="images/xxx.jpg"> -> <img src="https://...">
                pattern2 = rf'<img([^>]*?)src=["\']({self.STANDARD_IMAGE_DIR}/{re.escape(filename)})["\']([^>]*?)>'
                matches2 = re.findall(pattern2, content)
                if matches2:
                    logger.debug(f"   Found HTML pattern: {pattern2}")
                    logger.debug(f"   Matches: {matches2}")

                new_content = re.sub(pattern2, rf'<img\1src="{url}"\3>', content)
                if new_content != content:
                    replaced_count += 1
                    logger.debug(f"   ✅ Replaced HTML: {filename} -> {url}")
                content = new_content

            if content != original_content:
                md_file.write_text(content, encoding="utf-8")
                logger.info(f"✅ Replaced {replaced_count} image URLs in {md_file.name}")
            else:
                logger.warning(f"⚠️  No replacements made in {md_file.name}")
                logger.debug(f"   Content preview (first 500 chars):\n{original_content[:500]}")

        except Exception as e:
            logger.error(f"❌ Failed to replace URLs in Markdown: {e}")
            raise

    def _replace_json_urls(self, json_file: Path, url_mapping: Dict[str, str]):
        """
        替换 JSON 中的图片路径为 RustFS URL

        Args:
            json_file: JSON 文件
            url_mapping: {本地文件名: RustFS URL} 映射
        """
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            replaced_count = 0
            logger.debug(f"🔍 Replacing URLs in {json_file.name}")

            # 递归替换 JSON 中的所有图片路径
            def replace_paths(obj, path=""):
                nonlocal replaced_count
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        if isinstance(value, str):
                            # 检查是否是图片路径
                            for filename, url in url_mapping.items():
                                if filename in value and self.STANDARD_IMAGE_DIR in value:
                                    old_value = obj[key]
                                    obj[key] = url
                                    replaced_count += 1
                                    logger.debug(f"   ✅ Replaced JSON[{path}.{key}]: {old_value} -> {url}")
                                    break
                        else:
                            replace_paths(value, f"{path}.{key}")
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        replace_paths(item, f"{path}[{i}]")

            replace_paths(data)

            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            if replaced_count > 0:
                logger.info(f"✅ Replaced {replaced_count} image URLs in {json_file.name}")
            else:
                logger.warning(f"⚠️  No replacements made in {json_file.name}")

        except Exception as e:
            logger.error(f"❌ Failed to replace URLs in JSON: {e}")
            raise
