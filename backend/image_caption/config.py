"""
图片描述配置
从 system_config 表读取多模态大模型调用配置（管理员在前端页面维护）
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger

# 默认 Prompt：控制描述长度，避免 alt 文本过长影响排版
DEFAULT_PROMPT = "请用简体中文简要描述这张图片的内容，100字以内，直接输出描述文本，不要输出其他内容。"

DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_MAX_IMAGES = 30
DEFAULT_CONCURRENCY = 4
DEFAULT_TIMEOUT = 60


@dataclass
class ImageCaptionConfig:
    """图片描述（多模态大模型）配置"""

    enabled: bool
    api_base: str
    api_key: str
    model: str
    prompt: str
    max_images: int
    concurrency: int
    timeout: int

    @classmethod
    def load(cls) -> Optional["ImageCaptionConfig"]:
        """
        从 system_config 表加载配置

        每次任务处理时调用，管理员在页面修改后即时生效，无需重启 Worker。
        存量部署的 system_config 表不含这些键，全部依赖读取端默认值兜底。

        Returns:
            配置对象；未启用或缺少必要配置（api_base / model）时返回 None
        """
        from auth.system_config import SystemConfig

        config = SystemConfig()

        def get(key: str, default: str) -> str:
            value = config.get_config(key)
            return value if value is not None else default

        enabled = get("image_caption_enabled", "false").lower() in ("true", "1", "yes")
        if not enabled:
            return None

        api_base = get("image_caption_api_base", DEFAULT_API_BASE).strip()
        model = get("image_caption_model", "").strip()
        if not api_base or not model:
            logger.warning("⚠️ Image caption enabled but api_base/model not configured, skipping")
            return None

        def get_int(key: str, default: int) -> int:
            try:
                return max(1, int(get(key, str(default))))
            except (ValueError, TypeError):
                return default

        return cls(
            enabled=True,
            api_base=api_base,
            api_key=get("image_caption_api_key", "").strip(),
            model=model,
            prompt=get("image_caption_prompt", DEFAULT_PROMPT).strip() or DEFAULT_PROMPT,
            max_images=get_int("image_caption_max_images", DEFAULT_MAX_IMAGES),
            concurrency=get_int("image_caption_concurrency", DEFAULT_CONCURRENCY),
            timeout=get_int("image_caption_timeout", DEFAULT_TIMEOUT),
        )
