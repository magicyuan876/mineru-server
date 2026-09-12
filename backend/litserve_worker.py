"""
MinerU Tianshu - LitServe Worker
天枢 LitServe Worker

企业级 AI 数据预处理平台 - GPU Worker
支持文档、图片、音频、视频等多模态数据处理
使用 LitServe 实现 GPU 资源的自动负载均衡
Worker 主动循环拉取任务并处理

优化日志 (2026-02-16):
1. [并发] 强制限制 workers_per_device=1 (可通过 MAX_CONCURRENT_TASKS 调整)，防止爆显存
2. [修复] 强制回写源 PDF 到 output 目录，解决前端无法预览源文件的问题
3. [修复] MinerU 返回结果中补全 json_content 和 pdf_path 以支持双向定位
4. [性能] 移除单次任务后的强制显存清理 (clean_memory)，依赖引擎的智能休眠机制
5. [稳定] 增强 VLLM 容器互斥切换的健壮性
"""

import os
import json
import sys
import time
import threading
import signal
import atexit
import shutil
import socket
import multiprocessing
import warnings
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

# ==============================================================================
# 1. LitServe MCP Patch (Disable Internal MCP)
# ==============================================================================
try:
    import litserve.mcp as ls_mcp

    if not hasattr(ls_mcp, "MCPServer"):

        class DummyMCPServer:
            def __init__(self, *args, **kwargs):
                pass

        ls_mcp.MCPServer = DummyMCPServer
        if "litserve.mcp" in sys.modules:
            sys.modules["litserve.mcp"].MCPServer = DummyMCPServer

    if not hasattr(ls_mcp, "StreamableHTTPSessionManager"):

        class DummyStreamableHTTPSessionManager:
            def __init__(self, *args, **kwargs):
                pass

        ls_mcp.StreamableHTTPSessionManager = DummyStreamableHTTPSessionManager
        if "litserve.mcp" in sys.modules:
            sys.modules["litserve.mcp"].StreamableHTTPSessionManager = DummyStreamableHTTPSessionManager

    class DummyMCPConnector:
        """完全禁用 LitServe 内置 MCP 的 Dummy 实现"""

        def __init__(self, *args, **kwargs):
            self.mcp_server = None
            self.session_manager = None
            self.request_handler = None

        @asynccontextmanager
        async def lifespan(self, app):
            yield

        def connect_mcp_server(self, *args, **kwargs):
            pass

    ls_mcp._LitMCPServerConnector = DummyMCPConnector
    if "litserve.mcp" in sys.modules:
        sys.modules["litserve.mcp"]._LitMCPServerConnector = DummyMCPConnector

except Exception as e:
    warnings.warn(f"Failed to patch litserve.mcp (MCP will be disabled): {e}")

import litserve as ls
from litserve.connector import check_cuda_with_nvidia_smi
from loguru import logger

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Local imports
from task_db import TaskDB
from output_normalizer import normalize_output
from utils import parse_list_arg, ALLOWED_UPLOAD_EXTENSIONS
import importlib.util


# ==============================================================================
# 2. Dependency Checks & Global Configurations
# ==============================================================================
def check_dependency(module_name: str, display_name: str) -> bool:
    """Helper to check if a module is installed and log the result."""
    available = importlib.util.find_spec(module_name) is not None
    icon = "✅" if available else "ℹ️ "
    msg = "available" if available else "not available (optional)"
    logger.info(f"{icon} {display_name} {msg}")
    return available


# Check optional dependencies
MARKITDOWN_AVAILABLE = False
try:
    from markitdown import MarkItDown

    MARKITDOWN_AVAILABLE = True
    logger.info("✅ MarkItDown available")
except ImportError:
    logger.info("ℹ️  MarkItDown not available (optional)")

MINERU_PIPELINE_AVAILABLE = check_dependency("mineru_pipeline", "MinerU Pipeline")
SENSEVOICE_AVAILABLE = check_dependency("audio_engines", "SenseVoice")
VIDEO_ENGINE_AVAILABLE = check_dependency("video_engines", "Video Engine")
WATERMARK_REMOVAL_AVAILABLE = check_dependency("remove_watermark", "Watermark Removal")

FORMAT_ENGINES_AVAILABLE = False
try:
    from format_engines import FormatEngineRegistry, FASTAEngine, GenBankEngine

    FormatEngineRegistry.register(FASTAEngine())
    FormatEngineRegistry.register(GenBankEngine())
    FORMAT_ENGINES_AVAILABLE = True
    logger.info(f"✅ Format Engines available: {', '.join(FormatEngineRegistry.get_supported_extensions())}")
except ImportError as e:
    logger.info(f"ℹ️  Format Engines not available: {e}")

IMAGE_CAPTION_AVAILABLE = False
try:
    from image_caption import ImageCaptionConfig, process_output_dir

    IMAGE_CAPTION_AVAILABLE = True
    logger.info("✅ Image Caption available")
except ImportError as e:
    logger.info(f"ℹ️  Image Caption not available: {e}")


