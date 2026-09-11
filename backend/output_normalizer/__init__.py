"""
输出结果规范化模块

统一不同解析引擎的输出格式，确保：
1. Markdown 文件名统一为 result.md
2. 图片目录统一为 images/
3. 图片引用路径统一为 images/xxx.jpg
4. JSON 文件名统一为 result.json
5. 自动上传图片到 RustFS 对象存储并替换 URL

支持的引擎：
- MinerU (pipeline)
- SenseVoice
- Video Processing
- Format Engines (FASTA, GenBank, etc.)
"""

from pathlib import Path
from typing import Dict, Any
from loguru import logger

from .base_output_normalizer import BaseOutputNormalizer
from .standard_output_normalizer import StandardOutputNormalizer

# 全局单例实例
_standard_normalizer = StandardOutputNormalizer()


def normalize_output(output_dir: Path, handle_method="standard") -> Dict[str, Any]:
    """
    便捷函数：规范化输出目录

    Args:
        output_dir: 输出目录路径
        handle_method: 处理方法，目前仅支持 "standard"（StandardOutputNormalizer）

    Returns:
        Dict[str, Any]: 规范化后的文件信息
    """
    output_dir = Path(output_dir)
    if handle_method == "standard":
        logger.info("🤖 Using standard output normalize method")
        return _standard_normalizer.normalize(output_dir)
    else:
        raise ValueError(f"Unknown output_normalize handle_method: {handle_method}")


__all__ = [
    "BaseOutputNormalizer",
    "StandardOutputNormalizer",
    "normalize_output",
]
