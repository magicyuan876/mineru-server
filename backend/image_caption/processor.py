"""
图片描述写回处理器
将多模态大模型生成的图片描述写回 result.md（图片 alt）与 result.json（img_caption）
"""

import json
import re
from pathlib import Path
from typing import Dict

from loguru import logger

from .captioner import MIME_TYPES, ImageCaptioner
from .config import ImageCaptionConfig


def process_output_dir(output_dir: Path, config: ImageCaptionConfig) -> Dict[str, int]:
    """
    为输出目录中的图片生成描述并写回 result.md / result.json

    调用时机：输出规范化完成本地文件规整之后、RustFS 上传替换 URL 之前，
    此时 markdown/json 中的图片引用仍是 images/<原始文件名>，可按文件名精确匹配。
    任何失败只记日志，不影响任务主流程。

    Returns:
        统计信息 {total, captioned, failed}
    """
    stats = {"total": 0, "captioned": 0, "failed": 0}
    output_dir = Path(output_dir)

    try:
        images_dir = output_dir / "images"
        if not images_dir.is_dir():
            return stats

        images = sorted(p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in MIME_TYPES)
        if len(images) > config.max_images:
            logger.info(f"ℹ️  Too many images ({len(images)}), only captioning first {config.max_images}")
            images = images[: config.max_images]
        stats["total"] = len(images)
        if not images:
            return stats

        captions = ImageCaptioner(config).caption_batch(images)
        stats["captioned"] = len(captions)
        stats["failed"] = stats["total"] - len(captions)
        if not captions:
            return stats

        md_file = output_dir / "result.md"
        if md_file.exists():
            _write_back_markdown(md_file, captions)

        json_file = output_dir / "result.json"
        if json_file.exists():
            _write_back_json(json_file, captions)
    except Exception as e:
        logger.warning(f"⚠️ Image caption processing failed (task continues): {e}")

    return stats


def _write_back_markdown(md_file: Path, captions: Dict[str, str]):
    """将描述写入 markdown 中图片的 alt（Markdown 与 HTML img 两种形态）"""
    content = md_file.read_text(encoding="utf-8")
    original = content

    for filename, desc in captions.items():
        # Markdown 形态：![旧alt](images/xxx.jpg)，保留原路径只替换 alt
        md_pattern = r"!\[[^\]]*\]\(((?:images/)?" + re.escape(filename) + r")\)"
        content = re.sub(md_pattern, lambda m, d=desc: f"![{d}]({m.group(1)})", content)

        # HTML 形态：<img ... src="images/xxx.jpg" ... alt="旧值" ...>
        html_pattern = (
            r'(<img\b[^>]*?\bsrc=["\'][^"\']*' + re.escape(filename) + r'["\'][^>]*?\balt=["\'])[^"\']*(["\'])'
        )
        content = re.sub(html_pattern, lambda m, d=desc: m.group(1) + d + m.group(2), content)

    if content != original:
        md_file.write_text(content, encoding="utf-8")
        logger.info(f"✅ Image captions written to {md_file.name}")


def _write_back_json(json_file: Path, captions: Dict[str, str]):
    """
    将描述写入 JSON 中图片块的 img_caption 字段

    递归遍历以兼容 content_list v1（扁平 block）与 v2（按页嵌套）两种结构，
    只要块中含 img_path 键即按文件名匹配。
    """
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    written = 0

    def visit(obj):
        nonlocal written
        if isinstance(obj, dict):
            img_path = obj.get("img_path")
            if isinstance(img_path, str):
                basename = img_path.replace("\\", "/").split("/")[-1]
                if basename in captions:
                    obj["img_caption"] = [captions[basename]]
                    written += 1
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for item in obj:
                visit(item)

    visit(data)

    if written:
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Image captions written to {json_file.name}: {written} blocks")