# ==============================================================================
# 3. VLLM Container Controller
# ==============================================================================
class VLLMController:
    """管理 vLLM Docker 容器的互斥启动"""

    def __init__(self):
        pass

    def _get_client(self):
        """按需获取 Docker 客户端"""
        try:
            import docker

            return docker.from_env()
        except Exception as e:
            logger.warning(f"⚠️  Docker client init failed: {e}")
            return None

    def ensure_service(self, target_container: str, conflict_container: str):
        """
        确保目标容器运行，并关闭冲突容器 (严格互斥逻辑)
        """
        client = self._get_client()
        if not client:
            return

        try:
            # 1. 检查并关闭冲突容器
            try:
                conflict = client.containers.get(conflict_container)
                if conflict.status == "running":
                    logger.info(f"🛑 Stopping conflicting service {conflict_container} to free VRAM...")
                    conflict.stop()
                    time.sleep(2)  # 等待释放
                    logger.info(f"✅ Service {conflict_container} stopped.")
            except Exception:
                pass

            # 2. 检查并启动目标容器
            try:
                target = client.containers.get(target_container)
                if target.status == "running":
                    return

                logger.info(f"🚀 Starting service {target_container} (Manual/Cold Start)...")
                target.start()

                # 等待服务健康 (简单轮询)
                for _ in range(30):
                    time.sleep(1)
                    target.reload()
                    if target.status == "running":
                        break
                logger.info(f"✅ Service {target_container} started.")

            except Exception as e:
                logger.error(f"❌ Failed to start target container {target_container}: {e}")
                raise e
        finally:
            try:
                client.close()
            except Exception:
                pass


