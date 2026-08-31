"""
MinerU Tianshu - API Server
天枢 API 服务器

企业级 AI 数据预处理平台
支持文档、图片、音频、视频等多模态数据处理
提供 RESTful API 接口用于任务提交、查询和管理
企业级认证授权: JWT Token + API Key + SSO
"""

import json
import os
import re
import uuid
import shutil  # ✅ 用于删除非空目录
import mimetypes  # ✅ 用于自动识别文件类型
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

import anyio
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from loguru import logger
from starlette.types import ASGIApp, Receive, Scope, Send  # ✅ 用于底层中间件

# 导入认证模块
from auth import (
    User,
    Permission,
    get_current_active_user,
    require_permission,
)
from auth.auth_db import AuthDB
from auth.routes import router as auth_router
from task_db import TaskDB

# ✅ [优化] 预注册 MIME 类型，防止精简环境识别失败导致浏览器强制下载
mimetypes.add_type("application/pdf", ".pdf")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/jpeg", ".jpeg")
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("application/json", ".json")

# 初始化 FastAPI 应用
app = FastAPI(
    title="MinerU Tianshu API",
    description="天枢 - 企业级 AI 数据预处理平台 | 支持文档、图片、音频、视频等多模态数据处理 | 企业级认证授权",
    version="2.0.0",
    # 不设置 servers，让 FastAPI 自动根据请求的 Host 生成
)


# ============================================================================
# ✅ 终极修复：ASGI 路径重写中间件
# 彻底解决 Nginx proxy_pass 剥离 /api/ 导致所有后端接口(特别是 auth)报 404 的问题
# ============================================================================
class NginxPathRewriteMiddleware:
    """拦截底层 ASGI 请求，给被 Nginx 剥离的路径补全前缀"""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            # 如果收到 Nginx 发来的 /v1/...，自动补全为 /api/v1/...
            if path.startswith("/v1/"):
                scope["path"] = f"/api{path}"
                # 某些底层组件匹配强依赖 raw_path，也一并修改
                if "raw_path" in scope:
                    scope["raw_path"] = b"/api" + scope["raw_path"]
        await self.app(scope, receive, send)


# 必须最先添加此中间件！
app.add_middleware(NginxPathRewriteMiddleware)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 获取项目根目录（backend 的父目录）
PROJECT_ROOT = Path(__file__).parent.parent

# 初始化数据库
# 确保使用环境变量中的数据库路径（与 Worker 保持一致）
db_path_env = os.getenv("DATABASE_PATH")
if db_path_env:
    db_path = str(Path(db_path_env).resolve())
    logger.info(f"📊 API Server using DATABASE_PATH: {db_path_env} -> {db_path}")
    db = TaskDB(db_path)
else:
    logger.warning("⚠️  DATABASE_PATH not set in API Server, using default")
    # Docker 环境: /app/data/db/mineru_tianshu.db
    # 本地环境: ./data/db/mineru_tianshu.db
    default_db_path = PROJECT_ROOT / "data" / "db" / "mineru_tianshu.db"
    default_db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path = str(default_db_path.resolve())
    logger.info(f"📊 Using default database path: {db_path}")
    db = TaskDB(db_path)
auth_db = AuthDB()

# 注册认证路由
app.include_router(auth_router)

# ==============================================================================
# 目录配置 (Output & Upload)
# ==============================================================================

# 1. 配置输出目录（使用共享目录，Docker 环境可访问）
output_path_env = os.getenv("OUTPUT_PATH")
if output_path_env:
    OUTPUT_DIR = Path(output_path_env).resolve()
else:
    # Docker 环境: /app/output
    # 本地环境: ./data/output
    OUTPUT_DIR = (PROJECT_ROOT / "data" / "output").resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"📁 Output directory: {OUTPUT_DIR}")

# 2. 配置上传目录 (修改默认为 input)
upload_path_env = os.getenv("UPLOAD_PATH")
if upload_path_env:
    UPLOAD_DIR = Path(upload_path_env).resolve()
