"""
多模态大模型调用器
通过 OpenAI 兼容接口为图片生成描述，支持并发调用
"""

import base64
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

from loguru import logger

from .config import ImageCaptionConfig

# 图片后缀 -> MIME 类型，用于构造 base64 data URL
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}


class ImageCaptioner:
    """多模态大模型图片描述调用器"""

    def __init__(self, config: ImageCaptionConfig):
        from openai import OpenAI

        self.config = config
        self.client = OpenAI(
            base_url=config.api_base,
            api_key=config.api_key or "none",
            timeout=config.timeout,
        )

    def caption_image(self, image_path: Path) -> str:
        """
        为单张图片生成描述

        Returns:
            描述文本（已清洗为一行，便于写入 markdown alt / HTML alt 属性）
        """
        image_path = Path(image_path)
        mime = MIME_TYPES.get(image_path.suffix.lower(), "image/jpeg")
        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")

        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.config.prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        # 描述会写入 alt 属性/markdown alt，需去掉换行与双引号避免破坏文档结构
        return " ".join(text.split()).replace('"', "'")

    def caption_batch(self, image_paths: List[Path]) -> Dict[str, str]:
        """
        并发为一批图片生成描述

        调用是纯网络 IO，线程池即可充分利用并发，无需 asyncio。
        单张失败只记日志跳过，不影响其他图片与任务主流程。

        Returns:
            {文件名: 描述} 映射（失败的图片不出现在结果中）
        """
        results: Dict[str, str] = {}
        if not image_paths:
            return results

        logger.info(f"🖼️ Captioning {len(image_paths)} images (concurrency={self.config.concurrency})")
        with ThreadPoolExecutor(max_workers=self.config.concurrency) as executor:
            future_map = {executor.submit(self.caption_image, p): p for p in image_paths}
            for future in as_completed(future_map):
                path = future_map[future]
                try:
                    caption = future.result()
                    if caption:
                        results[path.name] = caption
                except Exception as e:
                    logger.warning(f"⚠️ Failed to caption image {path.name}: {e}")

        logger.info(f"✅ Captioned {len(results)}/{len(image_paths)} images")
        return results

    def test_connection(self) -> Tuple[bool, str, int]:
        """
        测试模型端点连通性（供配置页"测试连接"按钮使用）

        Returns:
            (是否成功, 消息, 耗时毫秒)
        """
        start = time.time()
        try:
            models = self.client.models.list()
            latency_ms = int((time.time() - start) * 1000)
            model_ids = [m.id for m in models.data]
            if self.config.model in model_ids:
                return True, f"连接成功，模型 {self.config.model} 可用", latency_ms
            return (
                True,
                f"连接成功，但模型列表中未找到 {self.config.model}（可用: {', '.join(model_ids[:5])}...）",
                latency_ms,
            )
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            return False, f"{type(e).__name__}: {e}", latency_ms
