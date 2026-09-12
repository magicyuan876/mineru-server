"""
图片描述模块（多模态大模型）

MinerU 解析完成后，调用 OpenAI 兼容的多模态大模型为结果中的图片生成描述，
写回 result.md 的图片 alt 与 result.json 的 img_caption 字段。
启用开关与调用配置由管理员在前端页面维护，存储于 system_config 表。
"""

from .captioner import ImageCaptioner
from .config import ImageCaptionConfig
from .processor import process_output_dir

__all__ = [
    "ImageCaptionConfig",
    "ImageCaptioner",
    "process_output_dir",
]