else:
    # Docker 环境: /app/input (如果不设置环境变量)
    # 本地环境: ./input (项目根目录下的 input 目录)
    UPLOAD_DIR = (PROJECT_ROOT / "input").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"📁 Upload directory: {UPLOAD_DIR}")


# 注意：此函数已废弃，Worker 已自动上传图片到 RustFS 并替换 URL
def process_markdown_images_legacy(md_content: str, image_dir: Path, result_path: str):
    """
    【向后兼容】处理 Markdown 中的图片引用
    """
    if "http://" in md_content or "https://" in md_content:
        return md_content

    if not image_dir.exists():
        return md_content

    def replace_image_path(match):
        full_match = match.group(0)
        if "![" in full_match:
            image_path = match.group(2)
            alt_text = match.group(1)
        else:
            image_path = match.group(2)
            alt_text = "Image"

        if image_path.startswith("http"):
            return full_match

        try:
            image_filename = Path(image_path).name
            output_dir_str = str(OUTPUT_DIR).replace("\\", "/")
            result_path_str = result_path.replace("\\", "/")

            if result_path_str.startswith(output_dir_str):
                relative_path = result_path_str[len(output_dir_str) :].lstrip("/")
                encoded_relative_path = quote(relative_path, safe="/")
                encoded_filename = quote(image_filename, safe="/")

                static_url = f"/api/v1/files/output/{encoded_relative_path}/images/{encoded_filename}"

                if "![" in full_match:
                    return f"![{alt_text}]({static_url})"
                else:
                    return full_match.replace(image_path, static_url)
        except Exception as e:
            logger.error(f"❌ Failed to generate local URL: {e}")

        return full_match

    try:
        md_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
        html_pattern = r'<img\s+([^>]*\s+)?src="([^"]+)"([^>]*)>'

        new_content = re.sub(md_pattern, replace_image_path, md_content)
        new_content = re.sub(html_pattern, replace_image_path, new_content)
        return new_content
    except Exception:
        return md_content


@app.get("/", tags=["系统信息"])
async def root():
    """API根路径"""
    return {
        "service": "MinerU Tianshu",
        "version": "2.0.0",
        "description": "天枢 - 企业级 AI 数据预处理平台",
        "features": "文档、图片、音频、视频等多模态数据处理",
        "docs": "/docs",
    }


# ============================================================================
# 创建 API Router
# ============================================================================
router = APIRouter()


