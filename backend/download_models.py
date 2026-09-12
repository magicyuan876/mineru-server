#!/usr/bin/env python3
"""
模型预下载脚本 - Tianshu

策略说明:
1. MinerU / YOLO / Audio 模型: 使用此脚本预先下载到 ./models 目录。
2. LaMa 等运行时按需获取的模型: 设置为 auto_download，首次使用时由引擎自动下载。
3. 配置文件生成:
   - 自动在模型目录生成 mineru.json（MinerU 3.0 新格式），供 entrypoint 脚本分发到各服务。
   - 配置文件格式: {"models-dir": {"pipeline": "...", "vlm": "..."}, "config_version": "1.3.1"}
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from loguru import logger

# 配置日志
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

# ==============================================================================
# 模型配置清单
# ==============================================================================
MODELS = {
    # -------------------------------------------------------------------------
    # 1. MinerU 核心模型 (需要预下载)
    # -------------------------------------------------------------------------
    "mineru_pipeline": {
        "name": "MinerU Pipeline (PDF-Extract-Kit)",
        "repo_id": "OpenDataLab/PDF-Extract-Kit-1.0",
        "source": "modelscope",
        "target_dir": "PDF-Extract-Kit-1.0",
        "description": "PDF OCR, Layout Analysis models (For 'pipeline' mode)",
        "required": True,
    },
    "mineru_vlm": {
        "name": "MinerU 2.5 Pro VLM (1.2B)",
        "model_id": "OpenDataLab/MinerU2.5-Pro-2605-1.2B",
        "source": "modelscope",
        "target_dir": "MinerU2.5-Pro-2605-1.2B",
        "description": "Vision Language Model (For 'vlm-engine' & 'hybrid-engine')",
        "required": True,
    },
    # -------------------------------------------------------------------------
    # 2. 其他模型 (需要预下载)
    # -------------------------------------------------------------------------
    "sensevoice": {
        "name": "SenseVoice Audio Recognition",
        "model_id": "iic/SenseVoiceSmall",
        "source": "modelscope",
        "target_dir": "SenseVoiceSmall",
        "description": "Multi-language speech recognition model",
        "required": True,
    },
    "paraformer": {
        "name": "Paraformer Speaker Diarization",
        "model_id": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "source": "modelscope",
        "target_dir": "Paraformer",
        "description": "Speaker diarization and VAD model",
        "required": False,
    },
    "yolo11": {
        "name": "YOLO11x Watermark Detection",
        "repo_id": "corzent/yolo11x_watermark_detection",
        "filename": "best.pt",
        "source": "huggingface",
        "target_dir": "YOLO11",
        "description": "Watermark detection model",
        "required": False,
    },
    "lama": {
        "name": "LaMa Watermark Inpainting",
        "auto_download": True,
        "description": "Will be downloaded by simple_lama_inpainting on first use",
        "required": False,
    },
}

# ==============================================================================
# 下载函数
# ==============================================================================


def download_from_huggingface(repo_id, target_dir, filename=None):
    """从 HuggingFace 下载"""
    try:
        from huggingface_hub import snapshot_download, hf_hub_download

        # 配置国内镜像
        hf_endpoint = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ.setdefault("HF_ENDPOINT", hf_endpoint)

        if filename:
            logger.info(f"    Downloading file: {filename}")
            path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(target_dir),
                local_dir_use_symlinks=False,
                resume_download=True,
            )
        else:
            logger.info(f"    Downloading repository: {repo_id}")
            path = snapshot_download(
                repo_id=repo_id, local_dir=str(target_dir), local_dir_use_symlinks=False, resume_download=True
            )
        return path
    except Exception as e:
        logger.error(f"    ❌ Download failed: {e}")
        return None


def download_from_modelscope(model_id, target_dir):
    """从 ModelScope 下载"""
    try:
        from modelscope import snapshot_download

        logger.info(f"    Downloading from ModelScope: {model_id}")
        path = snapshot_download(model_id, local_dir=str(target_dir), revision="master")
        return path
    except Exception as e:
        logger.error(f"    ❌ Download failed: {e}")
        return None


# ==============================================================================
# 验证与辅助函数
# ==============================================================================


def verify_model_files(path, model_name):
    """验证下载是否完整"""
    path_obj = Path(path)
    if not path_obj.exists():
        return False

    # 1. MinerU Pipeline - 校验 MinerU 3.0 必需的子路径
    # 参考: mineru/utils/enum_class.py ModelPath
    if model_name == "mineru_pipeline":
        models_dir = path_obj / "models"
        required_subpaths = [
            models_dir / "Layout" / "PP-DocLayoutV2",
            models_dir / "MFR" / "unimernet_hf_small_2503",  # MinerU 3.0 新版本路径(带 _2503 后缀)
            models_dir / "MFR" / "pp_formulanet_plus_m",  # MinerU 3.0 新增
            models_dir / "OCR" / "paddleocr_torch",
        ]
        missing = [str(p) for p in required_subpaths if not p.exists()]
        if missing:
            logger.warning("    ⚠️  Missing MinerU 3.0 required paths:")
            for m in missing:
                logger.warning(f"        - {m}")
            return False
        return True

    # 2. MinerU VLM
    elif model_name == "mineru_vlm":
        if not any(path_obj.rglob("*.safetensors")):
            logger.warning(f"    ⚠️  No safetensors found in {path}")
            return False

    # 3. YOLO (单文件或目录)
    elif model_name == "yolo11":
        if path_obj.is_file():
            if path_obj.suffix != ".pt":
                return False
        elif not list(path_obj.rglob("*.pt")):
            logger.warning("    ⚠️  No .pt files found")
            return False

    logger.info("    ✅ Model files verified")
    return True


def get_directory_size(path):
    path_obj = Path(path)
    if not path_obj.exists():
        return 0
    if path_obj.is_file():
        return path_obj.stat().st_size / (1024 * 1024)
    return sum(f.stat().st_size for f in path_obj.rglob("*") if f.is_file()) / (1024 * 1024)


def check_model_exists(output_path, config, name):
    target_dir = output_path / config["target_dir"]
    if config.get("filename"):
        f = target_dir / config["filename"]
        return (f.exists() and f.stat().st_size > 0), "File found"
    if not target_dir.exists():
        return False, "Dir missing"
    # MinerU Pipeline: 额外校验 MinerU 3.0 必需的子路径，防止旧版本目录跳过更新
    if name == "mineru_pipeline":
        models_dir = target_dir / "models"
        required = [
            models_dir / "Layout" / "PP-DocLayoutV2",
            models_dir / "MFR" / "unimernet_hf_small_2503",
            models_dir / "MFR" / "pp_formulanet_plus_m",
            models_dir / "OCR" / "paddleocr_torch",
        ]
        missing = [p for p in required if not p.exists()]
        if missing:
            return False, f"Missing MinerU 3.0 paths: {[p.name for p in missing]}"
    if any(target_dir.iterdir()):
        return True, "Files found"
    return False, "Dir empty"


def generate_mineru_json(output_dir):
    """
    生成 mineru.json (MinerU 3.0 新格式)
    ✅ [核心修复] 将配置文件直接保存到共享的 models 目录下 (output_dir)，
    这样该文件会持久化到宿主机 ./models/mineru.json，
    并由 docker-entrypoint.sh 脚本分发到各容器的 ~/mineru.json。

    MinerU 3.0 配置格式变更:
    - 旧: {"models-dir": "...", "vlm-models-dir": "..."}
    - 新: {"models-dir": {"pipeline": "...", "vlm": "..."}, "model-source": "...", "config_version": "1.3.2"}

    model-source 必须显式写 "local"：缺省时 MinerU 3.4+ 会按旧版配置做原地迁移，
    把 model-source 写成 huggingface，离线/本地模型部署下解析时会尝试联网下载而失败。
    """
    config_path = Path(output_dir) / "mineru.json"

    # 注意：这里的 paths 是容器内的绝对路径。
    # pipeline 必须指向仓库根（不含 models/ 后缀）：MinerU 3.4+ 的模型相对路径
    # （如 models/MFR/unimernet_hf_small_2503）自带 models/ 前缀，指到子目录会拼出
    # models/models/... 的双重路径。
    config = {
        "models-dir": {
            "pipeline": "/app/models/PDF-Extract-Kit-1.0",
            "vlm": "/app/models/MinerU2.5-Pro-2605-1.2B",
        },
        "model-source": "local",
        "config_version": "1.3.2",
    }
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        logger.success(f"✅ mineru.json created at: {config_path}")
        logger.info("    -> pipeline: /app/models/PDF-Extract-Kit-1.0/models")
        logger.info("    -> vlm:      /app/models/MinerU2.5-Pro-2605-1.2B")
    except Exception as e:
        logger.error(f"❌ Failed to create mineru.json: {e}")


# ==============================================================================
# 主程序
# ==============================================================================


def main(output_dir, selected_models=None, force=False):
    logger.info("=" * 60)
    logger.info("🚀 Tianshu Model Download Script (Hybrid Strategy)")
    logger.info("=" * 60)

    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 Output directory (Container/Host mapped): {output_path}")

    # 筛选模型
    models_to_download = MODELS
    if selected_models:
        selected_list = [m.strip() for m in selected_models.split(",")]
        models_to_download = {k: v for k, v in MODELS.items() if k in selected_list}

    manifest = {"created": datetime.now().isoformat(), "models": {}, "total_size_mb": 0}
    total_dl, total_skip, total_fail = 0, 0, 0

    for name, config in models_to_download.items():
        logger.info(f"📦 [{name.upper()}] {config['name']}")

        try:
            # 策略：运行时自动下载的模型直接跳过
            if config.get("auto_download"):
                logger.info(f"    ℹ️  {name} will be auto-downloaded by runtime engine")
                logger.info(f"        Target: {config.get('description', 'Cache directory')}")
                manifest["models"][name] = {"status": "auto_download"}
                continue

            target = output_path / config["target_dir"]

            # 检查存在
            if not force:
                exists, reason = check_model_exists(output_path, config, name)
                if exists:
                    size_mb = get_directory_size(target)
                    logger.info(f"    ✅ Already exists ({size_mb:.1f} MB)")
                    logger.info(f"    📂 Path: {target}")
                    manifest["models"][name] = {"status": "exists", "path": str(target), "size_mb": round(size_mb, 2)}
                    total_skip += 1
                    logger.info("")
                    continue

            # 下载
            logger.info(f"    ⬇️  Downloading to {config['target_dir']}...")
            path = None
            src = config["source"]

            if src == "huggingface":
                path = download_from_huggingface(config["repo_id"], str(target), config.get("filename"))
            elif src == "modelscope":
                # 优先使用 model_id，如果没有则用 repo_id (兼容旧配置)
                mid = config.get("model_id") or config.get("repo_id")
                path = download_from_modelscope(mid, str(target))

            # ✅ 核心优化：容错处理
            if path and verify_model_files(path, name):
                size_mb = get_directory_size(path)
                manifest["models"][name] = {"status": "downloaded", "path": str(path)}
                logger.info(f"    ✅ Success ({size_mb:.1f} MB)")
                logger.info(f"    📂 Path: {path}")
                total_dl += 1
            else:
                logger.error(f"    ❌ Validation failed for {name}")
                if config.get("required", False):
                    total_fail += 1
                else:
                    logger.warning(f"    ⚠️ [IGNORED] Optional model {name} failed, but not required. Skipping...")

        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            if config.get("required", False):
                total_fail += 1
            else:
                logger.warning(f"    ⚠️ [IGNORED] Optional model {name} failed, but not required. Skipping...")
        logger.info("")

    # 无论模型下载成功与否，都尝试生成配置文件，确保容器有配置可用
    generate_mineru_json(output_path)

    with open(output_path / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("=" * 60)
    logger.info(f"✅ Downloaded: {total_dl} | ⏭️  Skipped: {total_skip} | ❌ Failed: {total_fail}")

    # 只要必填项没有失败，脚本即以 0 状态退出，确保后续服务(如 vllm)能够启动
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="./models")
    parser.add_argument("--models")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        sys.exit(main(args.output, args.models, args.force))
    except KeyboardInterrupt:
        sys.exit(130)