# ==============================================================================
# 4. MinerU Worker API
# ==============================================================================
class MinerUWorkerAPI(ls.LitAPI):
    def __init__(
        self,
        mineru_vllm_api_list=None,
        output_dir=None,
        poll_interval=0.5,
        enable_worker_loop=True,
    ):
        super().__init__()

        # 路径配置
        project_root = Path(__file__).parent.parent
        default_output = project_root / "data" / "output"
        self.output_dir = output_dir or os.getenv("OUTPUT_PATH", str(default_output))

        # 运行配置
        self.poll_interval = poll_interval
        self.enable_worker_loop = enable_worker_loop

        # API 配置
        self.mineru_vllm_api_list = mineru_vllm_api_list or []

        # 进程间共享计数器
        ctx = multiprocessing.get_context("spawn")
        self._global_worker_counter = ctx.Value("i", 0)

        # 初始化控制器
        self.vllm_controller = VLLMController()

    def setup(self, device):
        """初始化 Worker (每个 GPU 进程调用一次)"""
        with self._global_worker_counter.get_lock():
            my_global_index = self._global_worker_counter.value
            self._global_worker_counter.value += 1

        logger.info(f"🔢 [Init] I am Global Worker #{my_global_index} (on {device})")

        # API 分配
        self.mineru_vllm_api = None
        if self.mineru_vllm_api_list:
            assigned_mineru_api = self.mineru_vllm_api_list[my_global_index % len(self.mineru_vllm_api_list)]
            self.mineru_vllm_api = assigned_mineru_api
            logger.info(f"🔧 Worker #{my_global_index} assigned MinerU VLLM API: {assigned_mineru_api}")

        # 设置 CUDA 隔离
        if "cuda:" in str(device):
            gpu_id = str(device).split(":")[-1]
            os.environ["CUDA_VISIBLE_DEVICES"] = gpu_id
            os.environ["MINERU_DEVICE_MODE"] = "cuda:0"
            logger.info(f"🎯 [GPU Isolation] Set CUDA_VISIBLE_DEVICES={gpu_id}")

        # 配置模型源
        model_source = os.getenv("MODEL_DOWNLOAD_SOURCE", "auto").lower()
        if model_source in ["modelscope", "auto"]:
            try:
                importlib.util.find_spec("modelscope")
                os.environ["MINERU_MODEL_SOURCE"] = "modelscope"
            except ImportError:
                if model_source == "modelscope":
                    logger.warning("⚠️  ModelScope not available, falling back to HuggingFace")

        if model_source == "huggingface":
            hf_endpoint = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
            os.environ.setdefault("HF_ENDPOINT", hf_endpoint)

        # 设备配置
        self.device = device
        if "cuda" in str(device):
            self.accelerator = "cuda"
            self.engine_device = "cuda:0"
        elif "mps" in str(device):
            # Apple Silicon: MinerU 通过 MINERU_DEVICE_MODE 使用 MPS 加速；
            # 音视频等辅助引擎（FunASR 等）对 MPS 支持不稳定，统一走 CPU
            self.accelerator = "mps"
            self.engine_device = "cpu"
            os.environ.setdefault("MINERU_DEVICE_MODE", "mps")
        else:
            self.accelerator = "cpu"
            self.engine_device = "cpu"

        # MinerU VRAM 设置
        from mineru.utils.model_utils import get_vram

        if os.getenv("MINERU_VIRTUAL_VRAM_SIZE", None) is None:
            if self.accelerator == "cuda":
                try:
                    vram = round(get_vram("cuda:0"))
                    os.environ["MINERU_VIRTUAL_VRAM_SIZE"] = str(vram)
                except Exception:
                    os.environ["MINERU_VIRTUAL_VRAM_SIZE"] = "8"
            elif self.accelerator == "mps":
                # Apple Silicon 统一内存架构，给较大阈值避免频繁 GC
                os.environ["MINERU_VIRTUAL_VRAM_SIZE"] = "8"
            else:
                os.environ["MINERU_VIRTUAL_VRAM_SIZE"] = "1"

        # 初始化数据库
        db_path_env = os.getenv("DATABASE_PATH")
        if db_path_env:
            db_path = Path(db_path_env).resolve()
        else:
            project_root = Path(__file__).parent.parent
            db_path = (project_root / "data" / "db" / "mineru_tianshu.db").resolve()

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.task_db = TaskDB(str(db_path))

        # 初始化状态
        self.running = True
        self.current_task_id = None
        hostname = socket.gethostname()
        pid = os.getpid()
        self.worker_id = f"tianshu-{hostname}-{device}-{pid}"

        # 引擎占位符
        self.markitdown = MarkItDown() if MARKITDOWN_AVAILABLE else None
        self.mineru_pipeline_engine = None
        self.sensevoice_engine = None
        self.video_engine = None
        self.watermark_handler = None

        logger.info(f"🚀 Worker Setup Complete: {self.worker_id}")

        if WATERMARK_REMOVAL_AVAILABLE and self.accelerator == "cuda":
            try:
                from remove_watermark.pdf_watermark_handler import PDFWatermarkHandler

                self.watermark_handler = PDFWatermarkHandler(device="cuda:0", use_lama=True)
                logger.info("✅ Watermark engine initialized")
            except Exception as e:
                logger.error(f"❌ Failed to init watermark engine: {e}")

        if self.enable_worker_loop:
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()

    def _worker_loop(self):
        logger.info(f"🔁 {self.worker_id} started task polling loop")
        loop_count = 0
        last_stats_log = 0

        while self.running:
            try:
                loop_count += 1
                task = self.task_db.get_next_task(worker_id=self.worker_id)

                if task:
                    task_id = task["task_id"]
                    self.current_task_id = task_id
                    logger.info(f"📥 {self.worker_id} pulled task: {task_id}")

                    try:
                        self._process_task(task)
                        logger.info(f"✅ {self.worker_id} completed task: {task_id}")
                    except Exception as e:
                        logger.error(f"❌ {self.worker_id} failed task {task_id}: {e}")
                        logger.exception(e)
                    finally:
                        self.current_task_id = None
                else:
                    if loop_count - last_stats_log >= 20:
                        try:
                            stats = self.task_db.get_queue_stats()
                            if loop_count % 100 == 0:
                                logger.info(f"💤 {self.worker_id} idle. Queue stats: {stats}")
                        except Exception:
                            pass
                        last_stats_log = loop_count
                    time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"❌ Worker loop error: {e}")
                time.sleep(self.poll_interval)

    def _process_task(self, task: dict):
        """处理任务"""
        task_id = task["task_id"]
        file_path = task["file_path"]
        options = json.loads(task.get("options", "{}"))
        parent_task_id = task.get("parent_task_id")
        backend = task.get("backend", "auto")

        # 防重入：调度器会把超时的 processing 父任务打回 pending 被重新拉取，
        # 父任务只负责等待子任务合并，重复执行会重复拆分
        if task.get("is_parent") and (task.get("child_count") or 0) > 0:
            logger.warning(f"⚠️  Parent task {task_id} re-pulled (likely stale reset), skipping re-processing")
            return

        try:
            # 1. 智能服务切换
            if backend in ["vlm-auto-engine", "hybrid-auto-engine"] and self.mineru_vllm_api:
                self.vllm_controller.ensure_service(
                    target_container="tianshu-vllm-mineru", conflict_container="tianshu-vllm-paddleocr"
                )

            file_ext = Path(file_path).suffix.lower()

            # 2. PDF 拆分
            if file_ext == ".pdf" and not parent_task_id:
                if self._should_split_pdf(task_id, file_path, task, options):
                    return

            # 3. ZIP 解包拆分（优先于引擎路由，任何 backend 值都走拆分，子任务继承父任务 backend）
            if file_ext == ".zip" and not parent_task_id:
                if self._should_split_zip(task_id, file_path, task, options):
                    return

            # 4. 去水印
            if file_ext == ".pdf" and options.get("remove_watermark", False) and self.watermark_handler:
                try:
                    cleaned_path = self._preprocess_remove_watermark(file_path, options)
                    file_path = str(cleaned_path)
                except Exception as e:
                    logger.warning(f"⚠️ Watermark removal failed: {e}")

            # 5. 引擎路由
            result = None

            if backend == "sensevoice":
                if not SENSEVOICE_AVAILABLE:
                    raise ValueError("SenseVoice not available")
                result = self._process_audio(file_path, options)

            elif backend == "video":
                if not VIDEO_ENGINE_AVAILABLE:
                    raise ValueError("Video engine not available")
                result = self._process_video(file_path, options)

            elif "pipeline" in backend or "vlm-" in backend or "hybrid-" in backend:
                if not MINERU_PIPELINE_AVAILABLE:
                    raise ValueError("MinerU Pipeline not available")
                options["parse_mode"] = backend
                result = self._process_with_mineru(file_path, options)

            elif backend == "auto":
                if FORMAT_ENGINES_AVAILABLE and FormatEngineRegistry.is_supported(file_path):
                    result = self._process_with_format_engine(file_path, options)
                elif file_ext in [".wav", ".mp3", ".flac", ".m4a", ".ogg"] and SENSEVOICE_AVAILABLE:
                    result = self._process_audio(file_path, options)
                elif file_ext in [".mp4", ".avi", ".mkv", ".mov"] and VIDEO_ENGINE_AVAILABLE:
                    result = self._process_video(file_path, options)
                elif (
                    file_ext in [".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".pptx"]
                    and MINERU_PIPELINE_AVAILABLE
                ):
                    options["parse_mode"] = "pipeline"
                    result = self._process_with_mineru(file_path, options)
                elif file_ext in [".doc", ".xls", ".ppt"]:
                    # 旧版 Office 格式先用 LibreOffice 转为对应 OOXML 新格式，再走 MinerU 原生解析
                    try:
                        new_path = self._convert_office_to_new_format(file_path)
                        if MINERU_PIPELINE_AVAILABLE:
                            options["parse_mode"] = "pipeline"
                            result = self._process_with_mineru(new_path, options)
                        else:
                            raise ValueError("MinerU Pipeline not available for converted Office file")
                    except Exception as e:
                        logger.warning(f"⚠️ Old format conversion failed ({e}), falling back to MarkItDown")
                        if self.markitdown:
                            result = self._process_with_markitdown(file_path)
                        else:
                            raise ValueError(f"Unsupported file type: {file_ext}") from e
                elif file_ext in [".epub"] and self.markitdown:
                    # EPUB 电子书走 MarkItDown 原生支持
                    result = self._process_with_markitdown(file_path)
                elif self.markitdown:
                    result = self._process_with_markitdown(file_path)
                else:
                    raise ValueError(f"Unsupported file type for Auto mode: {file_ext}")

            else:
                if FORMAT_ENGINES_AVAILABLE:
                    engine = FormatEngineRegistry.get_engine(backend)
                    if engine:
                        result = self._process_with_format_engine(file_path, options, engine_name=backend)
                    else:
                        raise ValueError(f"Unknown backend: {backend}")
                else:
                    raise ValueError(f"Unknown backend: {backend}")

            if not result:
                raise ValueError("No result generated by engine")

            # 6. 保存完整结果到数据库 (包含 json_content 和 pdf_path)
            self.task_db.update_task_status(
                task_id=task_id,
                status="completed",
                result_path=result["result_path"],
                error_message=None,
                data=json.dumps(
                    {
                        "pdf_path": result.get("pdf_path"),  # 关键：供前端左侧预览使用
                        "json_content": result.get("json_content"),  # 关键：供前端右侧布局渲染使用
                        "markdown": result.get("content"),
                        "markdown_file": result.get("markdown_file"),
                    }
                ),
            )

            # 7. 合并子任务
            if parent_task_id:
                parent_id_to_merge = self.task_db.on_child_task_completed(task_id)
                if parent_id_to_merge:
                    try:
                        self._merge_parent_task_results(parent_id_to_merge)
                    except Exception as e:
                        self.task_db.update_task_status(parent_id_to_merge, "failed", error_message=str(e))

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            self.task_db.update_task_status(task_id, "failed", error_message=error_msg)
            if parent_task_id:
                self.task_db.on_child_task_failed(task_id, error_msg)
            raise

    # -------------------------------------------------------------------------
    # Helper: 确保 PDF 存在于 Output 目录
    # -------------------------------------------------------------------------
    def _ensure_pdf_in_output(self, file_path: str, output_dir: Path, preferred_name: str = None) -> str:
        """
        确保输出目录中有 PDF 文件，供前端预览使用。
        返回相对于 output_dir 的文件名。
        """
        output_dir = Path(output_dir)
        source_file = Path(file_path)

        # 1. 如果源文件不是 PDF (可能是图片)，尝试找转换后的 PDF
        if source_file.suffix.lower() != ".pdf":
            # 检查是否有 layout.pdf
            layout_pdfs = list(output_dir.glob("*_layout.pdf"))
            if layout_pdfs:
                return layout_pdfs[0].name
            return None

        # 2. 如果源文件是 PDF
        # 优先查找 MinerU 生成的带布局信息的 PDF
        layout_pdfs = list(output_dir.glob("*_layout.pdf"))
        if layout_pdfs:
            return layout_pdfs[0].name

        # 3. 如果没有布局 PDF，则复制源 PDF 到输出目录
        target_name = preferred_name or source_file.name
        target_path = output_dir / target_name

        if not target_path.exists():
            try:
                shutil.copy2(source_file, target_path)
                logger.info(f"📄 Copied source PDF to output: {target_name}")
            except Exception as e:
                logger.warning(f"Failed to copy source PDF: {e}")
                return None

        return target_name

    # -------------------------------------------------------------------------
    # Engine Processor Implementations
    # -------------------------------------------------------------------------
    def _process_with_mineru(self, file_path: str, options: dict) -> dict:
        if self.mineru_pipeline_engine is None:
            from mineru_pipeline import MinerUPipelineEngine

            self.mineru_pipeline_engine = MinerUPipelineEngine(
                device=self.engine_device, vlm_api_base=self.mineru_vllm_api
            )

        output_dir = Path(self.output_dir) / Path(file_path).stem
        output_dir.mkdir(parents=True, exist_ok=True)

        if "http-client" in options.get("parse_mode", "") and self.mineru_vllm_api:
            options.setdefault("server_url", self.mineru_vllm_api.replace("/v1", ""))

        result = self.mineru_pipeline_engine.parse(file_path, output_path=str(output_dir), options=options)

        # 图片描述处理器：管理员开启后，规范化时（RustFS 上传改 URL 之前）按文件名匹配写回 alt/img_caption
        caption_stats = None

        def caption_processor(proc_dir: Path, _norm_result: dict):
            nonlocal caption_stats
            caption_cfg = ImageCaptionConfig.load()
            if caption_cfg:
                caption_stats = process_output_dir(proc_dir, caption_cfg)

        actual_output = Path(result["result_path"])
        normalize_output(
            actual_output,
            image_processor=caption_processor if IMAGE_CAPTION_AVAILABLE else None,
        )

        # 扁平化目录结构
        if actual_output.resolve() != output_dir.resolve():
            try:
                for item in actual_output.iterdir():
                    dest = output_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    shutil.move(str(item), str(dest))
                shutil.rmtree(actual_output)
            except Exception as e:
                logger.warning(f"Flattening warning: {e}")

        # [修复] 确保 PDF 存在并返回路径
        pdf_path = self._ensure_pdf_in_output(file_path, output_dir)

        # 图片描述写回的是磁盘文件，这里刷新内存快照，保证 tasks.data 中携带描述
        if caption_stats and caption_stats.get("captioned"):
            try:
                md_file = output_dir / "result.md"
                if md_file.exists():
                    result["markdown"] = md_file.read_text(encoding="utf-8")
                json_file = output_dir / "result.json"
                if json_file.exists():
                    result["json_content"] = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"⚠️ Failed to refresh captioned result: {e}")

        return {
            "result_path": str(output_dir),
            "content": result.get("markdown", ""),
            "json_content": result.get("json_content"),
            "pdf_path": pdf_path,  # 返回给前端
            "markdown_file": result.get("markdown_file"),
        }

    def _process_audio(self, file_path: str, options: dict) -> dict:
        if self.sensevoice_engine is None:
            from audio_engines import SenseVoiceEngine

            self.sensevoice_engine = SenseVoiceEngine(device=self.engine_device)

        output_dir = Path(self.output_dir) / Path(file_path).stem
        output_dir.mkdir(parents=True, exist_ok=True)

        result = self.sensevoice_engine.parse(
            audio_path=file_path,
            output_path=str(output_dir),
            language=options.get("lang", "auto"),
            use_itn=options.get("use_itn", True),
            enable_speaker_diarization=options.get("enable_speaker_diarization", False),
        )
        normalize_output(output_dir)
        return {"result_path": str(output_dir), "content": result.get("markdown", "")}

    def _process_video(self, file_path: str, options: dict) -> dict:
        if self.video_engine is None:
            from video_engines import VideoProcessingEngine

            self.video_engine = VideoProcessingEngine(device=self.engine_device)

        output_dir = Path(self.output_dir) / Path(file_path).stem
        output_dir.mkdir(parents=True, exist_ok=True)

        result = self.video_engine.parse(
            video_path=file_path,
            output_path=str(output_dir),
            language=options.get("lang", "auto"),
            use_itn=options.get("use_itn", True),
            keep_audio=options.get("keep_audio", False),
            enable_keyframe_ocr=options.get("enable_keyframe_ocr", False),
            ocr_backend=options.get("ocr_backend", "mineru"),
            keep_keyframes=options.get("keep_keyframes", False),
        )

        (output_dir / f"{Path(file_path).stem}_video_analysis.md").write_text(result["markdown"], encoding="utf-8")
        normalize_output(output_dir)
        return {"result_path": str(output_dir), "content": result["markdown"]}

    def _process_with_markitdown(self, file_path: str) -> dict:
        if not self.markitdown:
            raise RuntimeError("MarkItDown not available")

        output_dir = Path(self.output_dir) / Path(file_path).stem
        output_dir.mkdir(parents=True, exist_ok=True)

        result = self.markitdown.convert(file_path)
        markdown_content = result.text_content

        (output_dir / f"{Path(file_path).stem}_markitdown.md").write_text(markdown_content, encoding="utf-8")
        normalize_output(output_dir)

        # MarkItDown 也可以尝试生成 PDF 预览 (如果源文件是 PDF)
        pdf_path = self._ensure_pdf_in_output(file_path, output_dir)

        return {"result_path": str(output_dir), "content": markdown_content, "pdf_path": pdf_path}

    def _process_with_format_engine(self, file_path: str, options: dict, engine_name: Optional[str] = None) -> dict:
        lang = options.get("language", "en")

        if engine_name:
            engine = FormatEngineRegistry.get_engine(engine_name)
        else:
            engine = FormatEngineRegistry.get_engine_by_extension(file_path)

        if not engine:
            raise ValueError("No format engine available")

        result = engine.parse(file_path, options={"language": lang})

        output_dir = Path(self.output_dir) / Path(file_path).stem
        output_dir.mkdir(parents=True, exist_ok=True)

        (output_dir / "result.md").write_text(result["markdown"], encoding="utf-8")
        (output_dir / "result.json").write_text(
            json.dumps(result["json_content"], indent=2, ensure_ascii=False), encoding="utf-8"
        )

        normalize_output(output_dir)
        return {"result_path": str(output_dir), "content": result["content"], "json_content": result["json_content"]}

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------
    def _convert_office_to_new_format(self, file_path: str) -> str:
        """将旧版 Office 格式转换为对应的 OOXML 新格式（供 MinerU 原生解析）。
        .doc → .docx   .xls → .xlsx   .ppt → .pptx
        """
        _fmt_map = {".doc": "docx", ".xls": "xlsx", ".ppt": "pptx"}
        input_file = Path(file_path)
        target_fmt = _fmt_map.get(input_file.suffix.lower())
        if not target_fmt:
            raise ValueError(f"Unsupported old format: {input_file.suffix}")

        final_new = input_file.parent / f"{input_file.stem}.{target_fmt}"
        if final_new.exists():
            final_new.unlink()

        try:
            with tempfile.TemporaryDirectory(prefix="libreoffice_") as temp_dir:
                temp_path = Path(temp_dir)
                temp_input = temp_path / input_file.name
                shutil.copy2(input_file, temp_input)

                cmd = [
                    "libreoffice",
                    "--headless",
                    "--convert-to",
                    target_fmt,
                    "--outdir",
                    str(temp_path),
                    str(temp_input),
                ]
                subprocess.run(cmd, check=True, timeout=120, capture_output=True)

                temp_new = temp_path / f"{input_file.stem}.{target_fmt}"
                if not temp_new.exists():
                    raise RuntimeError(f"{target_fmt} output missing")
                shutil.move(str(temp_new), str(final_new))
                logger.info(f"✅ Converted {input_file.suffix} → .{target_fmt}: {final_new}")
                return str(final_new)
        except Exception as e:
            raise RuntimeError(f"Old format conversion failed: {e}")

    def _preprocess_remove_watermark(self, file_path: str, options: dict) -> Path:
        if not self.watermark_handler:
            raise RuntimeError("Watermark handler missing")
        output_file = Path(self.output_dir) / f"{Path(file_path).stem}_no_watermark.pdf"

        kwargs = {}
        for k in [
            "auto_detect",
            "force_scanned",
            "remove_text",
            "remove_images",
            "remove_annotations",
            "watermark_keywords",
            "watermark_dpi",
            "watermark_conf_threshold",
            "watermark_dilation",
        ]:
            if k in options:
                kwargs[k.replace("watermark_", "")] = options[k]

        return self.watermark_handler.remove_watermark(input_path=file_path, output_path=str(output_file), **kwargs)

    def _should_split_pdf(self, task_id, file_path, task, options):
        from utils.pdf_utils import get_pdf_page_count, split_pdf_file

        if os.getenv("PDF_SPLIT_ENABLED", "true").lower() != "true":
            return False

        threshold = int(os.getenv("PDF_SPLIT_THRESHOLD_PAGES", "500"))
        chunk_size = int(os.getenv("PDF_SPLIT_CHUNK_SIZE", "500"))

        try:
            pages = get_pdf_page_count(Path(file_path))
            if pages <= threshold:
                return False

            logger.info(f"🔀 Splitting PDF ({pages} pages)...")
            self.task_db.convert_to_parent_task(task_id, child_count=0)
            split_dir = Path(self.output_dir) / "splits" / task_id
            split_dir.mkdir(parents=True, exist_ok=True)

            chunks = split_pdf_file(Path(file_path), split_dir, chunk_size, task_id)

            children = []
            for chunk in chunks:
                c_ops = options.copy()
                c_ops["chunk_info"] = {k: chunk[k] for k in ["start_page", "end_page", "page_count"]}
                children.append(
                    {
                        "file_name": f"{Path(file_path).stem}_p{chunk['start_page']}-{chunk['end_page']}.pdf",
                        "file_path": chunk["path"],
                        "options": c_ops,
                    }
                )

            # 单事务批量创建：切片数多时避免上百个背靠背的写事务反复锁住数据库
            self.task_db.create_child_tasks_bulk(
                parent_task_id=task_id,
                children=children,
                backend=task.get("backend", "auto"),
                priority=task.get("priority", 0),
                user_id=task.get("user_id"),
            )

            self.task_db.convert_to_parent_task(task_id, child_count=len(chunks))
            logger.info(f"✂️  Split into {len(chunks)} subtasks")
            return True
        except Exception as e:
            logger.error(f"❌ PDF split failed: {e}")
            return False

    # ZIP 解包安全限制：防 zip bomb 与恶意条目
    ZIP_MAX_ENTRIES = 200
    ZIP_MAX_TOTAL_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

    def _should_split_zip(self, task_id, file_path, task, options):
        """将 zip 压缩包解包为多个子任务（每个可解析文件一个子任务）。返回 True 表示已拆分。"""
        extract_dir = Path(self.output_dir) / "splits" / task_id

        try:
            if not zipfile.is_zipfile(file_path):
                logger.error(f"❌ Invalid zip file: {file_path}")
                return False

            entries = []  # (原始条目名, 解压后的文件路径)
            total_size = 0
            used_names = set()
            used_stems = set()

            with zipfile.ZipFile(file_path) as zf:
                infos = zf.infolist()
                if len(infos) > self.ZIP_MAX_ENTRIES:
                    logger.error(f"❌ ZIP has too many entries ({len(infos)} > {self.ZIP_MAX_ENTRIES})")
                    return False

                extract_dir.mkdir(parents=True, exist_ok=True)

                for info in infos:
                    # 跳过目录
                    if info.is_dir():
                        continue

                    # 统一分隔符后取基名，剥离压缩包内目录成分
                    entry_name = info.filename.replace("\\", "/")
                    base_name = entry_name.rsplit("/", 1)[-1]

                    # 跳过 macOS 资源叉与隐藏文件
                    if entry_name.startswith("__MACOSX/") or base_name.startswith("."):
                        continue

                    ext = Path(base_name).suffix.lower()

                    # 跳过嵌套压缩包，避免递归解包风险
                    if ext == ".zip":
                        logger.warning(f"⚠️  Skipping nested archive in zip: {entry_name}")
                        continue

                    # 仅解包平台支持解析的格式
                    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
                        logger.warning(f"⚠️  Skipping unsupported entry in zip: {entry_name}")
                        continue

                    # 防 zip bomb：按解压后大小逐条累计
                    total_size += info.file_size
                    if total_size > self.ZIP_MAX_TOTAL_SIZE:
                        logger.error(
                            f"❌ ZIP total extracted size exceeds limit ({self.ZIP_MAX_TOTAL_SIZE} bytes), aborting"
                        )
                        shutil.rmtree(extract_dir, ignore_errors=True)
                        return False

                    # 重名条目加序号后缀；stem 也需唯一（引擎按 stem 建输出目录，撞名会互相覆盖）
                    stem, suffix = os.path.splitext(base_name)
                    safe_name = base_name
                    seq = 2
                    while safe_name in used_names or os.path.splitext(safe_name)[0] in used_stems:
                        safe_name = f"{stem}_{seq}{suffix}"
                        seq += 1
                    used_names.add(safe_name)
                    used_stems.add(os.path.splitext(safe_name)[0])

                    target_path = extract_dir / safe_name
                    target_path.write_bytes(zf.read(info))
                    entries.append((base_name, target_path))

            # 全部条目都被跳过（无可解析文件）→ 走正常路由报不支持
            if not entries:
                shutil.rmtree(extract_dir, ignore_errors=True)
                logger.warning(f"⚠️  No parseable files in zip: {file_path}")
                return False

            self.task_db.convert_to_parent_task(task_id, child_count=0)

            for i, (entry_name, extracted_path) in enumerate(entries, start=1):
                c_ops = options.copy()
                c_ops["chunk_info"] = {"index": i, "entry_name": entry_name}
                self.task_db.create_child_task(
                    parent_task_id=task_id,
                    file_name=entry_name,
                    file_path=str(extracted_path),
                    backend=task.get("backend", "auto"),
                    options=c_ops,
                    priority=task.get("priority", 0),
                    user_id=task.get("user_id"),
                )

            self.task_db.convert_to_parent_task(task_id, child_count=len(entries))
            logger.info(f"📦 Extracted zip into {len(entries)} subtasks")
            return True
        except Exception as e:
            logger.error(f"❌ ZIP split failed: {e}")
            return False

    def _merge_parent_task_results(self, parent_task_id):
        parent_task = self.task_db.get_task_with_children(parent_task_id)
        children = parent_task.get("children", [])
        if not children:
            return

        # PDF 分片按 start_page 排序，zip 解包子任务按解包序号 index 排序
        def _chunk_sort_key(child):
            chunk_info = json.loads(child.get("options", "{}")).get("chunk_info", {})
            return chunk_info.get("start_page") or chunk_info.get("index") or 0

        children.sort(key=_chunk_sort_key)

        parent_out = Path(self.output_dir) / Path(parent_task["file_path"]).stem
        parent_out.mkdir(parents=True, exist_ok=True)

        md_parts, json_pages = [], []

        for child in children:
            if child["status"] != "completed":
                continue
            res_dir = Path(child["result_path"])
            chunk_info = json.loads(child.get("options", "{}")).get("chunk_info", {})

            md_file = next((f for f in res_dir.rglob("*.md") if f.name == "result.md"), None) or next(
                iter(res_dir.rglob("*.md")), None
            )
            if not md_file:
                continue
            md_text = md_file.read_text(encoding="utf-8")
            # zip 解包子任务按条目名加章节头；PDF 分片是连续文本，保持原样
            entry_name = chunk_info.get("entry_name")
            if entry_name:
                md_text = f"## {entry_name}\n\n{md_text}"
            md_parts.append(md_text)

            json_file = next((f for f in res_dir.rglob("*.json") if "result" in f.name or "content" in f.name), None)
            if json_file:
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    # 仅 PDF 分片需要页码偏移；zip 子任务（MarkItDown 等）通常没有版面 json
                    start_page = chunk_info.get("start_page")
                    offset = (start_page - 1) if start_page else 0

                    # 兼容不同的 JSON 格式
                    pages = []
                    if isinstance(data, list):
                        pages = data
                    elif "pages" in data:
                        pages = data["pages"]

                    for p in pages:
                        # 修正页码偏移
                        if "page_idx" in p:
                            p["page_idx"] += offset
                        json_pages.append(p)
                except Exception:
                    pass

        (parent_out / "result.md").write_text("\n\n\n\n".join(md_parts), encoding="utf-8")
        if json_pages:
            (parent_out / "result.json").write_text(
                json.dumps(json_pages, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        # [修复] 复制父任务的源文件到输出（zip 父任务源文件非 PDF 且无 layout pdf，返回 None，无碍）
        self._ensure_pdf_in_output(parent_task["file_path"], parent_out)

        normalize_output(parent_out)
        self.task_db.update_task_status(parent_task_id, "completed", result_path=str(parent_out))
        self._cleanup_child_task_files(children)

    def _cleanup_child_task_files(self, children):
        for child in children:
            try:
                if child.get("file_path"):
                    Path(child["file_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        # 清理拆分遗留的空目录（PDF 分片与 zip 解压文件都在 splits/{task_id}/ 下）
        split_dirs = {Path(c["file_path"]).parent for c in children if c.get("file_path")}
        for d in split_dirs:
            try:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            except Exception:
                pass

    # LitServe Interfaces
    def decode_request(self, request):
        return request.get("action", "health")

    def predict(self, action):
        if action == "health":
            return {"status": "healthy", "worker_id": self.worker_id}
        elif action == "poll":
            if self.enable_worker_loop:
                return {"status": "skipped", "message": "Auto-loop active"}
            task = self.task_db.pull_task()
            if task:
                try:
                    self._process_task(task)
                    return {"status": "completed", "task_id": task["task_id"]}
                except Exception as e:
                    return {"status": "failed", "error": str(e)}
            return {"status": "empty"}
        return {"status": "error", "message": "Invalid action"}

    def encode_response(self, response):
        return response

    def teardown(self):
        self.running = False
        if hasattr(self, "worker_thread"):
            self.worker_thread.join(timeout=2)


def start_litserve_workers(
    output_dir=None,
    accelerator="auto",
    devices="auto",
    workers_per_device=1,
    port=8001,
    poll_interval=0.5,
    enable_worker_loop=True,
    mineru_vllm_api_list=[],
):
    def resolve_auto_accelerator():
        try:
            from importlib.metadata import distribution

            distribution("torch")
            if check_cuda_with_nvidia_smi() > 0:
                return "cuda"
            # Apple Silicon: 使用 MPS 加速（LitServe 原生支持 mps）
            import platform

            import torch

            if torch.backends.mps.is_available() and platform.machine() in ("arm64", "arm"):
                return "mps"
        except Exception:
            pass
        return "cpu"

    if output_dir is None:
        output_dir = os.getenv("OUTPUT_PATH", str(Path(__file__).parent.parent / "data" / "output"))

    if accelerator == "auto":
        accelerator = resolve_auto_accelerator()

    logger.info(f"🚀 Starting Worker | Acc: {accelerator} | Devices: {devices} | Out: {output_dir}")

    api = MinerUWorkerAPI(
        output_dir=output_dir,
        poll_interval=poll_interval,
        enable_worker_loop=enable_worker_loop,
        mineru_vllm_api_list=mineru_vllm_api_list,
    )

    server = ls.LitServer(
        api,
        accelerator=accelerator,
        devices=devices,
        workers_per_device=workers_per_device,
        timeout=False,
    )

    def graceful_shutdown(signum=None, frame=None):
        if hasattr(api, "teardown"):
            api.teardown()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    atexit.register(lambda: api.teardown() if hasattr(api, "teardown") else None)

    server.run(port=port, generate_client_file=False)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--accelerator", type=str, default="auto")
    parser.add_argument("--workers-per-device", type=int, default=1)
    parser.add_argument("--devices", type=str, default="auto")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--disable-worker-loop", action="store_true")
    parser.add_argument("--mineru-vllm-api-list", type=parse_list_arg, default=[])
    args = parser.parse_args()

    # Env Var Fallbacks
    devices = args.devices
    if devices == "auto":
        env_dev = os.getenv("CUDA_VISIBLE_DEVICES")
        if env_dev:
            devices = env_dev

    port = args.port
    if port == 8001:
        port = int(os.getenv("WORKER_PORT", "8001"))

    # [核心修复] 强制并发控制：优先使用环境变量，默认为 1
    # 用户可以在 .env 中设置 MAX_CONCURRENT_TASKS=1 来限制
    env_workers = os.getenv("MAX_CONCURRENT_TASKS", "1")
    workers_per_device = int(env_workers)

    logger.info(f"⚙️  Concurrency Config: workers_per_device={workers_per_device} (env: {env_workers})")

    start_litserve_workers(
        output_dir=args.output_dir,
        accelerator=args.accelerator,
        devices=devices,
        workers_per_device=workers_per_device,  # 使用处理后的变量
        port=port,
        poll_interval=args.poll_interval,
        enable_worker_loop=not args.disable_worker_loop,
        mineru_vllm_api_list=args.mineru_vllm_api_list,
    )