@router.post("/tasks/submit", tags=["任务管理"])
async def submit_task(
    file: UploadFile = File(..., description="文件: PDF/图片/Office/HTML/音频/视频等多种格式"),
    backend: str = Form(
        "auto",
        description="处理后端: pipeline, hybrid-auto-engine, vlm-auto-engine, hybrid-http-client, vlm-http-client, paddleocr-vl, etc.",
    ),
    lang: str = Form("auto", description="语言: ch/en/auto..."),
    method: str = Form("auto", description="解析方法: auto/txt/ocr"),
    formula_enable: bool = Form(True, description="是否启用公式识别"),
    table_enable: bool = Form(True, description="是否启用表格识别"),
    priority: int = Form(0, description="优先级，数字越大越优先"),
    start_page: Optional[int] = Form(None, description="起始页码（从0开始）"),
    end_page: Optional[int] = Form(None, description="结束页码"),
    force_ocr: bool = Form(False, description="[兼容旧版] 是否强制使用OCR"),
    server_url: Optional[str] = Form(None, description="远程服务器地址 (仅 Client 模式需要)"),
    draw_layout_bbox: bool = Form(True, description="绘制布局边框 (_layout.pdf)"),
    draw_span_bbox: bool = Form(True, description="绘制文本边框 (_span.pdf)"),
    dump_markdown: bool = Form(True, description="输出 Markdown"),
    dump_middle_json: bool = Form(True, description="输出中间 JSON"),
    dump_model_output: bool = Form(True, description="输出模型原始数据"),
    dump_content_list: bool = Form(True, description="输出内容列表"),
    dump_orig_pdf: bool = Form(True, description="保存原始/截取 PDF"),
    draw_layout: bool = Form(True, description="[兼容旧版] 是否绘制布局边框"),
    draw_span: bool = Form(True, description="[兼容旧版] 是否绘制文本Span边框"),
    keep_audio: bool = Form(False, description="视频处理时是否保留提取的音频文件"),
    enable_keyframe_ocr: bool = Form(False, description="是否启用视频关键帧OCR识别（实验性功能）"),
    ocr_backend: str = Form("paddleocr-vl", description="关键帧OCR引擎: paddleocr-vl"),
    keep_keyframes: bool = Form(False, description="是否保留提取的关键帧图像"),
    enable_speaker_diarization: bool = Form(False, description="是否启用说话人分离"),
    remove_watermark: bool = Form(False, description="是否启用水印去除"),
    watermark_conf_threshold: float = Form(0.35, description="水印检测置信度阈值"),
    watermark_dilation: int = Form(10, description="水印掩码膨胀大小"),
    convert_office_to_pdf: bool = Form(False, description="是否将 Office 文件转换为 PDF 后再处理"),
    useDocOrientationClassify: bool = Form(False, description="文档方向分类"),
    useDocUnwarping: bool = Form(False, description="文档去弯曲"),
    useLayoutDetection: bool = Form(True, description="是否启用版面分析"),
    useChartRecognition: bool = Form(False, description="是否启用图表识别"),
    useSealRecognition: bool = Form(True, description="是否启用印章识别"),
    useOcrForImageBlock: bool = Form(False, description="是否对图像块进行OCR"),
    mergeTables: bool = Form(True, description="是否合并表格"),
    relevelTitles: bool = Form(True, description="是否重构标题层级"),
    layoutShapeMode: str = Form("auto", description="版面形状模式"),
    promptLabel: str = Form("ocr", description="提示词标签"),
    repetitionPenalty: float = Form(1.0, description="重复惩罚"),
    temperature: float = Form(0.0, description="温度"),
    topP: float = Form(1.0, description="Top P"),
    minPixels: int = Form(147384, description="最小像素"),
    maxPixels: int = Form(2822400, description="最大像素"),
    layoutNms: bool = Form(True, description="是否启用版面 NMS"),
    restructurePages: bool = Form(True, description="是否重构页面"),
    markdownIgnoreLabels: str = Form(
        "header,header_image,footer,footer_image,number,footnote,aside_text", description="忽略的标签 (逗号分隔)"
    ),
    current_user: User = Depends(require_permission(Permission.TASK_SUBMIT)),
):
    try:
        unique_filename = f"{uuid.uuid4().hex}_{file.filename}"
        temp_file_path = UPLOAD_DIR / unique_filename

        # 异步写盘：同步的 temp_file.write() 会在写入期间冻结事件循环，uvicorn 期间
        # 不读取任何 socket —— 包括其它正在上传的连接。块大小从 8MB 降到 1MB，让出更均匀。
        async with await anyio.open_file(temp_file_path, "wb") as temp_file:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                await temp_file.write(chunk)

        options = {
            "lang": lang,
            "method": method,
            "formula_enable": formula_enable,
            "table_enable": table_enable,
            "start_page": start_page,
            "end_page": end_page,
            "force_ocr": force_ocr,
            "server_url": server_url,
            "draw_layout_bbox": draw_layout_bbox,
            "draw_span_bbox": draw_span_bbox,
            "dump_markdown": dump_markdown,
            "dump_middle_json": dump_middle_json,
            "dump_model_output": dump_model_output,
            "dump_content_list": dump_content_list,
            "dump_orig_pdf": dump_orig_pdf,
            "draw_layout": draw_layout,
            "draw_span": draw_span,
            "keep_audio": keep_audio,
            "enable_keyframe_ocr": enable_keyframe_ocr,
            "ocr_backend": ocr_backend,
            "keep_keyframes": keep_keyframes,
            "enable_speaker_diarization": enable_speaker_diarization,
            "remove_watermark": remove_watermark,
            "watermark_conf_threshold": watermark_conf_threshold,
            "watermark_dilation": watermark_dilation,
            "convert_office_to_pdf": convert_office_to_pdf,
            "useDocOrientationClassify": useDocOrientationClassify,
            "useDocUnwarping": useDocUnwarping,
            "useLayoutDetection": useLayoutDetection,
            "useChartRecognition": useChartRecognition,
            "useSealRecognition": useSealRecognition,
            "useOcrForImageBlock": useOcrForImageBlock,
            "mergeTables": mergeTables,
            "relevelTitles": relevelTitles,
            "layoutShapeMode": layoutShapeMode,
            "promptLabel": promptLabel,
            "repetitionPenalty": repetitionPenalty,
            "temperature": temperature,
            "topP": topP,
            "minPixels": minPixels,
            "maxPixels": maxPixels,
            "layoutNms": layoutNms,
            "restructurePages": restructurePages,
            "markdownIgnoreLabels": [label.strip() for label in markdownIgnoreLabels.split(",") if label.strip()],
        }

        options["upload_images"] = os.getenv("RUSTFS_ENABLED", "true").lower() == "true"

        # 本端点必须保持 async（要 await file.read()），因此把同步的 SQLite 写入
        # 显式丢到线程池，避免拿不到写锁时冻结整个事件循环。
        task_id = await anyio.to_thread.run_sync(
            lambda: db.create_task(
                file_name=file.filename,
                file_path=str(temp_file_path),
                backend=backend,
                options=options,
                priority=priority,
                user_id=current_user.user_id,
            )
        )

        logger.info(f"✅ Task submitted: {task_id} - {file.filename}")
        return {
            "success": True,
            "task_id": task_id,
            "status": "pending",
            "message": "Task submitted successfully",
            "file_name": file.filename,
            "user_id": current_user.user_id,
            "created_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"❌ Failed to submit task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}", tags=["任务管理"])
def get_task_status(
    task_id: str,
    upload_images: bool = Query(False, description="【已废弃】图片已自动上传到 RustFS"),
    format: str = Query("markdown", description="返回格式: markdown(默认)/json/both"),
    current_user: User = Depends(get_current_active_user),
):
    task = db.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_VIEW_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied: You can only view your own tasks")

    source_url = None
    if task.get("file_path"):
        try:
            source_filename = Path(task["file_path"]).name
            encoded_source_filename = quote(source_filename)
            source_url = f"/api/v1/files/upload/{encoded_source_filename}"
        except Exception as e:
            logger.warning(f"Failed to generate source_url: {e}")

    response = {
        "success": True,
        "task_id": task_id,
        "status": task["status"],
        "file_name": task["file_name"],
        "source_url": source_url,
        "backend": task["backend"],
        "priority": task["priority"],
        "error_message": task["error_message"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "completed_at": task["completed_at"],
        "user_id": task.get("user_id"),
    }

    if not task.get("is_parent"):
        response["worker_id"] = task.get("worker_id")
        response["retry_count"] = task.get("retry_count")
        response["result_path"] = task.get("result_path")

    if task.get("is_parent"):
        child_count = task.get("child_count", 0)
        child_completed = task.get("child_completed", 0)
        response["is_parent"] = True
        response["subtask_progress"] = {
            "total": child_count,
            "completed": child_completed,
            "percentage": round(child_completed / child_count * 100, 1) if child_count > 0 else 0,
        }
        try:
            children = db.get_child_tasks(task_id)
            response["subtasks"] = [
                {
                    "task_id": child["task_id"],
                    "status": child["status"],
                    "chunk_info": json.loads(child.get("options", "{}")).get("chunk_info"),
                    "error_message": child.get("error_message"),
                }
                for child in children
            ]
        except Exception:
            pass

    if task["status"] == "completed":
        if not task["result_path"] or task["result_path"] == "CLEARED":
            response["data"] = None
            response["message"] = "Task completed but result files have been cleaned up"
            return response

        result_dir = Path(task["result_path"])
        if result_dir.exists():
            md_files = list(result_dir.rglob("*.md"))
            json_files = [
                f
                for f in result_dir.rglob("*.json")
                if not f.parent.name.startswith("page_")
                and (f.name in ["content.json", "result.json"] or "_content_list.json" in f.name)
            ]

            if md_files or json_files:
                try:
                    response["data"] = {}
                    response["data"]["json_available"] = len(json_files) > 0

                    pdf_files = list(result_dir.rglob("*.pdf"))
                    preview_pdf = None
                    for pdf in pdf_files:
                        if "_layout.pdf" in pdf.name:
                            preview_pdf = pdf
                            break
                    if not preview_pdf:
                        for pdf in pdf_files:
                            if "_span.pdf" in pdf.name:
                                preview_pdf = pdf
                                break
                    if not preview_pdf:
                        for pdf in pdf_files:
                            if not pdf.name.startswith("page_"):
                                preview_pdf = pdf
                                break

                    if preview_pdf:
                        try:
                            rel_path = preview_pdf.relative_to(OUTPUT_DIR)
                            encoded_path = quote(str(rel_path).replace("\\", "/"), safe="/")
                            response["data"]["pdf_path"] = encoded_path
                        except ValueError:
                            pass

                    if format in ["markdown", "both"] and md_files:
                        md_file = next((f for f in md_files if f.name == "result.md"), md_files[0])
                        image_dir = md_file.parent / "images"
                        with open(md_file, "r", encoding="utf-8") as f:
                            md_content = f.read()

                        if image_dir.exists() and ("http://" not in md_content and "https://" not in md_content):
                            md_content = process_markdown_images_legacy(md_content, image_dir, task["result_path"])

                        response["data"]["markdown_file"] = md_file.name
                        response["data"]["content"] = md_content
                        response["data"]["has_images"] = image_dir.exists()

                    if format in ["json", "both"] and json_files:
                        import json as json_lib

                        json_file = json_files[0]
                        try:
                            with open(json_file, "r", encoding="utf-8") as f:
                                json_content = json_lib.load(f)
                            response["data"]["json_file"] = json_file.name
                            response["data"]["json_content"] = json_content
                        except Exception:
                            pass
                    elif format == "json" and not json_files:
                        response["data"]["message"] = "JSON format not available for this backend"

                    if not response["data"]:
                        response["data"] = None

                except Exception as e:
                    logger.error(f"❌ Failed to read content: {e}")
                    response["data"] = None
        else:
            logger.error(f"❌ Result directory does not exist: {result_dir}")

    return response


# ========================================================================
# 🚨 终极修复：物理清理任务接口（解决清理失败、任务依然存在问题）
# ========================================================================


@router.delete("/tasks/{task_id}", tags=["任务管理"])
def delete_task(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    【重构】彻底删除任务及其本地文件
    不仅取消 pending 的任务，还会物理抹除文件和数据库记录。
    """
    task = db.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 权限检查
    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied: You can only delete your own tasks")

    # 1. 物理删除 Output 文件夹
    output_dir = OUTPUT_DIR / task_id
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)

    # 2. 物理删除 Upload 的源文件
    if task.get("file_path"):
        file_path = Path(task["file_path"])
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete source file: {e}")

    # 3. 从数据库彻底移除记录
    with db.get_cursor() as cursor:
        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    logger.info(f"🗑️ Task completely deleted: {task_id} by user {current_user.username}")
    return {"success": True, "message": "Task and files completely deleted."}


@router.delete("/tasks/failed/clear", tags=["任务管理"])
def clear_failed_tasks_endpoint(current_user: User = Depends(require_permission(Permission.TASK_DELETE_ALL))):
    """
    【重构】一键清理所有失败的任务，包含物理清除文件
    """
    with db.get_cursor() as cursor:
        # 获取所有失败的任务信息
        cursor.execute("SELECT task_id, file_path FROM tasks WHERE status = 'failed'")
        failed_tasks = [dict(row) for row in cursor.fetchall()]

        deleted_count = 0
        for task in failed_tasks:
            t_id = task.get("task_id")
            f_path = task.get("file_path")

            # 删除 Output 文件夹
            output_dir = OUTPUT_DIR / t_id
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

            # 删除上传的源文件
            if f_path and Path(f_path).exists():
                try:
                    Path(f_path).unlink()
                except Exception:
                    pass

            # 从数据库中彻底删除
            cursor.execute("DELETE FROM tasks WHERE task_id = ?", (t_id,))
            deleted_count += 1

    logger.info(f"🧹 Cleared {deleted_count} failed tasks from DB and Disk.")
    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Successfully cleared {deleted_count} failed tasks.",
    }


# ========================================================================
# 修复：重试与暂停权限报错 (TASK_MANAGE_ALL -> TASK_DELETE_ALL)
# ========================================================================


@router.post("/tasks/{task_id}/retry", tags=["任务管理"])
def retry_task(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    重试失败的任务
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 🚨 修复属性名称错误
    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if db.retry_task(task_id):
        output_dir = OUTPUT_DIR / task_id
        if output_dir.exists():
            try:
                shutil.rmtree(output_dir)
            except Exception as e:
                logger.warning(f"Warning: Failed to clean up output directory for retried task {task_id}: {e}")

        return {"success": True, "message": "Task submitted for retry"}

    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/tasks/{task_id}/pause", tags=["任务管理"])
def pause_task_endpoint(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    暂停任务
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 🚨 修复属性名称错误
    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if db.pause_task(task_id):
        return {"success": True, "message": "Task paused"}

    raise HTTPException(status_code=409, detail="Task cannot be paused (must be in pending status)")


@router.post("/tasks/{task_id}/resume", tags=["任务管理"])
def resume_task_endpoint(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    恢复任务
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 🚨 修复属性名称错误
    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if db.resume_task(task_id):
        return {"success": True, "message": "Task resumed"}

    raise HTTPException(status_code=409, detail="Task cannot be resumed (must be in paused status)")


@router.post("/tasks/{task_id}/clear-cache", tags=["任务管理"])
def clear_task_cache_endpoint(task_id: str, current_user: User = Depends(get_current_active_user)):
    """
    清理任务缓存：仅删除 output 文件夹
    """
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not current_user.has_permission(Permission.TASK_DELETE_ALL):
        if task.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=403, detail="Permission denied")

    output_dir = OUTPUT_DIR / task_id
    if output_dir.exists():
        try:
            shutil.rmtree(output_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete files: {str(e)}")

    if db.clear_task_cache(task_id):
        return {"success": True, "message": "Task cache cleared, space freed"}

    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/queue/stats", tags=["队列管理"])
def get_queue_stats(current_user: User = Depends(require_permission(Permission.QUEUE_VIEW))):
    stats = db.get_queue_stats()
    return {
        "success": True,
        "stats": stats,
        "total": sum(stats.values()),
        "timestamp": datetime.now().isoformat(),
        "user": current_user.username,
    }


@router.get("/queue/tasks", tags=["队列管理"])
def list_tasks(
    status: Optional[str] = Query(None, description="筛选状态"),
    limit: int = Query(100, description="返回数量限制", le=1000),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    backend: Optional[str] = Query(None, description="筛选后端引擎"),
    search: Optional[str] = Query(None, description="搜索文件名或任务ID"),
    current_user: User = Depends(get_current_active_user),
):
    can_view_all = current_user.has_permission(Permission.TASK_VIEW_ALL)
    conditions = []
    params = []

    if not can_view_all:
        conditions.append("user_id = ?")
        params.append(current_user.user_id)

    if status:
        conditions.append("status = ?")
        params.append(status)
    if backend:
        conditions.append("backend = ?")
        params.append(backend)

    if search:
        search = search.strip()
        conditions.append("(file_name LIKE ? OR task_id = ?)")
        params.append(f"%{search}%")
        params.append(search)

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * page_size

    with db.get_cursor() as cursor:
        count_sql = f"SELECT COUNT(*) FROM tasks{where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        query_params = params + [page_size, offset]
        data_sql = f"""
            SELECT * FROM tasks
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(data_sql, query_params)
        tasks = [dict(row) for row in cursor.fetchall()]

    return {
        "success": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "count": len(tasks),
        "tasks": tasks,
        "can_view_all": can_view_all,
    }


@router.post("/admin/cleanup", tags=["系统管理"])
def cleanup_old_tasks(
    days: int = Query(7, description="清理N天前的任务"),
    current_user: User = Depends(require_permission(Permission.QUEUE_MANAGE)),
):
    deleted_count = db.cleanup_old_task_records(days)
    logger.info(f"🧹 Cleaned up {deleted_count} old tasks by {current_user.username}")
    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Cleaned up {deleted_count} tasks older than {days} days",
    }


@router.post("/admin/reset-stale", tags=["系统管理"])
def reset_stale_tasks(
    timeout_minutes: int = Query(60, description="超时时间（分钟）"),
    current_user: User = Depends(require_permission(Permission.QUEUE_MANAGE)),
):
    reset_count = db.reset_stale_tasks(timeout_minutes)
    logger.info(f"🔄 Reset {reset_count} stale tasks by {current_user.username}")
    return {
        "success": True,
        "reset_count": reset_count,
        "message": f"Reset tasks processing for more than {timeout_minutes} minutes",
    }


@router.get("/engines", tags=["系统信息"])
def list_engines():
    import importlib.util
    import importlib.metadata
    import sys

    def _pkg_version(pkg: str) -> str:
        try:
            return importlib.metadata.version(pkg)
        except Exception:
            return "N/A"

    # ── 运行环境信息 ──────────────────────────────────────────
    cuda_version = "N/A"
    gpu_name = "N/A"
    gpu_memory_gb = None
    try:
        import torch

        if torch.cuda.is_available():
            cuda_version = torch.version.cuda or "N/A"
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory_gb = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
    except Exception:
        pass

    system_info = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "cuda": cuda_version,
        "gpu": gpu_name,
        "gpu_memory_gb": gpu_memory_gb,
        "packages": {
            "mineru": _pkg_version("mineru"),
            "paddleocr": _pkg_version("paddleocr"),
            "paddlepaddle-gpu": _pkg_version("paddlepaddle-gpu"),
            "torch": _pkg_version("torch"),
            "transformers": _pkg_version("transformers"),
            "litserve": _pkg_version("litserve"),
        },
    }

    # ── 引擎列表 ──────────────────────────────────────────────
    mineru_ver = system_info["packages"]["mineru"]
    paddleocr_ver = system_info["packages"]["paddleocr"]

    engines = {
        "document": [
            {
                "name": "pipeline",
                "display_name": "Standard Pipeline",
                "version": mineru_ver,
                "description": "基于 PDF-Extract-Kit 的传统多模型管道，速度快，无幻觉，适合大多数文档。",
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg", ".docx"],
            },
            {
                "name": "vlm-auto-engine",
                "display_name": "MinerU VLM (视觉大模型)",
                "version": mineru_ver,
                "description": "基于 MinerU 3.X (1.2B) 视觉模型，擅长处理复杂排版、图表和非标准文档。DOCX 文件将使用原生解析。",
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg", ".docx"],
            },
            {
                "name": "hybrid-auto-engine",
                "display_name": "Hybrid High-Precision (高精度混合)",
                "version": mineru_ver,
                "description": "结合 Pipeline 的稳定性与 VLM 的理解能力，提供最高精度的解析效果。DOCX 文件将使用原生解析。",
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg", ".docx"],
            },
        ],
        "ocr": [],
        "audio": [],
        "video": [],
        "format": [],
        "office": [
            {
                "name": "MarkItDown (快速)",
                "value": "auto",
                "version": _pkg_version("markitdown"),
                "description": "Office 文档和文本文件转换引擎（快速但图片提取可能不完整）",
                "supported_formats": [".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".html", ".txt", ".csv"],
            },
            {
                "name": "LibreOffice + MinerU (完整)",
                "value": "auto",
                "version": mineru_ver,
                "description": "将 Office 文件转为 PDF 后使用 MinerU 处理（慢但图片提取完整）",
                "supported_formats": [".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"],
            },
        ],
    }

    if importlib.util.find_spec("paddleocr_vl") is not None:
        engines["ocr"].append(
            {
                "name": "paddleocr_vl",
                "display_name": "PaddleOCR-VL v1.5 (0.9B)",
                "version": paddleocr_ver,
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg"],
            }
        )

    if importlib.util.find_spec("paddleocr_vl_vllm") is not None:
        engines["ocr"].append(
            {
                "name": "paddleocr-vl-vllm",
                "display_name": "PaddleOCR-VL v1.5 (0.9B) (vLLM)",
                "version": paddleocr_ver,
                "supported_formats": [".pdf", ".png", ".jpg", ".jpeg"],
            }
        )

    if importlib.util.find_spec("audio_engines") is not None:
        engines["audio"].append(
            {
                "name": "sensevoice",
                "display_name": "SenseVoice",
                "version": _pkg_version("funasr"),
                "supported_formats": [".wav", ".mp3", ".flac", ".m4a", ".ogg"],
            }
        )

    if importlib.util.find_spec("video_engines") is not None:
        engines["video"].append(
            {
                "name": "video",
                "display_name": "Video Processing",
                "version": "N/A",
                "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv"],
            }
        )

    try:
        from format_engines import FormatEngineRegistry

        for engine_info in FormatEngineRegistry.list_engines():
            engines["format"].append(
                {
                    "name": engine_info["name"],
                    "display_name": engine_info["name"].upper(),
                    "version": engine_info.get("version", "N/A"),
                    "description": engine_info["description"],
                    "supported_formats": engine_info["extensions"],
                }
            )
    except ImportError:
        pass

    return {
        "success": True,
        "engines": engines,
        "system_info": system_info,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/health", tags=["系统信息"])
def health_check():
    try:
        stats = db.get_queue_stats()
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": "connected",
            "queue_stats": stats,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


@router.get("/files/output/{file_path:path}", tags=["文件服务"])
async def serve_output_file(file_path: str):
    """提供输出文件的访问服务"""
    try:
        decoded_path = unquote(file_path).lstrip("/")
        full_path = (OUTPUT_DIR / decoded_path).resolve()

        logger.debug(f"📥 Serving output file: {full_path}")

        if not full_path.is_relative_to(OUTPUT_DIR.resolve()) or not full_path.is_file():
            logger.warning(f"❌ Access denied or file not found: {full_path}")
            raise HTTPException(status_code=404, detail="File not found or access denied")

        media_type, _ = mimetypes.guess_type(full_path)
        media_type = media_type or "application/octet-stream"

        headers = {"Content-Disposition": f"inline; filename*=utf-8''{quote(full_path.name)}"}

        return FileResponse(path=str(full_path), media_type=media_type, headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error serving output file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/files/upload/{file_path:path}", tags=["文件服务"])
async def serve_upload_file(file_path: str):
    """提供上传源文件的访问服务"""
    try:
        decoded_path = unquote(file_path).lstrip("/")
        full_path = (UPLOAD_DIR / decoded_path).resolve()

        logger.debug(f"📥 Serving upload file: {full_path}")

        if not full_path.is_relative_to(UPLOAD_DIR.resolve()) or not full_path.is_file():
            logger.warning(f"❌ Access denied or file not found: {full_path}")
            raise HTTPException(status_code=404, detail="File not found or access denied")

        media_type, _ = mimetypes.guess_type(full_path)
        media_type = media_type or "application/octet-stream"

        headers = {"Content-Disposition": f"inline; filename*=utf-8''{quote(full_path.name)}"}

        return FileResponse(path=str(full_path), media_type=media_type, headers=headers)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error serving upload file: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


app.include_router(router, prefix="/api/v1")

logger.info(f"📁 File service mounted: /api/v1/files/output -> {OUTPUT_DIR}")
logger.info(f"📁 File service mounted: /api/v1/files/upload -> {UPLOAD_DIR}")

if __name__ == "__main__":
    api_port = int(os.getenv("API_PORT", "8000"))

    logger.info("🚀 Starting MinerU Tianshu API Server...")
    logger.info(f"📖 API Documentation: http://localhost:{api_port}/docs")

    uvicorn.run(app, host="0.0.0.0", port=api_port, log_level="info")
